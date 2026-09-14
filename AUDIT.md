# LivePaste — Professional Security & Quality Audit

**Date:** 2026-09-14 · **Scope:** full stack (CLI, backend, WebSocket layer, frontend, data flow, CI/CD) · **Result:** 1 critical data-breach fix, 3 high-severity fixes, multiple correctness/robustness fixes — all shipped in **v3.5.1**.

---

## CRITICAL — fixed in v3.5.1

### C1. Password lock bypass → content disclosure (data breach)
**Where:** `livepaste/core.py` — `GET /api/paste/{slug}/sheets/{id}` and `GET /api/paste/{slug}/revisions/{rev}`.

**Impact:** A locked paste (v2.8.0 password lock) returned `401` on `GET /paste/{slug}` — but `GET /paste/{slug}/sheets/main` returned the **full plaintext content** with no password, and revision snapshots were equally open. The lock screen was pure theater: anyone with the URL had three unauthenticated read paths. Worst case: a private paste's contents disclosed to whoever obtains/guesses the link (e.g. via Referer leakage — now mitigated, see below).

**Fix:** Both endpoints now enforce the same `check_password` gate as the main read path (401 before 404, so probing can't distinguish existing from missing revisions). The frontend sends the session password on those fetches. Regression test `test_locked_paste_cannot_leak_via_sheets_or_revisions` added (32 tests total).

---

## HIGH — fixed in v3.5.1

### H1. `X-Forwarded-For` spoofing defeats rate limiting & brute-force lockout
**Where:** `client_ip()` / `ws_client_ip()` in `livepaste/core.py`.

**Impact:** Every client could set `X-Forwarded-For: <random>` and get a fresh bucket: the 30/hour paste-creation limit, the 60/hour upload limit, and the **8-attempt password brute-force lockout** were all unenforced for a hostile client. Combined with C1's pre-fix state this was a full lock bypass; post-C1 it still made lockout toothless.

**Fix:** The header is only honored when `LIVEPASTE_TRUST_PROXY=1` is set (i.e. you actually run behind a reverse proxy that *overwrites* the header). Default deployments now rate-limit on the real socket address. Documented in the env-var reference.

### H2. Stale bytecode cache served dead code to production (`restart` shipped an old version)
**Where:** macOS framework Python (`/Library/Developer/CommandLineTools`) + `~/Library/Caches/com.apple.python/` (bytecode cache keyed by absolute source path).

**Impact:** After a `livepaste restart`, the server reported **v2.1.1 while the repo contained v3.4.0**. Root cause proven with `PYTHONVERBOSE=1`: Python loaded the repo's `__init__.py`/`core.py` paths but *executed code objects from the system bytecode cache*; cache invalidation by source mtime had been defeated (files were synced preserving mtimes). This also explains "why doesn't my fix show up" symptoms during this session. Two related landmines removed: a stale `build/lib/livepaste/` tree in the repo (pip could have installed it) and a `livepaste/static` holding an older bundle than `frontend/build`.

**Fix:** Purged the poisoned cache and `build/` artifacts; `livepaste restart` now launches uvicorn with `cwd` + `PYTHONPATH` pinned to the running checkout (deterministic import), instead of `python -m livepaste` whose resolution differs per launcher. Run doc updated: never `cp -R` with preserved mtimes into a watched tree; canonical bundle flow is `frontend/build` → `livepaste/static`.

### H3. Revision-history destruction via the full-text backup channel
**Where:** `PastePage.jsx` `sendEdit` → WS `edit` → `append_revision` (cap: 50).

**Impact:** Every debounced keystroke sent a full-text `edit`; the server snapshotted *each* into `revisions`. A normal burst of typing (200 words ≈ 50 syncs) filled the entire 50-slot history with near-identical snapshots and **evicted every real revision** within minutes of editing — the History panel's undo value was effectively zero, and it also amplified DB writes ~25×.

**Fix:** Full-text backup throttled client-side to at most one per 5 s (CRDT deltas — the real sync channel — still flow per keystroke, so collaboration is unaffected). Server-side `append_revision` also skips identical consecutive content, so the throttle and CRDT-first flow can't regress history.

---

## MEDIUM — fixed or mitigated in v3.5.1

### M1. No security headers
`X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, and a baseline `Content-Security-Policy` are now set on every response via middleware. `frame-ancestors 'self'` prevents clickjacking of the editor and the unlock screen; `Referrer-Policy: strict-origin-when-cross-origin` stops paste URLs from leaking out via `Referer` when users click external links; CSP allows only same-origin assets plus the Pyodide CDN used by v2.3.0 runnable pastes.

### M2. Message-ordering hazard in the WS handler
`ws.onmessage` had been made `async` for the offline-copy lookup (v3.4.0). Any `await` in that handler can delay subsequent messages — presence, CRDT deltas, and error paths could then apply out of order. Reverted to a synchronous handler with a fire-and-forget `.then()` for the lookup.

### M3. PID-reuse kill hazard in `livepaste restart`
The restart command read a pid from `~/.livepaste/livepaste.pid` and `SIGTERM`'d it. If the pid file is stale, the OS may have *recycled* that pid for an unrelated process (someone's editor, a system daemon) — the old code would have killed it. Now verifies via `ps` that the target command is actually LivePaste/uvicorn before signaling.

### M4. `PORT` config overrode an explicit `--port`
`livepaste restart --port 8123` computed its port as `config.PORT or args.port`, so the user's config (`PORT=65535`) silently hijacked an explicit flag. Explicit CLI args now win; additionally, the restart flow could kill the server on the *old* port and relaunch on the wrong one — same fix.

### M5. Version summary leakage of the editors allowlist
The WS `init` message includes the editors allowlist to all room members (needed to render grant badges). It is server-authoritative data (not a secret like `editToken`), but revocation of a granted user now also broadcasts so any stale viewer list self-corrects. (Behavior verified by tests; noted here for transparency.)

---

## LOW / hygiene — noted, fixed where trivial

| # | Finding | Status |
|---|---|---|
| L1 | `~/.livepaste/config` had `PORT=65535` from an early installer run — documented config precedence (`--port` > config > 8090 default) | documented |
| L2 | `livepaste/static` can drift from `frontend/build` (root cause of the "stale bundle" preview confusion). Run doc now makes the copy step explicit after every build | documented |
| L3 | CSP allows `https://cdn.jsdelivr.net` (Pyodide) — a supply-chain trust point. Pinning + SRI is recommended follow-up | follow-up |
| L4 | Uploads still buffer to disk per-chunk (good), but no per-paste total-size quota — a single paste can accumulate 100 MB files repeatedly | follow-up |
| L5 | `list_revisions` response leaks only sizes — fine; the *content* endpoint is now gated (C1) | resolved |
| L6 | SQLite `WAL` + per-call `_lock` is correct; no SQL-injection surface found (parameterized throughout) | clean |
| L7 | `sanitize_filename` strips path components & control chars; downloads force `attachment` for HTML/SVG (no stored-XSS via file origin); `nosniff` present | clean |
| L8 | Pyodide runner executes in a Worker with no DOM/network access — sound sandbox for JS; Python sandbox inherits Pyodide's WASM isolation | clean |
| L9 | CORS: `allow_origins=["*"]` + `allow_credentials=True` is an invalid per-spec combination — browsers reject credentialed requests when origin is `*`. Harmless here (no cookies), but tightened by leaving origins `*` only when credentials aren't requested | noted |
| L10 | GitHub Actions `release.yml` runs on `v*` tags with `contents: write` — least privilege OK; CI workflow (3.2.0) runs tests on push/PR | clean |

---

## Data-flow verification (traced end-to-end)

1. **Create** → `POST /paste` (rate-limit → slug validation → token gen) → SQLite row → REST returns token **once** → frontend stores `lp_edit_<slug>`.
2. **View** → `GET /paste/{slug}` or WS `init` → redaction filter strips `editToken/passwordHash/burnedBy/editors`.
3. **Edit (CRDT)** → client Y.Text delta → `yupdate`/`s:yupdate` (sheet id stamped at queue time, v3.4.0) → append to `ystate`/`ystate_sheets` (compacts at 4096) → broadcast → peers merge idempotently.
4. **Edit (backup)** → throttled (v3.5.1) full-text `edit`/`s:edit` → `append_revision` + content update + `clear_ystate` → broadcast.
5. **Upload** → token/clientId auth (v3.3.0) → rate-limit → chunked stream to disk/GridFS → `files-changed` broadcast.
6. **Burn-after-read** → `register_view` counts distinct clientIds → at N, purge files + delete paste → triggering reader still served, later joiners get `not_found`.
7. **Lock** → `passwordHash` (bcrypt; sha256 fallback) never leaves the server → gate enforced on REST, WS, sheets, revisions (v3.5.1).
8. **Rollback/update** → SHA256 verify → `.old` backup → atomic rename → history ledger + pending-restart marker → `livepaste restart` (v3.5.1: pinned imports, pid-verified kill).

## Env-var reference (new)

| Variable | Meaning |
|---|---|
| `LIVEPASTE_TRUST_PROXY=1` | Honor `X-Forwarded-For` (only when behind an overwriting reverse proxy) |
| `LIVEPASTE_DATA_DIR` | Where SQLite + files live (tests/local: e.g. `/tmp/lp-live`) |
| `LIVEPASTE_EPHEMERAL=1` | Wipe data on startup/shutdown (default in local mode) |
| `LIVEPASTE_SERVE_STATIC=0` | Don't serve the bundled frontend (dev/frontend-on-own-port) |
| `CORS_ORIGINS` | Comma-separated allowlist (default `*`) |

## Verification

- `pytest tests/` → **32/32 in <1 s** (includes the new lock-bypass regression)
- Frontend `yarn build` clean; canonical bundle copied to `livepaste/static`
- Live preview verified: home page, paste creation, edit round-trip, viewer counts, restart-on-fixed-code reporting `3.5.1`
