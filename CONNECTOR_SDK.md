# CONNECTOR SDK — Universal Ingestion Architecture

**Purpose:** Specification for pluggable content connectors — the ingestion layer of AI Memory OS.  
**Status:** Architecture phase — **F-29 Planned**; `BaseSource` is a stub.  
**Last updated:** 2026-07-18  
**Replaces:** Ad-hoc logic in `IngestService` and `CaptureService` over time (migration, not big-bang).

---

## 1. Design Goals

1. **One pipeline, many sources** — normalize to common memory primitives.  
2. **Security by default** — OAuth secrets isolated; SSRF rules for web.  
3. **Testable** — each connector ships unit tests + fixture payloads.  
4. **User-scoped** — every artifact tagged with `user_id` and `source_type`.  
5. **Job-friendly** — connectors expose batch/pagination for background workers.  
6. **Export symmetric** — import adapters paired with export adapters where possible.

---

## 2. Core Abstractions

### 2.1 SourceConnector (protocol)

```python
# Conceptual — not implemented yet (see app/services/sources/base_source.py stub)

class SourceConnector(Protocol):
    source_type: SourceType          # youtube, web_article, readwise, ...
    connector_id: str                # stable registry key e.g. "youtube.v1"

    def authenticate(self, credentials: ConnectorCredentials) -> AuthState: ...
    def health(self) -> ConnectorHealth: ...

    def fetch_item(self, ref: SourceRef) -> NormalizedItem: ...
    def fetch_batch(self, refs: list[SourceRef]) -> BatchResult: ...
    def list_discoverable(self, cursor: str | None) -> DiscoveryPage: ...  # optional

    def to_memory_plan(self, item: NormalizedItem, ctx: IngestContext) -> MemoryPlan: ...
```

### 2.2 NormalizedItem

Universal intermediate representation before capsule/chunk pipeline:

| Field | Type | Description |
|-------|------|-------------|
| `source_type` | enum | youtube, web, pdf, highlight, … |
| `external_id` | string | Stable ID in source system |
| `canonical_url` | string | Primary link |
| `title` | string | Display title |
| `author` | string | Channel, writer, etc. |
| `published_at` | datetime? | Content date |
| `duration_sec` | float? | Media length |
| `text_segments` | list | Timed or untimed text blocks |
| `raw_metadata` | dict | Connector-specific preserve |
| `content_hash` | string | Dedup key |

### 2.3 MemoryPlan

Output of connector — input to Knowledge Engine ingest:

| Field | Description |
|-------|-------------|
| `capsule_inputs` | Title, summary fields, reflection |
| `chunks` | Text + start/end times |
| `entities` | Optional pre-extracted entities |
| `attachments` | Thumbnails, PDF paths |
| `skip_reason` | If item should not ingest |

### 2.4 ConnectorRegistry

```text
connectors.yaml (or DB table connectors)
  connector_id → class path → enabled → config schema
```

Runtime: `get_connector(connector_id, settings) -> SourceConnector`

---

## 3. Adapter Families

### 3.1 OAuth Adapters (C-02)

**Purpose:** Connectors requiring user-delegated access (Google, Notion, Readwise API).

| Component | Responsibility |
|-----------|----------------|
| `OAuthAdapter` | Authorization URL, callback, refresh token |
| `TokenVault` | Encrypt tokens per user_id (env KMS key in prod) |
| `ScopeManifest` | Document required scopes per connector |

**Flow:**

```
User clicks Connect → redirect to provider → callback stores refresh token
  → Connector uses TokenVault.get(user_id, connector_id)
  → On 401: refresh once, then mark connector degraded
```

**Security:**

- Tokens never logged  
- Per-connector minimum scopes  
- Revoke endpoint: `DELETE /api/v1/connectors/{id}/auth`

**Acceptance criteria:**

- [ ] Token refresh without user re-login  
- [ ] Connector disabled on revoke  
- [ ] Audit log on token use  

---

### 3.2 Browser Extension Adapters (C-01 + F-22)

