# LivePaste Feature Audit Report

**Assessment date:** 2026-09-19 (updated after v3.18.0 remediation)  
**Audit mode:** gstack-style multi-persona review  
**Personas deployed:** QA, review, investigate, plan-eng-review, office-hours, design-review, and cso/security  
**Scope:** Backend API/WebSockets/storage, frontend routes and hooks, editor workflows, PWA/offline/P2P/media features, CLI/operations, documentation, and live preview smoke checks.

## Executive summary

LivePaste has a strong working core: anonymous paste creation, read-only sharing, edit-token authorization, WebSocket collaboration, Yjs relay, presence, password protection, expiry, burn-after-read, revisions, files, multiple pages, forking, and security headers are implemented and covered by a meaningful backend suite.

The product is **substantially more reliable after the v3.18.0 remediation**, but it is not yet feature-complete at the level claimed by the README. The two runner exception-path defects are fixed, CRDT listeners now rebind when a socket is replaced, the service worker is registered in production builds, and persistent storage is now the safe CLI default. Advanced offline conflict recovery, P2P fallback observability, recording compatibility, browser coverage, and bundle size remain open work.

### Release recommendation

- **Core paste/collaboration:** suitable for continued development and controlled LAN/self-host use.
- **Public release:** v3.18.0 is suitable for controlled LAN/self-host use; advanced features should retain experimental/support-matrix labels until browser coverage lands.
- **Immediate priority:** add browser-level regression coverage for offline, P2P, recording, runner execution, and reconnect; the original P0 code defects are fixed.

## Evidence and method

### gstack personas

| Persona | Review focus | Result |
|---|---|---|
| QA | Real user paths, regression risk, browser behavior | Core flows passed; advanced capabilities need browser coverage |
| Review | Static correctness, dead paths, docs/code mismatch | Found runner defects, stale listeners, unregistered SW |
| Investigate | Root causes rather than symptoms | Traced each high-confidence finding to a concrete code path |
| Plan-eng-review | Boundaries, state ownership, recovery strategy | Collaboration state needs a single connection lifecycle owner |
| Office-hours | Product value and prioritization | Core sharing is clear; advanced claims overstate maturity |
| Design-review | Discoverability, feedback, graceful failure | Offline/P2P/recording need stronger status and failure explanations |
| CSO/security | Abuse boundaries and untrusted content | Prior security audit remains broadly sound; runner needs stronger isolation policy |

### Automated evidence

- Backend: **56 passed** (`pytest tests/ -q`).
- Frontend: **4 passed** (`yarn test --run`), with React `act(...)` warnings.
- Frontend production build: **passes**, with a 968 KB minified JS chunk warning.
- Live preview: home and paste editor rendered; prior session demonstrated authenticated two-client CRDT sync, presence, Live status, and read-only enforcement.
- Browser automation daemon became unreliable during the reconnect/advanced-feature pass, so unsupported claims are explicitly marked as static or unverified rather than called passing.

## Findings by priority

### P0 — resolved in v3.18.0

#### F-01: JavaScript runner exception reporting — resolved

**Evidence:** `frontend/src/lib/runner.js`, `JS_WORKER_SRC` catch block.

```js
} catch {
  clearTimeout(timer);
  logs.push({ level: "error", text: (err && err.stack) || String(err) });
  self.postMessage({ ok: false, logs, error: (err && err.message) || String(err) });
}
```

The worker catch clause now binds `err`, normalizes the message, and returns the original stack/message in the structured worker response. User exceptions no longer trigger a secondary `ReferenceError`.

**Impact:** Resolved for the identified defect; browser execution coverage remains to be expanded.  
**Confidence:** Fixed statically and covered by build validation.  
**Acceptance test:** `throw new Error("boom")` returns `{ok:false, error:"boom"}` and displays the error without an uncaught worker error.

#### F-02: Python runner exception reporting — resolved

**Evidence:** `frontend/src/lib/runner.js`, `PY_WORKER_SRC` catch block.

```js
} catch {
  self.postMessage({ id, ok: false, logs, error: String(err.message || err) });
}
```

The worker catch clause now binds `err` and returns a stable message for Python syntax errors, imports, runtime exceptions, and Pyodide load failures. The remote CDN dependency and lack of visible progress/cancellation remain separate limitations.

**Impact:** The identified error-reporting defect is resolved; runtime and CDN integration coverage is still needed.  
**Confidence:** Fixed statically and build-validated.  
**Acceptance test:** syntax error, runtime error, CDN failure, and timeout each return a stable structured error and reset the runner UI.

### P1 — partially resolved; remaining reliability work

#### F-03: CRDT reconnect listener ownership — remediated

**Evidence:** `frontend/src/hooks/useCollab.js`. The message effect reads `const ws = wsRef.current` and installs `ws.addEventListener("message", onMessage)`, but its dependency array contains `enabled`, `wsRef`, `ydocRef`, `docVersion`, and `ytext` — not the current socket or a connection generation. `wsRef` is stable while `PastePage` replaces `wsRef.current` on reconnect.

