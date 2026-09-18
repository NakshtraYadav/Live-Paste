# LivePaste — Security Audit & Deep Analysis

**Assessment date:** 2026-09-18
**Auditor:** Buffy (automated deep review + live black-box probing)
**Baseline:** builds on the source audit in [`AUDIT.md`](./AUDIT.md) (2026-09-16, v3.16.14)
**Scope:** Full backend (`livepaste/core.py`, `storage.py`), frontend rendering paths, WebSocket flows, file handling, plus **live empirical probes** against a running server on `127.0.0.1:8090` — something the prior source-only audit did not do.
**Current version under review:** 3.16.14 + uncommitted working-tree changes (5 QA/security fixes applied this session).

---

## 1. Executive summary

LivePaste's security posture is **strong for its threat model** (anonymous, token-based collaborative pastebin; trusted LAN / self-hosting default). The two architectural risks the 2026-09-16 audit flagged as release blockers have been **remediated in code and verified empirically in this pass**:

1. **Editor-grant impersonation (H1)** — raw `clientId` is no longer accepted as REST authorization. The server derives an HMAC-SHA256 capability from the paste's secret owner token; impersonation now fails with `403` (probe-verified).
2. **Secrets in URLs (H2)** — new edit links use `#edit=` fragments; view passwords travel in `X-View-Password` headers and the `lp-auth` WebSocket subprotocol. Legacy query-param transports still exist for old clients (documented compat trade-off, see finding O-1).

**Overall rating: LOW-MEDIUM risk for trusted LAN/self-hosting; MEDIUM for public multi-user hosting** (primarily due to the legacy transport window and shared-rate-limit guidance, not new vulnerabilities).

No critical or high findings are open. One **Medium (new)**, two **Low (new)**, and several previously-tracked items remain — all listed with evidence and concrete remediation below.

---

## 2. What was verified in code (deep analysis)

### 2.1 Authentication & authorization

| Control | Location | Verdict |
|---|---|---|
| Edit token generation: `secrets.token_urlsafe(24)` (192-bit) | `core.py:new_edit_token` | ✅ Strong |
| Token comparison: `secrets.compare_digest` (timing-safe) | `core.py:can_user_edit`, `verify_edit_token` | ✅ |
| Editor capability: `HMAC-SHA256(paste_token, client_id)`, base64url | `core.py:editor_capability` | ✅ Non-forgeable without owner token |
| Raw clientId alone → `403` | `can_user_edit` + probe | ✅ Verified live |
| File upload/delete/fork all route through `require_user_edit` | `core.py:1162-1247` | ✅ Canonical + legacy image alias |
| Paste reads never return `editToken`/`passwordHash`/`burnedBy`/`editors` | `_redact_paste` + probe | ✅ Verified live |
| Token returned exactly once, at creation | `create_paste` | ✅ |

### 2.2 Password protection

| Control | Verdict | Evidence |
|---|---|---|
| New hashes: bcrypt when available; else PBKDF2-HMAC-SHA256, 600k iterations, 16-byte salt | ✅ | `hash_password` |
| Legacy unsalted SHA-256 accepted **read-only** for migration | ✅ documented trade-off | `check_password` |
| Timing-safe comparison everywhere | ✅ | `secrets.compare_digest` |
| Brute-force lockout: 8 failures / 5 min, applied on REST **and** WS | ✅ live probe: `codes=[200×8, 429, 429]` | Section 3 |
| Correct password resets counter | ✅ code path | `_pw_clear` |

### 2.3 WebSocket security

| Control | Verdict |
|---|---|
| Origin validation on paste WS + signaling WS (`websocket_origin_allowed`) | ✅ Wildcard-CORS mode still constrains to request Host origins |
| Missing-Origin native clients allowed (documented) | ✅ acceptable |
| WS auth via `lp-auth.` subprotocol carrying token/password/clientId/capability | ✅ v3.16.10 |
| **Legacy fallback: `?token=`, `?pw=`, `?capability=` query params still accepted** | ⚠️ O-1 (see findings) |
| Password gate before room join; brute-force guard shared with REST | ✅ |
| Burn-after-read: room join counts as view; Nth reader gets content, paste destroyed behind them | ✅ probe-verified (200 then 404) |
| Per-IP WS admission budget + per-paste 256-viewer cap | ✅ `ws_admission_local` / `MAX_VIEWERS_PER_PASTE` |
| Redis-backed shared admission when `REDIS_URL` set | ✅ v3.16.13 |

### 2.4 File handling

