# Changelog

All notable changes to **LivePaste** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.2.0] - 2025-07

### Added
- **Inline images (Google Docs style)** — pasted, dropped, or uploaded images now render as actual images at the exact spot in the document where they were inserted, instead of appearing in an attachments strip.
- **Hover controls on inline images** — open full size, copy image URL, and delete, shown on mouse-over of each image.
- **Keyboard editing around images** — Backspace at the start of a line deletes the image above it; Delete at the end of a line removes the image below; arrow keys move the caret across images.
- **Click-to-type zones** — slim insert zones between adjacent images and at document edges let you place the caret anywhere.
- **Automatic file cleanup** — deleting an image (button or Backspace) also removes the stored file from GridFS when no references remain.

### Changed
- Editor re-architected as a block-based document (`InlineBlocksEditor`): text segments keep Prism syntax highlighting and continuous line numbers, image token lines render as inline image blocks. The underlying content format and real-time sync protocol are unchanged.

### Removed
- Bottom "Images (N)" attachments strip — superseded by inline rendering.

---

## [1.1.0] - 2025-07

### Added
- **Image support** — paste (Ctrl/Cmd+V) or upload screenshots and images directly into a paste; stored in MongoDB GridFS (up to 100 MB per image) with inline previews and one-click deletion.
- **Line numbers** in the editor gutter, kept in sync with scrolling and wrapping.
- **Status bar** showing live line count, character count, and paste size metrics.
- Image API endpoints: `POST /api/paste/{slug}/image`, `GET /api/image/{image_id}`, `DELETE /api/image/{image_id}` (streamed responses).

### Changed
- Editor layout refined to accommodate the gutter and status bar without breaking syntax-highlight overlay alignment.

---

## [1.0.0] - 2025-07

### Added
- **Anonymous live pastes** — create a paste with no account and share a single URL; everyone with the link can view and edit together.
- **Real-time collaborative editing** over WebSockets (`/api/ws/{slug}`) with room-based broadcast and revision tracking.
- **Random short slugs** by default, with optional **custom slugs** (validated, reserved names protected, duplicates rejected).
- **Optional expiry** — 1 hour / 1 day / 1 week / never, enforced server-side with automatic cleanup of expired pastes.
- **Syntax highlighting** (Prism) for many languages — Python, JavaScript/Node, TypeScript, and more — with a language selector.
- **Live presence** — see how many viewers are currently connected, plus a total view counter.
- **Copy link** and **copy content** one-click actions.
- **Dark mode** toggle persisted to `localStorage`.
- Content size cap of 400 KB per paste.
- REST API: `GET /api/health`, `POST /api/paste`, `GET /api/paste/{slug}`.
- MongoDB persistence (Motor async driver) — pastes survive refreshes and reconnects.
- WebSocket POC test script (`scripts/ws_poc_test.py`) validating external `wss://` connectivity through ingress (13/13 checks passed).

[1.2.0]: #120---2025-07
[1.1.0]: #110---2025-07
[1.0.0]: #100---2025-07