The page now increments a connection generation whenever it creates a socket, and `useCollab` includes that generation in its listener effect dependencies. The listener is removed from the old socket and attached to the replacement. A real two-browser restart test is still required to prove convergence under network failure.

**Impact:** The identified stale-listener defect is addressed; the message architecture still has two dispatch paths.  
**Confidence:** High static confidence in the fix; live restart proof remains outstanding.  
**Recommended next step:** consolidate socket message dispatch when browser integration coverage is added.

#### F-04: Offline-first PWA registration — remediated; browser proof pending

**Evidence:** `frontend/public/sw.js` contains install/activate/fetch handlers and the manifest is linked from `frontend/index.html`. v3.18.0 now registers `/sw.js` on `load` for production builds, with a resilient warning when registration fails.

IndexedDB persistence through `useOfflineDoc` still works for a loaded page, and the production app now registers the service worker. The cold offline navigation path and cache update lifecycle still need browser verification.

**Impact:** Registration is fixed; offline shell correctness and cache/API semantics remain unverified.  
**Confidence:** Registration fixed statically and build-validated.  
**Next step:** add a production browser test for registration, offline route reload, cache invalidation, and write exclusion.

#### F-05: Offline synchronization has no conflict/recovery state machine

**Evidence:** `useOfflineDoc` creates IndexedDB persistence, while `PastePage` hydrates a local main-sheet string after a 3.5s handshake timeout. There is no explicit queued-update count, merge confirmation, conflict UI, retry result, or durable failure state. The offline reader is also text-oriented while the editor has multiple sheets and attachment references.

**Impact:** A user may see “offline” and type successfully but cannot tell whether edits have synced, whether a server copy won, or whether a non-main sheet/attachment is recoverable.  
**Confidence:** High static finding; browser offline/online testing was not completed in this pass.  
**Acceptance test:** cold offline open, edit, reconnect, server merge, duplicate-tab conflict, multi-sheet recovery, and failed upload are all observable and tested.

#### F-06: P2P mode has no complete user-facing fallback or health proof

**Evidence:** `useP2P.js` creates a `WebrtcProvider` and uses the correct backend route `/api/webrtc/signaling`. However, the UI only exposes coarse `off | connecting | connected` state and peer count. WebRTC NAT failure, signaling failure, permission/policy restrictions, and relay fallback are not surfaced with actionable guidance. The comments promise LAN direct data flow, but there is no browser integration test proving two actual peers exchange a Yjs update.

**Impact:** P2P can silently fall back to the normal server path or look connected without a direct peer; users cannot distinguish those cases.  
**Confidence:** Static plus incomplete empirical coverage.  
**Acceptance test:** two-browser WebRTC exchange, signaling failure, same-browser fallback, sheet switch, peer departure, and server-only fallback.

#### F-07: Voice/screen recording is browser-dependent and under-specified

**Evidence:** `useRecorder.js` correctly stops tracks and handles unsupported APIs, but screen capture asks for `{video, audio:true}` then separately requests microphone permission. Browser support, MIME/container compatibility, maximum duration, upload failure, and large recording memory behavior are not surfaced as a product workflow. A screen recording is labeled/uploaded through the generic file path, with no playback-specific card validation in the audit.

**Impact:** Recordings may produce files a viewer cannot play, fail after a long capture, or upload without a clear retry path.  
**Confidence:** Static; no real microphone/screen permission run was possible in the automated preview.  
**Acceptance test:** Chrome/Safari/Firefox voice and screen matrix, track-ended behavior, cancel, long capture, upload retry, playback, and unsupported-browser messaging.

### P2 — important quality and product gaps

#### F-08: Runner security boundary is weaker than the product language suggests

JavaScript runs in a worker but intentionally retains `fetch`, and Python downloads/executes Pyodide from a CDN. This is not a server sandbox and is not equivalent to safe execution of hostile code. A worker limits direct DOM access but does not provide a security boundary against browser/network abuse, CPU/memory exhaustion, or data exfiltration from permitted origins.

**Recommendation:** describe it as “best-effort client-side execution,” add network policy and resource budgets, terminate workers on timeout, and never run untrusted code with access to application-origin secrets. Consider disabling the feature by default for untrusted/public pastes.

#### F-09: API/UI contract drift is easy to create

The audit's earlier direct API probe used `slug`/`expiry_days`, while the actual Pydantic API accepts `customSlug`/`expiry`. The UI is correct today, but there is no generated schema/client contract test. Similar drift is likely around legacy query password transports and sheet/file APIs.

**Recommendation:** generate or snapshot OpenAPI schemas, add contract tests for every UI mutation, and remove undocumented aliases after a migration window.

