# LivePaste — Full-Scale Security Audit

**Assessment date:** 2026-09-16
**Repository:** `NakshtraYadav/Live-Paste`
**Reviewed version:** `3.16.4`
**Scope:** FastAPI/SQLite/MongoDB backend, WebSockets and WebRTC signaling, file handling, frontend rendering and browser storage, CLI/update/rollback, packaging, CI/CD, and existing regression tests.

## Executive summary

LivePaste has a solid security baseline for an anonymous collaborative paste application: edit tokens are high-entropy, password checks cover the main read paths, SQL is parameterized, uploads are streamed and size-limited, stored HTML/SVG downloads are forced to attachments when correctly typed, and the project has meaningful authorization and WebSocket regression tests.

This review also found two important architectural risks that should be treated as release blockers for an internet-facing deployment:

1. **Per-user editor grants are not proof of identity for REST requests.** `clientId` is a browser-generated, client-controlled identifier. A user who learns a granted client's ID can impersonate that client to upload or delete files through REST. This is not safely fixable by another string check; the grant must become a signed, short-lived capability or be replaced with a server-authenticated session.
2. **Secrets are placed in URLs.** Edit tokens and view passwords travel in WebSocket query strings and password-protected REST query strings. URLs can enter reverse-proxy logs, access logs, browser history, monitoring, and referrer-adjacent telemetry. This is a confidentiality risk even though the application does not use cookies.

A legacy image-delete authorization bypass was confirmed and fixed in this pass. New password hashes now use bcrypt when available or salted scrypt otherwise; legacy unsalted SHA-256 hashes remain readable only for migration compatibility. Static-file containment and security headers were also hardened.

**Overall rating:** **Medium risk for trusted LAN/self-hosting; High risk for public multi-user hosting until the REST editor-grant and URL-secret designs are replaced.** This document is a source review and regression assessment, not a certificate, external penetration test, cloud configuration review, or guarantee that undiscovered vulnerabilities do not exist.

---

## Severity definitions

- **Critical:** likely remote compromise, broad data breach, or destructive unauthorized access with minimal prerequisites.
- **High:** practical unauthorized read/write, account/tenant boundary failure, secret disclosure, or significant denial of service.
- **Medium:** meaningful hardening gap or exploit requiring additional conditions; should be fixed before broad public exposure.
- **Low:** defense-in-depth, operational, usability, or maintainability concern.
- **Informational:** design trade-off or item requiring explicit deployment documentation.

---

## Findings and status

### H1 — Client-controlled `clientId` is used as a REST edit capability

**Status:** Open — architectural redesign required
**Affected areas:** `POST /api/paste/{slug}/file`, `DELETE /api/file/{id}`, legacy image upload/delete aliases, `can_user_edit`, browser presence identity.

The per-user grant feature stores a browser-provided `clientId` in the paste's editor allowlist. REST requests accept `clientId` directly from a form/query parameter and treat a matching value as edit authorization. `clientId` is not a secret, is not bound to a cryptographic key, and is visible through presence messages. Anyone who learns a granted ID can claim it from another browser and upload or delete files.

**Impact:** unauthorized attachment upload/deletion by a viewer who can observe or guess a granted client ID; possible quota exhaustion, content tampering, and destructive modification of a paste. The same conceptual risk applies to any future REST operation that accepts `clientId` as proof.

**Why the obvious fix is insufficient:** checking length, format, or `compare_digest` does not make a public browser identifier an authenticator.

**Required remediation:** choose one of these designs before public deployment:

1. **Signed capability (recommended for the current anonymous model):** the owner grants a client public key, not an ID. The client proves possession by signing a nonce/request; the server stores the public key and verifies signatures. For simpler implementation, issue a random short-lived capability token over the authenticated WebSocket and require it for REST writes.
2. **Authenticated session:** add accounts or passkey-based sessions and bind grants to a server identity. Use an HttpOnly, Secure, SameSite cookie plus CSRF protection for REST writes.
3. **Conservative interim policy:** remove `clientId` authorization from REST and require the edit token for uploads/deletes. This preserves security but temporarily removes granted-editor file management.

Do not describe a raw `clientId` as an authorization credential in future documentation.

### H2 — Edit tokens and view passwords appear in URLs

