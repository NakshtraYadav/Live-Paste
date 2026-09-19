# LivePaste Project Plan

**Planning baseline:** FEATURE_AUDIT_REPORT.md (updated for v3.18.0)  
**Goal:** turn the strong collaboration core into a reliably supported product without expanding scope until existing claims are honest and tested.

**Current state:** v3.18.0 closes the runner exception-path defects, rebinds CRDT listeners after socket replacement, registers the production service worker, and makes persistent CLI storage the safe default. The remaining phases below are browser-validation and advanced-feature hardening work.

## Strategy

1. Protect data and collaboration correctness first.
2. Establish browser-level confidence for every advertised workflow.
3. Harden advanced features or label them experimental.
4. Reduce operational and bundle risk.
5. Only then add larger product bets such as comments, token revocation, and embeds.

## Priority map

| Priority | Theme | Target outcome |
|---|---|---|
| P0 | Correctness | No feature throws while handling its own errors |
| P1 | Collaboration/recovery | Reconnect and offline behavior are observable and convergent |
| P1 | Feature integrity | PWA, P2P, recording, and runners either work end-to-end or are marked experimental |
| P2 | Product quality | Better revision semantics, UX feedback, coverage, and performance |
| P3 | Expansion | Token management, comments, embeds, integrations |

## Phase 0 — Release blockers — complete in v3.18.0

### 0.1 Fix runner error handling — complete

**Owner:** Frontend/runtime  
**Changes:** bind `catch (err)` in both worker sources; return structured error objects; add worker error and timeout cleanup; show a stable output state in the editor.

**Acceptance criteria:**

- JavaScript `throw new Error("boom")` displays `boom` and no uncaught worker exception.
- Python syntax/runtime errors display the actual Pyodide error.
- CDN failure, worker startup failure, and timeout all produce actionable UI.
- A failed run cannot leave the block stuck in `running`.
- Unit tests cover success, logs, error, and timeout paths.

### 0.2 Fix reconnect listener ownership — implementation complete; browser proof pending

**Owner:** Collaboration/runtime  
**Changes:** make the active WebSocket and connection generation explicit state; bind `useCollab` to that socket; remove listeners on every replacement; avoid competing `ws.onmessage` and `addEventListener` dispatch paths where possible.

**Acceptance criteria:**

- Two browser clients exchange edits before and after server restart.
- Client A receives client B's edit after reconnect without reload.
- A stale socket cannot mutate the current document.
- Reconnect backoff, offline hydration, and close cleanup are covered by tests.

### 0.3 Decide and implement PWA registration — implementation complete; browser proof pending

**Owner:** Frontend/platform  
**Changes:** register `/sw.js` only in production/served-static mode, handle updates and controller changes, version the cache from the app version, and document secure-origin requirements.

**Acceptance criteria:**

- A production browser registers the worker.
- Root and a paste route load from cache after an offline reload.
- API writes are never replayed by the worker.
- Old cache versions are removed.
- If registration is intentionally deferred, remove “installable/offline-first PWA” from supported claims instead.

## Phase 1 — Browser contract suite (3–5 days) — next gate

**Owner:** QA + frontend  
**Tooling:** existing Vitest/Testing Library plus the established browser harness; do not rely exclusively on mocked WebSockets.

Create a smoke matrix for:

- create paste with custom slug, language, expiry, burn count, and password;
- view-only vs edit-link behavior;
- concurrent editing and reconnect;
- password unlock and lockout;
- expiry and burn-after-read;
- file/image upload, drag/drop, clipboard, delete, and quota error;
- sheets create/rename/duplicate/reorder/delete;
- history list/diff/restore;
- markdown and sandboxed HTML preview;
- find/replace and command palette;
- fork;
- offline cold start/edit/reconnect;
- P2P on/off and signaling failure;
- voice/screen recording where supported;
- JS/Python runnable blocks.

**Acceptance criteria:** every row has a deterministic pass/fail test, browser support notes, and a screenshot/log artifact for failures. The test suite must fail on the reconnect bug and runner exception regressions.

## Phase 2 — Offline and collaboration reliability (3–5 days)

### 2.1 Define document authority

