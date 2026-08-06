# V1-4 Universal Memory Connectors

**Status:** Implemented  
**Last updated:** 2026-07-28  

All supported knowledge sources behave as first-class memories once imported. The Memory Intelligence Layer is **not** modified with connector-specific code.

---

## 1. Architecture

```
URL / upload / bookmark folder
        │
        ▼
 ConnectorRegistry.resolve_for_url (specific → general)
   youtube.v1 → github.v1 → pdf.v1 → web.v1 → bookmarks.v1
        │
        ▼
 SourceConnector.fetch_metadata + fetch_transcript
        │
        ▼
 ConnectorIngestService (generic)  ──or──  IngestService (YouTube-rich path)
        │
        ▼
 Chroma + FTS + UniversalMemory.finalize_ingest
        │
        ▼
 Memory Intelligence.on_memory_indexed (unchanged hook)
```

**Rule:** Source-specific I/O lives only inside connector modules.

---

## 2. Connectors

| ID | Source | Content |
|----|--------|---------|
| `youtube.v1` | YouTube | Captions + yt-dlp metadata (reference) |
| `web.v1` | Web articles | SSRF-safe fetch + trafilatura (HTML fallback) |
| `pdf.v1` | PDFs | pypdf page text; scanned/encrypted handled |
| `github.v1` | GitHub repos | Public API metadata + README |
| `bookmarks.v1` | Chrome bookmarks | Folder preview; delegates URL ingest |

Resolution order prefers specific hosts (YouTube/GitHub/PDF) before generic web.

---

## 3. Unified ingest

`ConnectorIngestService` indexes any connector into the same vector/FTS/universal-memory pipeline:

- Cross-connector duplicate check (`content_url_index`)
- Capsule + enrich + embed + Chroma (`source_type` + `connector_id` metadata)
- `finalize_ingest` → intelligence hook automatically

YouTube capture continues via `IngestService` for rich `YouTubeMemory` fields, and also registers into `content_url_index`.

---

## 4. Import Manager

`ImportManager` tracks:

- Queued / running / completed / failed / retries  
- Per-item status  
- Bookmark preview (count, duplicates, unsupported)  
- Connector health  

Tables: `import_runs`, `import_run_items` (schema v8).

---

## 5. Cross-connector duplicates

`CrossConnectorDuplicateDetector` matches:

1. Canonical URL hash  
2. Content hash  

Examples covered: bookmarked article later saved manually; same README URL; repeated imports.

---

## 6. Search & evidence

Hybrid/AHME search is source-agnostic. Hits include additive fields:

- `source_type`  
- `connector_id`  
- `citation_ref` (URL or `title p.N` for PDFs)  
- `page_number`  
- `import_date`  
- `confidence` / `why_matched` / matching sections  

Queries like “Find the Docker PDF” or “Kubernetes repository” work across the unified index.

---

## 7. APIs

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/capture/url` | Save any supported URL (async) |
| POST | `/api/v1/capture/pdf` | Upload PDF |
| POST | `/api/v1/capture/bookmarks/preview` | Bookmark import preview |
| POST | `/api/v1/capture/bookmarks/import` | Import bookmarks via ImportManager |
| GET | `/api/v1/imports` | Import history |
| GET | `/api/v1/imports/{id}` | Import detail + items |
| POST | `/api/v1/imports/{id}/start` | Start/resume import |
| GET | `/api/v1/connectors/health` | Per-connector health |

Existing search/chat/intelligence APIs unchanged.

---

## 8. Schema (v8)

- `import_runs` / `import_run_items`  
- `content_url_index`  

---

## 9. Dependencies

- `trafilatura` — readable article extraction  
- `pypdf` — PDF text extraction  
- `httpx` — SSRF-validated fetches  

---

## 10. Out of scope

Watch Later OAuth · Instagram · Reddit · X · LinkedIn · Memory OS · Consensus · Gap · Agents.

---

## 11. Extension points

Implement `SourceConnector`, register in `ConnectorRegistry`, route through `ConnectorIngestService` / ImportManager. No Intelligence Layer changes required.