**Status:** Open — design change recommended before sensitive public use
**Affected areas:** `/api/ws/{slug}?token=...`, `/api/ws/{slug}?pw=...`, `?pw=...` sheet/revision reads, edit links containing `?edit=...`.

Query parameters are commonly logged by reverse proxies, load balancers, APM agents, browser history, copied URLs, and support tooling. WebSocket upgrade URLs are especially likely to be logged. A leaked edit token grants write access; a leaked password grants access to a locked paste.

**Mitigations already present:** strict referrer policy, redaction from API payloads, session-only password storage in the browser, and no cookie-based authentication.

**Required remediation:** move secrets to headers or a short-lived exchange:

- Exchange the edit link once for a short-lived, scoped session/capability, then use an `Authorization` header or WebSocket subprotocol.
- Submit view passwords via POST, issue a short-lived HttpOnly session cookie, and stop using `pw` query parameters for sheet/revision/WebSocket reads.
- Scrub query strings in reverse-proxy logs immediately as an interim measure.
- Rotate edit tokens after any suspected URL/log exposure.

### H1-fixed — Legacy image delete bypassed authorization

**Status:** Fixed in this assessment; regression test added
**Affected area:** `DELETE /api/image/{image_id}`.

The canonical `/api/file/{id}` route checked the owning paste's edit rights, but the legacy image alias directly deleted the file. Any party who knew an image ID could delete it, including on token-protected pastes.

**Fix:** the legacy alias now performs the same metadata lookup and `require_user_edit` check as the canonical route. Test: `test_legacy_image_delete_requires_edit_rights`.

### H2-fixed — Weak password fallback for new passwords

**Status:** Fixed in this assessment; legacy migration still required
**Affected area:** `hash_password`.

The environment does not include bcrypt by default, so the previous implementation created unsalted SHA-256 hashes. SHA-256 is not a password KDF and is vulnerable to offline dictionary/rainbow-table attacks if the database is exposed.

**Fix:** bcrypt remains preferred; minimal installations now use salted, high-iteration PBKDF2-HMAC-SHA256. Existing `sha256$...` hashes remain readable for compatibility but are never generated for new passwords.

**Next step:** on successful authentication of a legacy SHA-256 password, transparently rehash it with PBKDF2/bcrypt and persist the new hash. Add a migration report for remaining legacy hashes.

### H3 — WebRTC signaling allows unbounded topic and message growth

**Status:** Open — denial-of-service hardening
**Affected area:** `/api/webrtc/signaling`.

The relay caps total connections but allows each socket to subscribe to an unbounded number of `lp:` topics and publishes arbitrary nested dictionaries without a byte limit or per-socket rate limit. A client can create many topic sets and large messages, increasing memory, CPU, and fan-out cost.

**Remediation:** enforce a maximum topics-per-socket limit, strict topic grammar tied to a validated slug/sheet ID, maximum frame size and JSON depth/serialized bytes, maximum recipients/fan-out, idle timeouts, and per-IP connection/message rate limits. Remove dead sockets under a lock and use a bounded relay queue.

### H4 — Password brute-force state and rate limits are process-local

**Status:** Open — deployment scalability and abuse resistance
**Affected area:** `RateLimiter`, `pw_failures`, WebSocket admission.

The in-memory limiters work in one process and are covered by tests, but multiple workers/containers have independent counters. Attackers can multiply attempts by distributing requests across workers or IPs. Memory cleanup is opportunistic rather than a hard bounded store.

**Remediation:** use Redis or another shared, bounded store for rate limits, lockouts, and WebSocket admission. Apply limits by IP, paste, and optionally a privacy-preserving paste identifier. Add trusted-proxy parsing that validates proxy topology rather than trusting an environment switch alone.

### M1 — CORS defaults are broad

**Status:** Partially fixed/mitigated

The default remains `CORS_ORIGINS=*` for self-hosting compatibility. It is now non-credentialed when wildcard is used; explicit origins may opt into credentials. There are no cookies today, so this is not currently a credentialed CSRF bypass.

**Production requirement:** set an exact origin allowlist, do not use `*`, and keep credentials disabled unless a reviewed session design requires them. Add automated deployment checks that reject wildcard CORS in hosted mode.

### M2 — WebSocket Origin is not validated

**Status:** Open — defense in depth

