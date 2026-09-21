# Task C — Xero Integration Review

Multi-tenant service syncing invoices between an internal order system and Xero.
Background workers hold per-organisation OAuth tokens, tenant IDs and sync cursors.

Assumptions stated up front: **Xero OAuth 2.0 (authorization code grant), Accounting
API v2.0 (REST), official Python/Node SDK or plain HTTPS — behaviour described below
is at the HTTP level so it applies either way.** Access tokens expire after 30
minutes and are refreshed with the per-connection refresh token (see references).

---

## C1 — Connection verification

Smallest sequence that *proves* each layer before reading invoices:

1. **Token exchange/refresh succeeds** — `POST https://identity.xero.com/connect/token`
   with the refresh token returns a fresh `access_token`.
   *Proves:* the client credentials are valid and the refresh token was not
   revoked (user didn't disconnect the app). It says nothing about tenants.
2. **`GET https://api.xero.com/connections`** with `Authorization: Bearer <token>`.
   *Proves:* the access token is live **and** lists the tenant ids this user
   authorised. Assert the expected `tenantId` is present. An empty list = the
   authorisation exists but the user selected no organisation → re-consent needed.
3. **One cheap, scoped read against the chosen tenant** — e.g.
   `GET https://api.xero.com/api.xro/2.0/Organisations` with
   `Xero-Tenant-Id: <tenantId>` (or `GET /Invoices?page=1&pageSize=1` if you want
   to exercise the exact scope). Expect HTTP 200.
   *Proves:* the tenant header routing works, the tenant is still connected to
   this app, and the granted scopes cover the accounting endpoints.

Only after all three do we start reading invoices. Each step isolates a different
failure class: step 1 = auth grant, step 2 = consent/tenant selection,
step 3 = tenant routing + scopes. Persist the verified `(connection_id,
tenant_id)` pair with a timestamp so a later 4xx can be compared against "was
verified at time T".

## C2 — Failure diagnosis (401 / 403 / 404 on invoices, connections OK)

`GET /connections` succeeding while `/Invoices` fails means the token is valid —
the problem is tenant routing, scope, or resource availability:

```
Invoices request fails
├─ 401 Unauthorized
│  ├─ Token older than ~30 min? → expired access token: refresh once and retry.
│  │    If refresh itself fails → grant revoked; mark connection for re-auth.
│  └─ Fresh token still 401? → wrong environment: base URL / auth server of the
│       other env (demo vs production app keys mixed in config). Check the
│       client_id embedded in the token against the app registration.
├─ 403 Forbidden
│  ├─ Scope missing? Decode granted scopes from the consent (stored at connect
│     time): invoices endpoint needs `accounting.transactions.read` (or
│     `.submit` etc.). 403 + valid tenant = scope or tenant-type mismatch
│     (e.g. a Xero HQ/Payroll-only tenant hit with Accounting API, or trial/
│     subscription disabled).
│  ├─ Tenant header belongs to another org the token doesn't cover? → 403:
│     re-run GET /connections and diff the tenant list.
│  └─ Env difference: staging org may have a different plan/permissions;
│     compare org `organisationType`/subscription via /Organisations.
└─ 404 Not Found
   ├─ 403-like tenant problem usually returns 403, not 404 — a 404 on the
   │  collection endpoint means a wrong URL (typo, missing /api.xro/2.0,
   │  trailing path) or an API surface disabled for that tenant.
   └─ 404 on a *single* invoice by id → record genuinely deleted/never existed
      in that tenant; expected during reconciliation, not a connection fault.
```

Observable checks per branch: token age vs 30-min TTL; scope list vs required
scope; tenant id present in `/connections`; exact URL and headers echoed in the
request log (ids only, never tokens). Env config diff (client_id, redirect URI,
API base) compared between the failing and working environment.

## C3 — Incremental synchronisation (resumable, large org)

State per tenant, persisted transactionally with the last applied batch:

```
sync_cursor {
  tenant_id, modified_since_utc,      # high-water mark of last successful page
  page,                               # current page within a change window
  window_start_utc,                   # fixed "from" for the in-flight window
  etag/last_run_id, status
}
```

- **Change window**: query `GET /Invoices?where=...&page=n` with the
  `If-Modified-Since` header (or the `modifiedSince` query param) set to
  `window_start`. Pull only invoices modified after it.
- **Pagination**: Xero returns 100/page; walk `page=1..` until a short page.
  Store `page` in the cursor after each page so a crash resumes mid-window.
  Accept that pages can shift if data changes mid-window — mitigate by using a
  *fixed* `window_start` per pass and de-duplicating on `InvoiceID` (+
  `ModifiedDateTimeUTC`) at apply time, not by trusting page stability.
- **Clock safety**: set `window_start = last_success - overlap` (e.g. 5 minutes)
  to absorb clock skew and late writes; duplicates are harmless because apply is
  idempotent (upsert keyed on InvoiceID).
- **Advance only on durable apply**: commit the cursor in the same DB
  transaction that upserts the page's invoices. Crash between fetch and commit
  re-fetches the page (at-least-once + idempotent apply = effectively exactly-once).
- **Partial failure**: a page that fails mid-apply is retried; after N attempts
  the *invoice* goes to a dead-letter table with the cursor still pointing at
  the page — the run completes other tenants, and an alert fires. Never advance
  the cursor past an unapplied page.
- **Safe replay**: re-running a window is always allowed (upsert semantics);
  deleting the cursor forces a full resync, which is the documented escape hatch.
- **Deletes**: Xero's modified-since doesn't emit tombstones for purged records;
  schedule a nightly/weekly reconciliation pass comparing counts/ids to catch
  removals.

## C4 — Rate limits (HTTP 429)

Xero enforces per-app-per-tenant minute limits **and** a per-tenant daily limit
(60-second and 24-hour windows); a 429 carries **`Retry-After`** in seconds.

Worker behaviour:

1. **Honour `Retry-After` exactly** — park the *tenant's* job until then; do not
   busy-retry. Add jitter (±10–20%) so many tenants' workers don't wake in lockstep.
2. **Exponential backoff with jitter as fallback** when the header is missing:
   `min(cap, base * 2^attempt) + rand`.
3. **Concurrency limits**: one in-flight job per tenant, plus a global token
   bucket sized below the documented minute limit, so we rarely discover the
   limit via 429. The daily budget is tracked per tenant: when ~90% consumed,
   defer non-urgent syncs to the next UTC day instead of burning the remainder.
4. **Retry budget per job** (e.g. 3 attempts / max wall-time) — after that,
   reschedule the job (back of queue / next window) rather than blocking workers.
5. **Do not retry**: 400 validation errors (fix data, alert), 401 after one
   refresh attempt (re-auth flow), 403 (scope/tenant config — human action),
   404 on single records (record-level reconciliation, not transport retry).
   5xx: retry with backoff but cap attempts; sustained 5xx = circuit-break the
   tenant and alert.

## C5 — Data integrity (timeout on invoice create → duplicate risk)

Classic at-least-once transport: the request may have committed even though we
got no response.

- **Idempotency at the API boundary**: before POST, store the intent in the
  internal DB: `(internal_order_id, idempotency_key=UUID, state=IN_FLIGHT)`.
  Xero's create-invoice response includes `InvoiceID`; the idempotency key lets a
  retry be recognised. (Xero Accounting has no first-class Idempotency-Key
  header on creates, so the *reconcile* step is what closes the gap.)
- **On timeout, never blind-retry.** Move to `state=UNKNOWN_OUTCOME` and run a
  **reconcile-before-retry**: `GET /Invoices?where=InvoiceNumber eq '<stable ref>'`
  (we always send a deterministic `InvoiceNumber` derived from the internal
  order id, plus our `OrderNumber` in a custom field).
  - Found exactly one → adopt its `InvoiceID`, mark `SYNCED`.
  - Found none → safe to retry the POST with the same payload.
  - Found >1 (legacy bug) → quarantine, alert, human merge.
- **Prevention**: unique constraint on `(tenant, invoice_number)` in Xero means
  a duplicate POST is rejected with a validation error rather than creating a
  second invoice — turn that error into "already exists → reconcile".
- **Two-phase record**: internal invoice row has `xero_invoice_id` and a state
  machine `DRAFT → IN_FLIGHT → (SYNCED | FAILED)`; only `FAILED`/`UNKNOWN` with
  completed reconcile may re-dispatch. Retries after *any* timeout therefore
  cannot double-create, and a lost response can never lose a successful create.

## C6 — Observability and security

**Logs (structured, JSON, per event):** tenant id (hashed or short-uuid),
connection id, job id, invoice internal id + Xero InvoiceID, HTTP status,
Retry-After value, cursor position, sync lag (`now - last_modified_synced`),
attempt number, error class. Correlation: propagate a `trace_id` from the
scheduler through worker → HTTP client → internal DB events; include
`X-Request-Id` (our per-call UUID) so Xero support can match server logs.

**Metrics:** request counter by status/endpoint/tenant; p50/p95 latency;
429 count and time-spent-parked; daily-budget consumption per tenant;
sync lag gauge; dead-letter depth; tokens-refresh failures; reconcile
"found-after-timeout" counter (the key integrity metric).

**Alerts:** sustained sync lag > threshold; 401-after-refresh rate (mass
revocation); daily budget >90% early in the day; dead-letter non-empty;
clock-skew heuristic (modified-since in the future); error-rate spike per
tenant vs fleet baseline.

**Never log:** access/refresh tokens, client secrets, full `Authorization`
headers, cookie/session values, PII beyond business ids the sync already owns
(customer emails), or full request bodies containing bank/account details.
Redact at the HTTP-client layer so it's impossible to leak by accident.

**Secrets:** tokens encrypted at rest (KMS envelope encryption), stored per
connection row, never in code or env files; short-lived access tokens held only
in worker memory, refresh tokens only in the encrypted store. Rotate client
secrets via app re-registration with overlap window; rotate KMS keys on schedule;
auto re-auth flow when a refresh token dies. Least-privilege scopes (read-only
where possible). Git hygiene: pre-commit secret scanning, no credentials in the
repo (this assessment's own rule).

---

## References (official Xero developer documentation)

- OAuth 2.0 overview: https://developer.xero.com/documentation/guides/oauth2/overview/
- Authorisation code flow (tokens, 30-min expiry, headers): https://developer.xero.com/documentation/guides/oauth2/auth-flow/
- Tenants & `GET /connections`: https://developer.xero.com/documentation/guides/oauth2/tenants
- Managing tokens and ids (best practice): https://developer.xero.com/documentation/best-practices/data-integrity/managing-tokens
- API limits (minute/daily, `Retry-After`): https://developer.xero.com/documentation/guides/oauth2/limits/ and https://developer.xero.com/documentation/best-practices/api-call-efficiencies/rate-limits
- Accounting API response codes (401/403/404/429 semantics): https://developer.xero.com/documentation/api/accounting/responsecodes
- Requests & responses incl. `If-Modified-Since`/pagination: https://developer.xero.com/documentation/api/accounting/requests-and-responses
- FAQ (rate limit behaviour): https://developer.xero.com/faq