Document the relationship between REST text, Yjs updates, full-text backups, IndexedDB, and sheets. Make the server's merge result authoritative after reconnect and show a “synced at” indicator.

### 2.2 Add offline state UX

Show: offline, reconnecting, pending local edits, synced, and recovery-needed. Provide a user action to retry and a safe export of the local copy.

### 2.3 Expand offline persistence

Persist all sheets under stable IDs and make attachment references explicit. Do not promise binary attachment offline availability unless files are cached and quota-managed.

**Acceptance criteria:** offline edits survive reload, merge with a second editor, never silently disappear, and expose their final sync state.

## Phase 3 — Harden or constrain advanced features (1–2 weeks)

### 3.1 P2P WebRTC

- Add explicit “direct peer” vs “server relay” status.
- Handle signaling, ICE, permission, and NAT failures.
- Keep server CRDT as a safe fallback.
- Bound peer count, reconnect providers on sheet changes, and test topic cleanup.
- Add a feature flag and mark P2P experimental until the two-browser matrix is green.

### 3.2 Recording

- Build a browser/MIME compatibility matrix.
- Store actual MIME and duration metadata.
- Add playback previews and retryable uploads.
- Cap duration and report file size before upload.
- Handle user-ended display tracks and microphone failures separately.

### 3.3 Runnable code

- Keep execution strictly client-side and describe it as best-effort.
- Add hard CPU/time/output limits and terminate workers on all failure paths.
- Consider disabling network access in JavaScript or make the policy explicit.
- Lazy-load Pyodide with a visible progress indicator and a pinned local fallback for deployments that cannot reach the CDN.
- Add a “do not run untrusted code” warning for public pastes.

**Exit criterion:** each feature has either a green browser matrix and support statement or an “experimental” label and feature flag.

## Phase 4 — Product quality and operations (1 week) — partially complete

### 4.1 Revision semantics

Define checkpoint vs named snapshot, author, sheet scope, retention, and restore behavior. Add named snapshots and a clear restore confirmation.

### 4.2 Operational safety

- **Complete in v3.18.0:** persistent storage is the default; `--ephemeral` is explicit.
- Detect another process using the same data directory.
- Warn and confirm before purging non-empty data.
- Add backup/export/import and a documented SQLite/Mongo recovery path.

### 4.3 Frontend performance

Split history, preview, recorder, P2P, and runner code. Set a CI bundle budget below the current 968 KB main chunk, with a justified exception process.

### 4.4 Test hygiene

Remove React `act(...)` warnings, add a dedicated integration environment, and retain the 56-test backend baseline. Add CI artifact collection for browser console/network failures.

## Phase 5 — Next product bets (after reliability exit)

Recommended order:

1. **Token rotation/revocation UI** — revoke all edit capabilities without changing the view link.
2. **Named snapshots and comments** — build on existing revisions and presence.
3. **Read-only embed/oEmbed** — sandboxed, CSP-safe paste widgets.
4. **Export/import** — Markdown, JSON, zip attachments, and backup restore.
5. **Hosted deployment profile** — Redis-backed rate limits, object storage, metrics, and health dashboards.

## Definition of done for the project

- Every README feature is categorized as supported, experimental, or removed.
- P0/P1 findings in FEATURE_AUDIT_REPORT.md are closed or explicitly accepted.
- Browser tests cover core and advanced workflows on at least Chromium and one WebKit/Firefox target where APIs differ.
- Reconnect and offline edits converge without reload.
- Security audit has no critical/high findings and runner limitations are documented.
- Release CI runs backend, frontend, browser smoke, dependency audit, bandit, and bundle-budget checks.
- Operational defaults cannot silently delete a non-empty data directory.

## Suggested issue breakdown

- `fix(runner): preserve worker exception objects`
- `fix(collab): rebind CRDT message listener on socket replacement`
- `feat(pwa): register and update service worker`
- `test(e2e): add reconnect and offline convergence matrix`
- `test(e2e): cover upload, sheets, history, auth, and fork`
- `feat(p2p): expose direct-peer health and fallback state`
- `feat(recorder): metadata, playback, retry, and duration limits`
- `docs: label experimental features and define support matrix`
- `ops: protect persistent data directory from competing instances`
- `perf: split advanced feature bundles and enforce size budget`