WebSockets do not automatically receive browser CORS protection. The application currently relies on token/password knowledge rather than an Origin policy. Since edit tokens are URL credentials, a leaked token remains usable from any origin.

**Remediation:** validate `Origin` against an explicit allowlist during WebSocket handshake. Decide and document behavior for native clients and LAN HTTP. Origin validation is not a replacement for proper authentication.

### M3 — Passwords in REST query parameters can be logged

**Status:** Open; included in H2 remediation

`GET /sheets/{id}?pw=...` and `GET /revisions/{rev}?pw=...` are convenient but expose passwords to infrastructure logs. Replace with a short-lived server-side unlock session or an authorization header.

### M4 — Update pipeline trusts unsigned release metadata and has a permissive fallback

**Status:** Open — supply-chain hardening
**Affected area:** `livepaste update`, release workflow.

SHA-256 verification is useful, but the checksum file is fetched from the same GitHub release channel as the binary. If the release account/workflow is compromised, both can be replaced. Older releases without `SHA256SUMS` are explicitly allowed to install without verification. Pip updates also install from a Git ref without a lock/hash.

**Remediation:** sign release manifests with a pinned public key (Sigstore/Cosign or equivalent), fail closed when signatures/checksums are absent, pin action SHAs, generate provenance/SBOMs, protect release branches/tags, and use trusted publishing with least privilege.

### M5 — CI/CD dependency and action trust is incomplete

**Status:** Open

CI runs the backend tests but does not enforce dependency auditing, secret scanning, SAST, frontend audit, SBOM generation, or pinned third-party action SHAs. The release workflow grants `contents: write` at workflow scope and uses mutable action tags.

**Remediation:** add `pip-audit`, `npm/yarn audit` policy, Bandit/Ruff or equivalent SAST, Semgrep rules for auth/file paths, Gitleaks, Trivy/Syft SBOM generation, artifact signing, and a protected release environment. Pin every action to a full commit SHA and scope write permissions to the release job only.

### M6 — Frontend code execution is isolated but not a security boundary for secrets

**Status:** Partially mitigated

JavaScript runs in a Worker, but the Worker still has `fetch`; Python loads Pyodide from a CDN and may access network-capable runtime functionality. This is appropriate for a user-requested local code runner, but it is not a hardened hostile-code sandbox and must never receive application tokens or private data.

**Remediation:** block or proxy network APIs in the JS worker, disable Python package/network access, enforce worker memory/output quotas, terminate workers on navigation, pin Pyodide with integrity/provenance, and document that code execution is not a server sandbox.

### M7 — External CDN and Google font trust points

**Status:** Open — supply-chain/privacy hardening

CSP permits `cdn.jsdelivr.net` for Pyodide and Google font domains. A CDN compromise, availability issue, or privacy-sensitive deployment may affect users.

**Remediation:** self-host and pin runtime assets where practical; otherwise use immutable versioned URLs, SRI where browser-supported, CSP nonces/hashes for local inline styles if feasible, and an explicit risk acceptance for the Python runtime.

### M8 — File and object delivery needs a separate-origin deployment option

**Status:** Medium / deployment-dependent

Files are served from the same origin and rely on content type, `nosniff`, forced attachment for HTML/XML/SVG, and CSP. This is a reasonable defense, but a future content-type regression or browser parser behavior could turn stored content into same-origin active content.

**Remediation:** serve uploads from a dedicated cookieless asset origin with `Content-Disposition: attachment` by default, immutable opaque IDs, strict type allowlisting for inline previews, and no application cookies on that origin. Keep HTML/SVG/PDF preview policy explicit.

### M9 — Static path containment was prefix-based

**Status:** Fixed in this assessment

The SPA fallback used string-prefix containment. Prefix checks can accept a sibling path whose name begins with the static directory name. The check now uses `os.path.commonpath` against the resolved static root.

### M10 — Concurrent view/burn updates need atomic cross-instance semantics

**Status:** Open

SQLite serializes through the process lock; Mongo updates read and write viewer/burn arrays in separate operations. Concurrent requests can lose viewer updates or produce inconsistent burn decisions.

**Remediation:** use atomic Mongo update operators/transactions, bounded hashed viewer IDs, and an idempotency key. Add concurrent integration tests against Mongo or a production-like replica set.

