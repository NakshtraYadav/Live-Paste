# plan.md

## 1. Objectives
- Deliver an anonymous, real-time collaborative “live paste” app (dontpad-style) on FastAPI + React + MongoDB.
- Core workflow: open a shared link → edit text → all connected clients see updates instantly via WebSockets routed through `/api/ws/{slug}`.
- Support random IDs by default + optional custom slug, optional expiry (1h/1d/1w/never), syntax highlighting for common languages, copy content/link, view count, dark mode.

## 2. Implementation Steps

### Phase 1 — Core WebSocket + Persistence POC (isolation; do not proceed until stable)
**User stories**
1. As a user, I can connect to a paste’s WebSocket endpoint through the public preview URL and stay connected.
2. As a user, when I send an edit event, all other connected clients receive it within ~1s.
3. As a user, I can refresh and the latest content loads from MongoDB.
4. As a user, I can join/leave and see an accurate active-connection count.
5. As a developer, I can run a Python script to prove external `wss://.../api/ws/{slug}` connectivity via ingress.

**Steps**
- Websearch best practices for FastAPI WebSockets behind ingress (timeouts, headers, ping/keepalive).
- Implement minimal backend:
  - `GET /api/health`
  - `GET /api/paste/{slug}` (load from Mongo)
  - `POST /api/paste` (create: random code + optional custom slug, expiry)
  - `WS /api/ws/{slug}`: broadcast to room, send current doc on join, track connections, persist updates (debounced server-side).
- Data model (Mongo): `{ slug, content, language, createdAt, updatedAt, expiresAt?, views }`.
- Expiry POC: on read/join, if `expiresAt < now` treat as expired; optionally add TTL index later.
- Write `scripts/ws_poc_test.py`:
  - Connect 2+ clients to external `wss://<preview>/api/ws/testslug`.
  - Client A sends edits; assert client B receives; assert reconnect loads latest from REST.
- Iterate until: stable WS through ingress (no 404/upgrade issues), broadcast works, persistence verified.

### Phase 2 — V1 App Development (build around proven core)
**User stories**
1. As a user, I can create a new paste with optional custom slug, expiry, and language, and get a shareable link.
2. As a user, visiting a paste link opens a live editor where everyone with the link can edit.
3. As a user, I see syntax highlighting while editing and can change language mode.
4. As a user, I can copy the paste content and copy the share link with one click.
5. As a user, I can see live viewers and total view count, and use dark mode.

**Backend**
- Finalize REST:
  - `POST /api/paste` validates slug uniqueness; returns canonical URL.
  - `GET /api/paste/{slug}` increments view count (once per session/localStorage marker).
- WebSocket protocol (JSON):
  - `join` → server replies `{type:'init', content, language, viewers}`.
  - `edit` → `{type:'edit', content, version?, updatedAt}` broadcast (last-write-wins MVP).
  - `presence` updates viewer count.
- Expiry: enforce on REST + WS join; return `410 Gone`/`expired` message.

**Frontend (React)**
- Routes:
  - `/` create page.
  - `/:slug` live editor page.
- Editor:
  - `react-simple-code-editor` + `prismjs` (load common languages: markup, css, clike, javascript, typescript, python, go, java, cpp, bash, json, yaml, markdown, sql).
  - Debounce outgoing edits (e.g., 150–300ms) + show connection status.
- UI features:
  - Copy content button + copy link button.
  - Viewer count (live) + view count.
  - Dark mode toggle (persist to localStorage).
  - Expiry selector on create + display remaining time when applicable.
- Use design agent for polished layout (minimal, fast, readable typography).

**End Phase 2**
- Run one full E2E pass with testing agent: create → share → two tabs edit sync → refresh persistence → expiry behavior → copy buttons → dark mode.

### Phase 3 — Hardening + Feature Additions (production-friendly modularization)
**User stories**
1. As a user, I can safely edit in multiple tabs without the app becoming laggy or losing content.
2. As a user, I can recover gracefully if my connection drops (auto-reconnect + re-init).
3. As a user, I can choose/see the language reliably and it persists with the paste.
4. As a user, expired pastes clearly show an expired state and don’t allow edits.
5. As an operator, old expired pastes are cleaned automatically.

**Steps**
- Add optimistic versioning (monotonic `rev`) to reduce overwrite surprises (still MVP).
- Add server keepalive/ping + frontend auto-reconnect with backoff.
- Add Mongo TTL index on `expiresAt` (where supported) + retain lazy-check guard.
- Improve slug rules + reserved paths handling (`api`, `p`, etc.).
- Performance: avoid broadcasting on no-op; cap max paste size (configurable) + show error.

**End Phase 3**
- Testing agent: concurrency (2–3 clients), reconnect, expiry cleanup, large paste, reserved slug errors.

### Phase 4 — Optional Enhancements (only after V1 is solid)
**User stories**
1. As a user, I can set a read-only mode link variant if I want to share without edits.
2. As a user, I can export/download as `.txt`/`.md`.
3. As a user, I can see basic history (last N snapshots) and restore one.
4. As a user, I can set a password on a paste (no accounts).
5. As a user, I can search within the paste and jump to matches.

## 3. Next Actions
1. Implement Phase 1 minimal backend endpoints + WS room broadcaster under `/api/ws/{slug}`.
2. Add Mongo model + save/load.
3. Create and run `ws_poc_test.py` against external preview URL; fix ingress/WS issues until stable.
4. Only after Phase 1 passes, proceed to Phase 2 full React UI + end-to-end testing.

## 4. Success Criteria
- POC: External `wss://<preview>/api/ws/{slug}` connects reliably; edits broadcast to all clients; latest content persists in Mongo and reloads correctly.
- V1: Users can create/share a link, collaboratively edit with live updates, syntax highlighting works for common languages, copy content/link works, view + viewer counts display, dark mode works.
- Reliability: Reconnect works, expired pastes block edits and show clear state, TTL/lazy expiry prevents stale data.