#### F-10: Revisions are full-text snapshots, not a complete collaborative history

The README promises “every edit snapshotted (last 50)” while the implementation intentionally throttles full-text backups to at most one per five seconds and CRDT updates are stored separately. This is reasonable for storage, but users may expect every meaningful keystroke or a named revision. Restore and diff are main-sheet oriented; multi-sheet revision semantics are not clearly exposed.

**Recommendation:** define revision semantics explicitly: autosave checkpoints, named snapshots, author, sheet, and restore scope. Add retention/compaction tests at scale.

#### F-11: Frontend test coverage is too narrow

Only four `PastePage` mount/regression tests exist. They mock the transport and do not test actual editor input, reconnect, offline hydration, P2P, upload, password UI, burn/expiry UI, history restore, recorder, or runner workers. Backend coverage is much stronger but does not replace browser tests.

The tests also emit React `act(...)` warnings, which should be cleaned up so future warnings are meaningful.

#### F-12: Production bundle is oversized

`yarn build` succeeds but emits a 968 KB minified JS chunk and a Vite warning above the 900 KB threshold. Pyodide is loaded lazily at runtime, but the main bundle still contains a large application surface and many UI modules.

**Recommendation:** route-level/code splitting, lazy-load history/preview/recording/P2P, and establish a bundle budget in CI.

#### F-13: Ephemeral startup was a dangerous operational default — resolved

v3.18.0 makes persistent storage the default and adds explicit `livepaste start --ephemeral` for destructive temporary sessions. Restart propagation preserves persistence unless `KEEP_DATA=0` is configured. Competing-process detection and confirmation before purging a non-empty directory remain recommended hardening.

#### F-14: Documentation overstates maturity of advanced features

README sections present offline PWA, P2P, voice/screen notes, runnable pastes, and installability as complete features. The static audit shows source presence, but not complete browser-level reliability. Add maturity labels (“experimental”, “best effort”, “supported browsers”) and link each advanced claim to an acceptance test.

## Feature scorecard

| Feature | Source | Core QA | Completeness | Status |
|---|---:|---:|---:|---|
| Paste creation/read-only links | Yes | Passed | 95% | Production-ready core |
| Edit-token authorization | Yes | Passed/live verified | 95% | Strong |
| WebSocket/Yjs collaboration | Yes | Passed/live verified | 85% | Reconnect browser proof pending |
| Presence/cursors/reactions | Yes | Partial | 80% | Needs reconnect/browser tests |
| Password lockout | Yes | Passed | 90% | Strong; legacy URL transport remains |
| Expiry/burn-after-read | Yes | Passed | 90% | Strong; operational purge footgun |
| File/image upload/delete | Yes | Passed | 90% | Strong; needs browser UX tests |
| Multiple sheets | Yes | Passed backend | 80% | Needs multi-client/browser coverage |
| Revision history/diff/restore | Yes | Passed backend | 75% | Semantics need clarification |
| Markdown/HTML preview | Yes | Static/security verified | 85% | Strong; add browser cases |
| Forking | Yes | Passed backend | 85% | Needs UI end-to-end test |
| Find/replace/command palette | Yes | Static | 80% | Needs interaction coverage |
| JS runnable blocks | Yes | Not fully tested | 65% | Error path fixed; browser coverage pending |
| Python runnable blocks | Yes | Not fully tested | 60% | Error path fixed; CDN/UX risk remains |
| Offline IndexedDB editing | Yes | Static | 55% | P1 recovery/merge gaps |
| Installable PWA/service worker | Yes | Not passed | 60% | Registration fixed; offline proof pending |
| P2P WebRTC | Yes | Signaling backend passed | 50% | P1 browser proof/fallback gaps |
| Voice/screen notes | Yes | Not passed | 50% | P1 compatibility/upload gaps |
| CLI/update/release | Yes | Prior release verified | 90% | Persistent default; process guardrails pending |

## What is working well

- Backend tests cover auth, password-gated read paths, revisions, files, sheets, fork, burn deduplication, rate limiting, signaling bounds, origin checks, and connection budgets.
- Edit tokens and derived capabilities are enforced server-side; public client IDs are not sufficient for writes.
- Uploaded HTML/SVG is served as attachment with `nosniff` in the prior security probe.
- Markdown uses DOMPurify and HTML preview uses a sandboxed iframe.
- Core editor and two-client CRDT behavior were demonstrated live in Preview before the audit session was interrupted.

## Audit conclusion

The project is not a failed or nonfunctional prototype. It is a solid core collaboration product with an ambitious layer of advanced features that need a second reliability pass. The correct next move is not a broad rewrite: v3.18.0 fixes the three highest-confidence correctness gaps and the destructive CLI default. The next reliability gate is browser contract coverage for reconnect, offline, P2P, recording, and runner execution, followed by either hardening or clearly labeling the remaining advanced features as experimental.