**Purpose:** Bridge MV3 extension → Capture API → connector routing.

| Surface | Role |
|---------|------|
| `extension/background.js` | POST `/api/v1/capture/url` |
| Capture API | Classify URL → route to connector |
| Extension adapter | Validates origin, attaches reflection payload |

**Payload (existing):**

```json
{
  "url": "https://...",
  "title": "page title",
  "goal": "optional",
  "note": "optional reflection"
}
```

**Future:**

- Signed capture tokens (JWT scoped to extension client_id)  
- Offline queue in extension storage → batch `/capture/batch`  
- Connector hint: `source_hint: "web_article"`

**Security:**

- CORS: `chrome-extension://` in `cors_origins`  
- Rate limit per token  
- No arbitrary JS execution server-side  

---

### 3.3 Share Sheet Adapters (C-09)

**Purpose:** Mobile/desktop OS share targets → memory capture.

| Platform | Entry |
|----------|-------|
| PWA | `/share?url=&text=&title=` (implemented) |
| Android TWA | Same manifest share_target |
| iOS | Universal link → `/share` |

**Adapter logic:**

```
Parse share payload → NormalizedItem (url required, text optional)
  → If YouTube URL → youtube connector
  → Else → web_article connector with SSRF fetch
```

**Acceptance criteria:**

- [ ] Share from mobile browser opens PWA with URL prefilled  
- [ ] One-tap ingest from share sheet  

---

### 3.4 Import Adapters (C-05, C-06, C-07)

**Purpose:** Bulk import from exports or third-party APIs.

| Adapter | Input | Output |
|---------|-------|--------|
| Readwise bridge | API or CSV export | Highlight → evidence chunks grouped by article |
| Notion export | ZIP of markdown | Pages → capsules + chunks |
| Bookmark import | JSON (existing API) | Queue for Capture Triage Agent |
| Podcast RSS | Feed URL | Episodes → metadata + show notes or transcript API |

**Readwise mapping example:**

```text
Readwise highlight → NormalizedItem segment
  → parent article NormalizedItem
  → MemoryPlan: capsule per article, chunks per highlight
  → Preserve Readwise tags as reflection tags
```

---

### 3.5 Export Adapters (C-08)

**Purpose:** User data portability — critical for OS positioning vs Mem/Notion lock-in.

| Format | Contents |
|--------|----------|
| Markdown vault | One file per video/article + YAML front matter |
| JSON archive | Full MemoryPlan + capsule JSON |
| CSV index | video_id, title, url, goal, trust_score |

**API (planned):** `POST /api/v1/export` → async job → download link

**Acceptance criteria:**

- [ ] Export includes timestamp URLs and reflection metadata  
- [ ] Re-importable via import adapter (round-trip test)  

---

## 4. Connector Catalog (Planned)

| ID | Connector | Priority | Auth | Status |
|----|-----------|----------|------|--------|
| `youtube.v1` | YouTube video/playlist | P0 | API key optional | **Complete (V1-2)** — `YouTubeConnector` + registry |
| `web_article.v1` / `web.v1` | HTTP(S) articles | P0 | None (SSRF) | **Complete (V1-4)** — trafilatura + SSRF |
| `pdf.v1` | PDF documents | P0 | None | **Complete (V1-4)** — pypdf |
| `github.v1` | GitHub repositories | P0 | Token optional | **Complete (V1-4)** — public README; starred OAuth later |
| `bookmarks.v1` | Browser bookmarks | P0 | Extension | **Complete (V1-4)** — preview + ImportManager |
| `readwise.v1` | Highlights | P2 | OAuth | Planned |
| `gdrive.v1` | Google Docs/PDF | P3 | OAuth | Planned |
| `notion.v1` | Notion export | P3 | OAuth/export | Planned |
| `podcast.v1` | RSS feeds | P3 | None | Planned |

---

## 5. Integration with Ingest Pipeline

### 5.1 Current path (V1-4)