### L1 — Secrets and operational logs

**Status:** Follow-up

Server logs may contain request paths, WebSocket upgrade URLs, exception details, and user-controlled slug/name values. Use structured logging with redaction, bounded field lengths, log rotation, restrictive file permissions, and no content/password/token logging.

### L2 — Local data directory permissions

**Status:** Follow-up

SQLite and attachment files contain user data and edit capability metadata. Create the data directory with mode `0700`, database/files with restrictive permissions, and document backup encryption. Do not rely on the parent home directory alone.

### L3 — Availability controls

**Status:** Follow-up

There are limits for paste creation, uploads, file size, total paste attachment quota, Yjs updates, and signaling connection count. Add request-body limits at the reverse proxy, maximum concurrent uploads, maximum sheets/files per paste, output limits for runners, server timeouts, and disk quota monitoring.

### L4 — Error and identifier enumeration

**Status:** Mostly acceptable; review during redesign

Slug existence and custom-slug collisions are intentionally disclosed to support creation. Locked read paths return a password challenge. Keep edit-token verification responses generic and avoid revealing whether a token was close to valid.

### L5 — Dependency ranges

**Status:** Follow-up

Backend dependencies use lower bounds rather than a fully locked production environment. Keep the committed frontend lockfile, produce a backend lock/constraints file, and upgrade through automated dependency PRs with tests and audit gates.

---

## Component-by-component review

### Backend and authorization

- **Edit tokens:** generated with `secrets.token_urlsafe(24)` and compared with `secrets.compare_digest`; not returned by normal paste reads or WebSocket redacted payloads. Good entropy and redaction. Main issue is transport in URLs and the separate raw-client-ID grant model.
- **Legacy pastes:** intentionally remain editable without a token for compatibility. This is a documented security trade-off: old links cannot be assumed private or write-protected.
- **Password locks:** enforced on paste, sheets, revisions, and WebSocket paths; brute-force lockout exists. New KDF is now bcrypt/scrypt. Query transport and distributed lockout remain.
- **Input limits:** paste content and Yjs updates are bounded; sheet count/name and attachment file/quota limits exist. Add proxy-level limits and signaling limits.
- **SQL:** reviewed queries use parameter binding. No SQL injection finding was identified.
- **Mongo:** collection indexes exist, but multi-operation viewer/burn and upload quota races require atomic/transactional redesign.

### File handling

- Filename path components and control characters are stripped.
- Files are streamed and capped at 100 MB each and 500 MB per paste.
- HTML/XML/SVG content types are forced to download and `nosniff` is set.
- Canonical and legacy delete routes now require edit rights.
- File reads are intentionally bearer-by-ID and do not require paste authorization; treat IDs as unguessable but not as a substitute for access control. Dedicated asset origin is recommended.

### WebSockets and signaling

- Paste WebSocket authentication, password gate, live rights update, message size checks, and disconnect cleanup are tested.
- Message handlers accept user-provided presence names/colors/cursors; frontend rendering uses React text nodes, reducing DOM XSS risk. Keep server-side size/shape validation.
- Signaling has a connection cap but needs topic, frame, queue, and rate bounds.
- Validate `Origin` and use a shared admission/rate-limit service in hosted mode.

### Frontend

- Markdown is rendered through `marked` then DOMPurify with dangerous tags/attributes restricted. Maintain sanitizer tests for links, images, SVG, protocol URLs, and event attributes.
- HTML preview uses a sandboxed iframe without `allow-same-origin`; this is a good boundary for the preview, but do not add same-origin or forms/popups without review.
- Edit tokens are stored in `localStorage`, which is accessible to any same-origin XSS. The best long-term design is an HttpOnly capability/session; until then, CSP, sanitizer tests, and dependency integrity are critical.
- Offline IndexedDB mirrors paste content. Treat local browser storage as sensitive and document clearing/backup behavior.
- Browser code calls the GitHub releases API and a Pyodide CDN; these are privacy and supply-chain dependencies.

### CLI, packaging, and operations

