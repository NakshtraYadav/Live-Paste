# plan.md (Updated)

## 1. Objectives
- Deliver an anonymous, real-time collaborative **live paste** app (dontpad-style) on **FastAPI + React + MongoDB**.
- Core workflow: open a shared link → edit text/code → all connected clients see updates instantly via **WebSockets** routed through **`/api/ws/{slug}`**.
- Support (current V1+):
  - **Random IDs by default** + **optional custom slug**
  - **Optional expiry** (1h/1d/1w/never) with server enforcement + cleanup
  - **Syntax highlighting** (Prism) for many languages (Python, NodeJS/JS, TS, etc.)
  - **Copy link** + **copy content**
  - **Live viewer count** + **total view count**
  - **Dark mode toggle** persisted to localStorage
  - **Image support**: paste/upload screenshots and images, inline insertion, previews, deletion
  - **Line numbers** + status bar showing **line/char/size** metrics
- Status: **V1+ shipped and tested (backend + frontend + real-time sync + images + line numbers).**

## 2. Implementation Steps

### Phase 1 — Core WebSocket + Persistence POC (isolation; do not proceed until stable) ✅ COMPLETE
**User stories**
1. As a user, I can connect to a paste’s WebSocket endpoint through the public preview URL and stay connected.
2. As a user, when I send an edit event, all other connected clients receive it within ~1s.
3. As a user, I can refresh and the latest content loads from MongoDB.
4. As a user, I can join/leave and see an accurate active-connection count.
5. As a developer, I can run a Python script to prove external `wss://.../api/ws/{slug}` connectivity via ingress.

**Implemented / Verified**
- Backend endpoints proven behind ingress:
  - `GET /api/health`
  - `POST /api/paste` (random slug by default, optional custom slug)
  - `GET /api/paste/{slug}` (load from Mongo)
  - `WS /api/ws/{slug}` room broadcast with presence
- POC test script created and run: `scripts/ws_poc_test.py`
  - External `wss://livepaste.preview.emergentagent.com/api/ws/{slug}` connectivity verified
  - Broadcast edits between multiple clients verified
  - Presence/viewer count messages verified
  - Mongo persistence verified via REST reload
  - Custom/duplicate/invalid slug validation verified
  - Non-existent slug WS returns `{type:'error', code:'not_found'}` then closes
- Result: **13/13 checks passed**.

### Phase 2 — V1 App Development (build around proven core) ✅ COMPLETE
**User stories**
1. As a user, I can create a new paste with optional custom slug, expiry, and language, and get a shareable link.
2. As a user, visiting a paste link opens a live editor where everyone with the link can edit.
3. As a user, I see syntax highlighting while editing and can change language mode.
4. As a user, I can copy the paste content and copy the share link with one click.
5. As a user, I can see live viewers and total view count, and use dark mode.

**Backend (Implemented)**
- REST
  - `POST /api/paste`
    - Random slug by default; optional `customSlug`
    - Reserved slug protection (e.g., `api`, etc.)
    - Expiry options: `1h | 1d | 1w | never`
    - Size cap: **400KB**
  - `GET /api/paste/{slug}`
    - Returns persisted content/language
    - Optional view counting (`count_view=true`) increments `views`
- WebSocket `WS /api/ws/{slug}`
  - Message types: `init | edit | language | presence | error | ping/pong`
  - Room broadcast for collaborative editing (anyone with link can edit)
  - Presence tracking per slug (live viewer count)
  - Persistence on edit (last-write-wins MVP)
- Expiry
  - Enforced on REST + WS join
  - **Mongo TTL index** on `expiresAt` + **lazy cleanup** on read/join
- Data model includes: `slug, content, language, views, createdAt, updatedAt, expiresAt, rev`

**Frontend (Implemented)**
- App name/UI: **LivePaste** (design system defined in `design_guidelines.md`)
- Pages
  - `/` Home page
    - Hero + create form (textarea, custom slug, language select, expiry select)
    - “How it works” section
  - `/:slug` Paste page
    - Full-screen live editor using `react-simple-code-editor` + Prism highlighting
    - Sticky toolbar with:
      - Slug/link display
      - Copy link + copy content buttons
      - Language selector (23 languages)
      - Live viewer count + total views
      - Connection status pill
      - Expiry countdown badge
      - Dark/light theme toggle (persisted)
    - Loading + Not-found/Expired states
- Real-time behavior
  - Debounced outgoing edits (~250ms)
  - Auto-reconnect with backoff
  - Keepalive pings
- Testing hooks
  - `data-testid` attributes added across key UI elements

**End Phase 2 Validation (Complete)**
- Testing agent `iteration_1`: **100% pass**
  - Backend: **16/16 tests passed**
  - Frontend: all key flows passed, including **critical 2-tab real-time sync (~1.5s) and bidirectional editing**
  - No open bugs

### Phase 2.5 — Feature Addition: Images + Line Numbers ✅ COMPLETE
**New user stories (post-V1)**
1. As a user, I can paste screenshots/images into a paste (clipboard paste), or add them via drag & drop or upload button.
2. As a user, images appear **inline** within the paste content (as a link/token) and sync to all collaborators live.
3. As a user, I can preview and manage images (open/copy URL/delete) without accounts; anyone with the link can delete.
4. As a user, I can see **line numbers** and live metrics (line count) to verify whether code is complete/missing.