| Control | Verdict | Evidence |
|---|---|---|
| Filename sanitization: strips path components, control chars, leading dots | ✅ `sanitize_filename` | |
| 100 MB/file, 500 MB/paste quota, 60 uploads/hour/IP | ✅ limits enforced in `_upload_file` | |
| **Stored-XSS via uploaded HTML/SVG: forced `Content-Disposition: attachment`** | ✅ **empirically confirmed** — uploaded `evil.svg` served with `attachment; filename="evil.svg"` + `nosniff` | Section 4.4 |
| `X-Content-Type-Options: nosniff` on file responses | ✅ probe-verified | |
| File reads are bearer-by-ID (no paste authz on read) | ⚠️ known design trade-off — IDs are 24-char unguessable; audit M8 recommends dedicated asset origin | |

### 2.5 Frontend rendering (XSS)

| Surface | Verdict |
|---|---|
| Markdown preview: `marked` → **DOMPurify** with `FORBID_TAGS: [style, form, input, iframe]`, `FORBID_ATTR: [style]` | ✅ Strict config |
| Only one `dangerouslySetInnerHTML` in the entire frontend (`MarkdownView`), always sanitized | ✅ grep-verified |
| HTML preview iframe: `sandbox="allow-scripts allow-modals"` **without** `allow-same-origin` → opaque origin, cannot touch app storage/DOM | ✅ Best practice |
| Paste content stored/rendered as JSON data, never as server-rendered HTML | ✅ probe-verified (`content-type: application/json`) |
| Edit tokens in `localStorage` | ⚠️ accepted trade-off (XSS would reach them; CSP + sanitizer are the compensating controls) |

### 2.6 Transport & headers (probe-verified)

```
content-security-policy: default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:;
  style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com;
  script-src 'self' https://cdn.jsdelivr.net;
  worker-src 'self' blob:; connect-src 'self' wss: ws: https://cdn.jsdelivr.net https://api.github.com;
  frame-ancestors 'self'
x-content-type-options: nosniff
x-frame-options: SAMEORIGIN
referrer-policy: strict-origin-when-cross-origin
permissions-policy: camera=(), geolocation=(), payment=(), usb=()
x-permitted-cross-domain-policies: none
strict-transport-security: (set when served over HTTPS)
```

CORS: wildcard by default but **non-credentialed**; explicit origin allowlists may opt into credentials. No cookies exist today, so no credentialed-CSRF path.

### 2.7 Data layer

- SQLite: all reviewed statements parameterized; WAL mode; no string-interpolated SQL found (grep-verified).
- Mongo mode: viewer/burn/quota multi-operation races remain open (audit M10) — unchanged.
- No hardcoded secrets in source (grep scan across `frontend/src`, `livepaste/*.py`: clean).

---

## 3. Empirical probe results (live server, black-box)

32 automated probes were executed against the running server. **31 passed.** The single "failure" was a probe artifact (hand-built multipart body rejected as malformed *before* reaching the auth layer); re-verified with well-formed requests below.

| # | Attack simulated | Expected | Observed | Verdict |
|---|---|---|---|---|
| 1 | `/api/file/..%2f..%2f..%2fetc%2fpasswd` | reject | 404 | ✅ |
| 2 | `/api/file/../../../../etc/passwd` | reject | 404 | ✅ |
| 3 | `/api/paste/..%2f..%2fetc%2fpasswd` | reject | 404 | ✅ |
| 4 | `/assets/..%2f..%2f..%2fpyproject.toml` | reject | 404 | ✅ |
| 5-6 | SPA-fallback traversal (`/..%2f..%2fpyproject.toml`) | no file leak | 200 but SPA HTML, no leak | ✅ |
| 7 | Read paste → secrets in JSON | redacted | `leaked=[]` | ✅ |
| 8-10 | Security headers (`nosniff`, `SAMEORIGIN`, referrer-policy) | present | present | ✅ |
| 11 | CSP `frame-ancestors 'self'` | present | present | ✅ |
| 12 | Locked paste read without password | 401 | 401 | ✅ |
| 13 | Locked paste, wrong password | 401 | 401 | ✅ |
| 14 | Correct password via `X-View-Password` header | 200 | 200 | ✅ |
| 15 | Authenticated read redacts token | redacted | redacted | ✅ |
| 16 | Password brute-force ×10 | lockout | 429 from 9th attempt | ✅ |
| 17 | **File upload without edit token** | 403 | **403** | ✅ |
| 18 | **File upload with wrong token** | 403 | **403** | ✅ |
| 19 | **File upload with raw clientId, no capability** | 403 | **403** | ✅ |
| 20 | File upload with correct token | 200 | 200 | ✅ |
| 21 | Restore content with wrong token | 403 | 403 | ✅ |
| 22 | Token verify: wrong / right | false / true | as expected | ✅ |
| 23 | Stored XSS payload read back | JSON data only | `application/json` | ✅ |
| 24 | **Uploaded SVG served** | attachment | **`attachment; filename="evil.svg"`** + nosniff | ✅ |
| 25 | Burn-after-read: reader 1 / reader 2 | 200 / 404 | 200 / 404 | ✅ |
| 26 | Reserved slug `api` | 400 | 400 | ✅ |
| 27 | Duplicate slug | 409 | 409 | ✅ |
| 28 | Invalid slug chars | 400 | 400 | ✅ |
| 29 | 500 KB content | 413 | 413 | ✅ |
| 30 | Invalid expiry | 400 | 400 | ✅ |
| 31 | Unknown slug | generic 404 | generic 404 | ✅ |
| 32 | Paste-creation rate limit | 429 | 429 after ~30/hour | ✅ |

