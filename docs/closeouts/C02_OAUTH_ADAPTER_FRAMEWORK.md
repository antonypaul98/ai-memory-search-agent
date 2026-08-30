# C-02 OAuth Adapter Framework — Acceptance Closeout Candidate

Status: validation pending

## Acceptance boundary

C-02 is the shared, provider-neutral OAuth credential framework required by connector integrations. The accepted boundary is the one defined in `FEATURE_IDEAS.md` and `CONNECTOR_SDK.md`:

- tenant-scoped encrypted credential storage with scoped metadata;
- refresh of an expiring token without forcing user re-login;
- connector credential revocation that disables later retrieval/use;
- durable audit evidence whenever a stored credential is used;
- no token material in audit payloads or connector-auth status responses.

Provider-specific consent screens, authorization URLs, callback exchanges, provider billing/verification, and provider-specific scopes remain integration concerns for the connector that uses this framework. C-02 does not fabricate or require live third-party credentials in automated tests.

## Implementation evidence

`app/services/oauth_token_vault.py` provides the shared framework:

- Fernet encryption at rest using an environment-provided encryption key;
- `(user_id, connector_id)` as the credential identity boundary;
- normalized scope metadata stored separately from encrypted token material;
- `get_valid(...)` refreshes once when a credential is expired or near expiry and persists token rotation;
- failed refresh leaves the prior stored record intact and emits a failure audit event;
- `revoke(...)` replaces the encrypted credential payload with an encrypted tombstone and disables the row;
- `get(...)` emits `connector.oauth.used` by default without putting access/refresh tokens into the audit payload.

`app/api/routes/connector_auth.py` exposes tenant-authenticated status/revoke operations. Status reports connection/scopes/expiry only and never returns access or refresh tokens.

## Automated acceptance evidence

`tests/test_oauth_token_vault.py` covers:

1. encrypted-at-rest storage and tenant isolation;
2. deterministic normalized scopes;
3. one-shot refresh and persisted credential rotation;
4. no unnecessary second refresh after a successful rotation;
5. revocation disables retrieval and erases retrievable secret material;
6. fail-closed behavior when the encryption key is not configured;
7. failed refresh does not replace the existing credential;
8. explicit `connector.oauth.used` audit emission with no secret material in the audit payload.

Full repository CI must pass on the exact PR head before this closeout is promoted from validation-pending to accepted/merged.

## Security and architecture invariants

- Credentials are always tenant scoped.
- Plaintext credentials are not stored in the relational row.
- Missing encryption configuration fails closed.
- Audit evidence records credential lifecycle/use without credential contents.
- OAuth work is on-demand; there is no background token polling loop.
- No secrets, live credentials, billing actions, or provider approvals are required for this acceptance gate.

## Out of scope

This closeout does not complete Google/Notion/Readwise provider authorization UX by itself and does not alter any Jarvis voice, vision, gesture, spatial, hologram, or hardware roadmap item.