**Backend (Implemented)**
- MongoDB **GridFS** bucket: `images` via `AsyncIOMotorGridFSBucket`.
- Endpoints:
  - `POST /api/paste/{slug}/image`
    - `multipart/form-data` upload
    - Accepts `image/*` only
    - Streams in 1MB chunks
    - Max size: **100MB per image**
    - Returns `{id, url, name, size, contentType}`
  - `GET /api/image/{id}`
    - Streams bytes via `StreamingResponse`
    - Includes cache headers
  - `DELETE /api/image/{id}`
    - Deletes image by id (anonymous; anyone can delete)
- Expiry cascade:
  - When a paste is detected expired (lazy path), paste document is deleted and **all images with `metadata.slug` are purged**.
- Ingress verification:
  - Verified **60MB** uploads successfully pass through the external URL.

**Frontend (Implemented)**
- Inline images model:
  - Upload inserts markdown token at cursor: `![name](<API_BASE>/api/image/{id})`
  - Images list is derived by parsing paste text for `/api/image/{id}` tokens (no new WS message types needed).
  - Real-time sync piggybacks on existing WS `edit` updates.
- Image input methods:
  - **Clipboard paste** (Ctrl/Cmd+V) for images inside the editor
  - **Drag & drop** on editor surface with a drop overlay
  - Toolbar **“Add image”** button using hidden file input
  - Upload progress indicator in toolbar
- Attachments strip:
  - Bottom strip shows thumbnails + open/copy URL/delete actions
  - Delete action removes token from text and calls backend delete
- Line numbers + metrics:
  - Sticky left gutter with **line numbers**
  - Editor set to **no-wrap** with horizontal scroll for long lines
  - Bottom status bar displays: `N lines · M chars · size` and updates live
- Minor UX tweak:
  - “Copied” feedback duration increased from **900ms → 1600ms**.

**End Phase 2.5 Validation (Complete)**
- Testing agent `iteration_2`: **100% pass**
  - Backend: **24/24 tests passed** (includes new image API tests)
  - Frontend: image upload via file input, real-time sync across tabs, delete flow, line-number updates, status bar updates, regression suite.
  - Note: Clipboard/drag&drop are difficult to automate, but they share the same upload path as the tested file-upload flow.

### Phase 3 — Hardening + Production Readiness (optional, future) ⏳ NOT STARTED (No open issues)
**User stories**
1. As a user, I can safely edit in multiple tabs without the app becoming laggy or losing content.
2. As a user, I can recover gracefully if my connection drops (auto-reconnect + re-init).
3. As a user, I can choose/see the language reliably and it persists with the paste.
4. As a user, expired pastes clearly show an expired state and don’t allow edits.
5. As an operator, old expired pastes are cleaned automatically.

**Notes on current status**
- Several hardening items are already implemented:
  - Client auto-reconnect + keepalive pings exist
  - TTL index + lazy expiry cleanup exist
  - Image purge on paste expiry exists (lazy path)
  - `rev` is stored in Mongo (not yet used for conflict resolution)

**Potential improvements (if/when needed)**
- Add optimistic concurrency/version checks using `rev` (reduce overwrite surprises beyond last-write-wins).
- Server-side debounce/coalescing of edits to reduce DB write frequency during heavy typing.
- Better connection-state UX (explicit offline banner, retry button) and more robust ping/pong handling.
- Rate limiting / abuse prevention (optional), configurable max paste size, and configurable max image size.
- Optional malware/EXIF stripping or image transcoding pipeline (if required for security/privacy).

**End Phase 3**
- Re-run testing agent with heavier concurrency (3+ clients), reconnect scenarios, large paste, expiry cleanup verification.

### Phase 4 — Optional Enhancements (only if requested) ⏳ NOT STARTED
**User stories**
1. As a user, I can generate a read-only link variant for sharing without edits.
2. As a user, I can export/download as `.txt`/`.md`.
3. As a user, I can see basic history (last N snapshots) and restore one.
4. As a user, I can set a password on a paste (no accounts).
5. As a user, I can search within the paste and jump to matches.
6. As a user, I can render markdown (including inline images) in a read-only preview mode.

## 3. Next Actions
1. ✅ No immediate engineering tasks required (V1+ shipped and passes tests).
2. If you want to continue:
   - Decide which Phase 3 hardening items matter most (rev-based conflict handling vs. performance vs. abuse protections).
   - Choose Phase 4 enhancements (read-only mode, export, history, password, search, markdown preview).

## 4. Success Criteria
- ✅ POC success: External `wss://<preview>/api/ws/{slug}` connects reliably; edits broadcast; persistence confirmed.
- ✅ V1 success: Create/share a link; collaborative editing with live updates; syntax highlighting; copy link/content; live viewer + view count; dark mode; expiry supported.
- ✅ V1+ success: **Upload/paste images** (up to 100MB) stored in GridFS; inline references sync live; attachments strip supports open/copy/delete; **line numbers + live line/char/size metrics**.
- ✅ Reliability baseline: Auto-reconnect and keepalive; expired pastes show clear state and are cleaned via TTL/lazy checks; paste expiry cascades to image cleanup.
- Future (optional): Rev-based conflict handling, performance improvements, and additional sharing/export/security features.