**Probe verdict: no exploitable authorization, traversal, injection, or XSS hole found from the outside.**

---

## 4. Findings (current)

### O-1 · Medium — Legacy credential transports still enabled (compat window)
**Where:** `core.py:1431` — WS auth falls back to `?token=`, `?pw=`, `?capability=` query params; REST still accepts `?pw=` for locked reads.
**Why it matters:** URLs leak into proxy/access logs, browser history, and telemetry. A token in a query string defeats the fragment-based fix for any client still using the legacy form. This is the audit's known "remaining work" from H2.
**Risk:** Confidentiality of edit tokens / view passwords in hosted deployments with logging infrastructure.
**Remediation:** announce a deprecation window, then remove the query-param fallbacks; emit a warning log when a legacy transport is used to measure remaining clients; scrub proxy logs as interim.

### O-2 · Low — File read is bearer-by-ID
`GET /api/file/{id}` requires no paste authorization (design trade-off, documented in AUDIT.md M8). IDs are 24-char random (unguessable), responses are `nosniff`, and HTML/SVG forces download. Risk materializes only if an ID leaks (e.g., referrer, shared URL) — mitigated by the immutable, cache-friendly headers. **Recommendation:** keep, but add an optional `LIVEPASTE_STRICT_FILES=1` mode requiring paste-level auth on file reads, and move to a cookieless asset origin for public hosting.

### O-3 · Low — Frontend test suite is minimal (now 4 tests)
The paste-page crash found in QA this session (blank page for every paste) would have been caught by a render test. Regression tests now exist for it (`PastePage.test.jsx`), but auth-flow and sanitizer tests should follow. **Recommendation:** add DOMPurify-sanitizer tests (javascript: URLs, event handlers, SVG) and a WS-auth subprotocol unit test to CI.

### Carried-forward items (from AUDIT.md, still open, unchanged)
- **M4** — update pipeline trusts unsigned release metadata (sign releases, fail closed).
- **M5** — CI actions not SHA-pinned; no SBOM/provenance yet.
- **M6/M7** — code-runner and CDN trust boundaries (documented trade-offs).
- **M10** — Mongo viewer/burn atomicity for multi-instance deployments.
- **L1/L2/L3/L5** — log redaction, data-dir permissions, availability budgets, dependency locking.

### Fixed during this session (context)
- 🔴 Blank paste page (regex-escape SyntaxError in `encodeWebSocketAuth` — every paste was unrenderable) — fixed + regression tests.
- 🟠 CSP blocked the update-banner fetch to `api.github.com` — fixed (`connect-src` now includes it; verified).
- 🟠 Stale served bundle — fixed (`yarn sync` one-step build+deploy).
- 🟡 API rejected `null` optional fields — fixed via Pydantic `field_validator` + tests.

---

## 5. Prioritized recommendations

**P0 — before any public hosting**
1. Remove legacy query-param credential transports (O-1) after a deprecation window.
2. Terminate TLS, set an exact `CORS_ORIGINS` allowlist, set `REDIS_URL` for shared rate-limit/admission state.
3. Scrub request-URL logging at the proxy as interim mitigation for any remaining `?pw=`/`?token=` usage.

**P1 — production readiness**
4. Sign release artifacts and make update verification fail-closed (M4).
5. Pin CI actions by SHA; add SBOM/provenance; add sanitizer + WS-auth tests to CI (O-3, M5).
6. Optional strict file-read mode (O-2) and dedicated asset origin.

**P2 — hardening**
7. Mongo atomic operations for viewer/burn/quota (M10).
8. Log redaction, data-dir `0700`, disk-quota monitoring (L1/L2/L3).
9. Independent external penetration test after P0 changes.

---

## 6. Methodology & limitations

**Method:** source review of all auth/authz/render/file/transport code paths; live black-box probing (32 automated attacks + manual curl/browser verification with gstack's browse engine); secret-scan; SQL-parameterization scan; regression-suite runs (backend 56/56, frontend 4/4).

**Limitations:** no external pentest, no browser-matrix testing, Mongo/Redis modes not exercised live, no dependency CVE audit run in this pass (CI's `pip-audit`/`npm audit` cover this on push), and the server was probed only on loopback. A green probe set proves the tested paths hold — it does not prove absence of all vulnerabilities.

---

*Report file: `SECURITY_AUDIT_REPORT.md`. Probe script preserved at `/tmp/security_probe.py` — consider committing it under `scripts/security_probe.py` so the probes can run in CI.*