- Restart checks process identity before signaling and uses direct interpreter import paths; this addresses the historical stale-bytecode issue.
- Autostart writes user-level launchd/systemd configuration. XML/argument escaping and environment/config validation should be hardened before accepting untrusted configuration sources.
- Update rollback preserves an old binary and supports checksum verification, but release signing and fail-closed verification are still needed.
- Hosted deployment must terminate TLS, set an exact CORS allowlist, redact query strings, restrict methods/body sizes, add WAF/rate controls, and isolate uploaded files.

### CI/CD

- Existing CI runs the offline backend suite.
- Release builds matrix binaries and publishes checksums.
- Missing controls: pinned action SHAs, SAST, dependency audit, secret scan, SBOM/provenance, signed releases, protected tags/environments, and separate write permissions.

---

## Tests and evidence executed

### Automated regression suite

```text
PYTHONPATH=. ./.venv/bin/pytest tests/ -q --tb=short
45 passed in 0.97s
```

The suite covers password lock read paths, WebSocket auth and disconnects, edit grants/revocation, unique views/burn behavior, uploads and quotas, filename flattening, file delete authorization, forks, sheets, CRDT relay, and revision behavior. This assessment added the legacy image-delete regression; password KDF and static containment should receive dedicated tests in the next test expansion.

### Review limitations

- No production host, reverse proxy, MongoDB cluster, DNS, TLS, cloud IAM, secrets, or GitHub branch settings were available.
- No external network penetration test or browser matrix was run.
- Dependency vulnerability status was not asserted because package audit tools/dependency installation were not executed in this pass.
- A green offline suite proves regression behavior, not complete security.

---

## Prioritized action plan

### Before public internet exposure — P0

1. Replace raw `clientId` REST authorization with signed capabilities or authenticated sessions; otherwise require the edit token for all REST writes.
2. Remove passwords/tokens from URLs; implement short-lived unlock/edit sessions and scrub existing proxy/application logs.
3. Put the app behind TLS, an exact CORS allowlist, WebSocket Origin validation, a reverse proxy body/time limit, and distributed rate limiting.
4. Add signaling topic/frame/rate/queue limits and a global connection budget.
5. Sign releases, pin CI actions, protect tags, and make update verification fail closed.

### Before calling the deployment production-ready — P1

6. Add scrypt/bcrypt legacy rehash-on-login and a migration report.
7. Use atomic Mongo viewer/burn/quota operations and run replica-set integration tests.
8. Move uploads to a dedicated cookieless origin and default unknown files to attachment download.
9. Add SAST, dependency audit, secret scanning, SBOM/provenance, and frontend sanitizer/security tests to CI.
10. Set data/log permissions, rotation, redaction, disk quotas, backup encryption, and incident-response procedures.

### Product and quality improvements — P2

11. Add user-visible token rotation/revocation and paste owner recovery controls.
12. Add an export/delete/privacy lifecycle policy and an admin abuse-report workflow for hosted mode.
13. Add observability for rate-limit hits, rejected auth, quota exhaustion, suspicious signaling, and release verification failures without logging secrets/content.
14. Publish a threat model and security.txt/contact process; create a responsible disclosure policy.
15. Run an independent penetration test after P0 changes, including WebSockets, Mongo mode, proxy behavior, upload content types, browser storage, and update/rollback paths.

## Recommended target architecture

For the best long-term security posture, keep the anonymous paste UX but separate trust domains:

- **Browser session:** short-lived HttpOnly/Secure/SameSite session or signed capability, never a long-lived token in a URL.
- **Authorization:** owner capability plus signed per-device editor capabilities; no raw browser-generated identifier is accepted as proof.
- **Data plane:** API and WebSocket service behind TLS and a proxy; Redis for shared rate limits/presence/admission; Mongo transactions or a single-writer storage service for counters.
- **File plane:** dedicated asset origin/bucket, opaque IDs, forced attachment by default, strict preview allowlist.
- **Execution plane:** optional local-only runner with network disabled and hard output/memory limits; never market it as a server sandbox.
- **Release plane:** reproducible builds, pinned actions, SBOM, signed artifacts/provenance, protected tags, and fail-closed client verification.
- **Assurance plane:** threat model, security regression suite, dependency/SAST gates, telemetry without secrets, and scheduled external testing.

This sequence preserves LivePaste's strongest product qualities—anonymous links and fast collaboration—while removing the two largest trust-model weaknesses instead of adding more checks around an unauthenticated identifier.