```
POST /capture/url|/pdf|/bookmarks/* → CaptureService / ImportManager
GET  /imports|/connectors/health     → ImportManager
ConnectorRegistry → SourceConnector → ConnectorIngestService | IngestService(YouTube)
→ UniversalMemory.finalize_ingest → Memory Intelligence hook
```

### 5.2 Target path

```
API / Connector webhook
  → ConnectorRegistry.resolve(url | ref)
  → SourceConnector.fetch_item → NormalizedItem
  → MemoryPlanBuilder (shared)
  → CapsuleService + Chunking + Embeddings
  → MemoryRepository + HierarchicalStore + VideoRegistry
  → Event: memory.ingested
```

### 5.3 Migration plan

| Step | Action | Risk |
|------|--------|------|
| 1 | Implement `MemoryPlanBuilder` extracting shared logic from IngestService | Low |
| 2 | Wrap YouTube as `youtube.v1` connector calling existing services | Low |
| 3 | Route CaptureService through registry | Medium |
| 4 | Add Readwise connector | Medium |
| 5 | Deprecate direct IngestService public surface for new sources | Low |

---

## 6. Security Model

### 6.1 Threat matrix

| Threat | Mitigation |
|--------|------------|
| SSRF on web connector | `validate_public_http_url`; block private IP; size/time limits |
| OAuth token theft | Encrypted vault; short-lived access tokens |
| Malicious extension | Scoped JWT; rate limits; capture size cap |
| Cross-tenant ingest | `user_id` on all writes; connector credentials per user |
| Zip slip (Notion import) | Sandboxed extract path |
| API key leakage | Env vars only; never in repo |

### 6.2 Connector permission levels

| Level | Can do |
|-------|--------|
| `public` | Fetch public URLs (web, YouTube) |
| `authenticated` | OAuth read user content |
| `privileged` | Write back to source (future — off by default) |

### 6.3 Audit

Every connector call logs:

```json
{
  "user_id", "connector_id", "external_id", "action", "status", "duration_ms", "bytes"
}
```

---

## 7. Background Jobs & Connectors

Playlist ingest becomes:

```
POST /playlists/ingest
  → PlaylistConnector (youtube.v1) → list_discoverable pages
  → JobStore.create_playlist_job(entries from NormalizedItem refs)
  → JobWorker: for each item → connector.fetch_item → MemoryPlan → ingest
```

**Requirements:**

- Idempotent item keys: `{connector_id}:{external_id}`  
- Lease-based claims (existing JobStore)  
- Connector rate limit awareness (YouTube quota)

---

## 8. Configuration

```env
# Per-connector overrides (future)
CONNECTOR_YOUTUBE_ENABLED=true
CONNECTOR_READWISE_ENABLED=false
CONNECTOR_WEB_MAX_BYTES=2000000

# OAuth
OAUTH_CALLBACK_BASE=https://app.example.com/api/v1/connectors/callback
TOKEN_VAULT_KEY_ENV=TOKEN_VAULT_KEY
```

---

## 9. Testing Strategy

| Level | Approach |
|-------|----------|
| Unit | Mock fetch; assert NormalizedItem + MemoryPlan |
| Contract | Fixture files per connector in `tests/fixtures/connectors/` |
| Integration | Temp DB; ingest fixture URL with VCR |
| Security | SSRF test suite (extend `test_distribution`) |

---

## 10. Acceptance Criteria (SDK v1)

- [ ] `SourceConnector` protocol documented and enforced  
- [ ] `youtube.v1` passes all existing ingest tests unchanged  
- [ ] `web_article.v1` passes capture tests  
- [ ] Registry loads connectors from config  
- [ ] Connector health in `/api/v1/health` detail (optional)  
- [ ] CONNECTOR_SDK.md + MASTER_SPEC F-29 marked Partial  

---

## 11. Related Documents

| Doc | Role |
|-----|------|
| `MASTER_SPEC.md` | F-21, F-29, C-* IDs |
| `FEATURE_IDEAS.md` | Connector backlog |
| `AGENT_BIBLE.md` | Ingest/Capture agents use connectors |
| `COMPETITOR_BIBLE.md` | Readwise bridge opportunity |
