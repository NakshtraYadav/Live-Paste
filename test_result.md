#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================

user_problem_statement: "Images pasted into a paste were shown as attachments (bottom strip) instead of appearing inline in the document. Add Google Docs / Word style inline images. Then: make LivePaste an installable package (pip from GitHub repo NakshtraYadav/Live-Paste) with local SQLite storage (no MongoDB locally), LAN access, self-update from GitHub, and an interactive animated installer."

backend:
  - task: "Installer PATH bug fix: livepaste command not found after install"
    implemented: true
    working: true
    file: "install.sh"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "user"
          comment: "User installed on macOS via curl|bash, used default port, custom directory, started+closed the app. Afterwards `livepaste start`/`config` → command not found. Installer only printed a manual PATH hint (~/.local/bin not on PATH by default on macOS)."
        - working: "NA"
          agent: "main"
          comment: "Fix in install.sh: (1) link_cli now prefers symlink targets already on PATH and writable (incl. /opt/homebrew/bin, /usr/local/bin, any writable $HOME dir on PATH) before falling back to ~/.local/bin; (2) new ensure_on_path() automatically appends export PATH=\"<linkdir>:$PATH\" to the correct shell profile (~/.zshrc for zsh, ~/.bash_profile on macOS bash, ~/.bashrc on Linux bash, ~/.profile fallback), idempotently, and prints clear 'open a new terminal or source <profile>' instructions. Needs testing-agent verification."
        - working: true
          agent: "testing"
          comment: "Comprehensive installer PATH fix verification completed. ALL 4 test scenarios PASSED: ✅ Scenario 1 (PATH-fix): Installed to /tmp/th1 with PATH not including ~/.local/bin. Installer created symlink at /tmp/th1/.local/bin/livepaste, added exactly ONE export PATH line to .bashrc with idempotent check, printed clear instructions. Simulated new terminal test PASSED: `livepaste version` returned v1.5.0, `livepaste config` showed configuration, `livepaste start --port 8188` started successfully and responded to health check. ✅ Scenario 2 (Idempotency): Re-ran installer with same HOME. .bashrc still contains exactly ONE PATH export line (grep -c = 1). ✅ Scenario 3 (Already-on-PATH): Installed to /tmp/th2 with ~/.local/bin already on PATH. Symlink created, NO .bashrc file created, NO PATH export added, NO manual warning shown. ✅ Scenario 4 (zsh profile): Installed to /tmp/th3 with SHELL=/usr/bin/zsh. PATH export correctly added to .zshrc (not .bashrc). Hosted preview backend health check: 200 OK. The original bug (command not found after install) is completely fixed."

  - task: "Storage-layer refactor: livepaste package with MongoDB (hosted) + SQLite (local) backends"
    implemented: true
    working: true
    file: "livepaste/core.py, livepaste/storage.py, backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: "Moved the whole FastAPI app into /app/livepaste package with a pluggable storage layer. backend/server.py is now a thin wrapper (loads backend/.env, imports livepaste.core:app) so supervisor/preview still uses MongoDB via MONGO_URL. SQLite mode verified separately on port 8090 (REST, WS edit, image file storage, SPA serving all pass). Preview Mongo mode needs full regression: health, create paste (random+custom slug, reserved/duplicate/invalid validation), get paste + count_view, image upload/get/delete (GridFS), WS /api/ws/{slug} (init/edit/language/presence/not_found), expiry validation, 400KB cap."
        - working: true
          agent: "testing"
          comment: "Comprehensive regression test completed against https://command-hub-119.preview.emergentagent.com. ALL 26 tests PASSED: ✅ Health endpoint (200 OK, ISO timestamp) ✅ Create paste with random 7-char slug (rev=0, views=0) ✅ Create paste with custom slug ✅ Duplicate slug validation (409) ✅ Reserved slug validation (400 for 'api') ✅ Invalid slug validation (400 for short/bad chars) ✅ Invalid expiry validation (400) ✅ Expiry 1h (expiresAt ~1h future) ✅ Expiry never (expiresAt=null) ✅ Content size limit (413 for >400KB) ✅ Get paste (returns correct data) ✅ Get paste with count_view=true (increments views) ✅ Get unknown paste (404) ✅ Image upload (returns 24-hex id, url, name, size) ✅ Image get (200 with image/* content-type and Content-Length) ✅ Image delete (returns ok:true) ✅ Image get after delete (404) ✅ Image upload non-image (400) ✅ Image upload to unknown slug (404) ✅ WebSocket init (receives type:init with paste and viewers) ✅ WebSocket edit (broadcasts with incremented rev, persists to DB) ✅ WebSocket language (broadcasts language change) ✅ WebSocket presence (broadcasts viewer count on join/leave) ✅ WebSocket ping/pong ✅ WebSocket not_found (error + close for non-existent slug). Serialization verified: all timestamps are ISO strings, no ObjectId leakage in any JSON response. MongoDB GridFS image storage working correctly. Storage-layer refactor is production-ready."

frontend:
  - task: "Inline images in paste editor (Google Docs style)"
    implemented: true
    working: true
    file: "frontend/src/components/InlineBlocksEditor.jsx, frontend/src/pages/PastePage.jsx, frontend/src/index.css"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: "Rewrote editor as block-based document: content string (with ![name](url) token lines) is parsed into alternating text/image blocks. Text blocks keep Prism syntax highlighting + per-block line numbers in gutter; image token lines render as actual inline <img> with hover controls (open / copy URL / delete). Clipboard paste, drag&drop, and Add-image button all insert the image at the caret position. Backspace at start of a block deletes the image above it (and removes orphaned GridFS file). Removed the bottom attachments strip. Verified via browser automation: inline render at correct line, caret insertion, typing between images, backspace delete + server file cleanup, persistence via WS/Mongo. Backend untouched."

metadata:
  created_by: "main_agent"
  version: "1.2"
  test_sequence: 3
  run_ui: false

test_plan:
  current_focus: []
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    - agent: "main"
      message: "Frontend-only change. New component InlineBlocksEditor.jsx replaces the single react-simple-code-editor instance in PastePage. Test ids: paste-inline-image-{id}, paste-inline-image-open/copy/delete-{id}, paste-insert-zone-{index}, paste-live-editor. Attachment strip test ids (paste-attachments-strip etc.) were removed intentionally. Real-time sync model unchanged (full-content WS edits)."
    - agent: "main"
      message: "v1.4.0: Added CLI features — livepaste config (port/data-dir/keep-data/repo persisted in ~/.livepaste/config), livepaste autostart enable/disable/status (macOS launchd plist + Linux systemd user unit), installer prompts for install location + autostart. Local SQLite mode is now ephemeral by default: purge_all() on graceful shutdown AND on startup (covers force-kill), guarded to SQLite only via LIVEPASTE_EPHEMERAL env set by CLI — hosted Mongo mode untouched (verified: preview health + paste creation OK after change). All flows tested in container: config persistence, graceful-exit wipe, force-kill recovery wipe, --keep-data persistence, autostart unit generation."
    - agent: "testing"
      message: "Backend regression testing complete. Created comprehensive test suite in /app/backend_test.py covering all 26 test scenarios from the review request. All tests passed successfully against the public URL https://command-hub-119.preview.emergentagest.com/api. The storage-layer refactor is working perfectly in MongoDB mode: REST endpoints (health, paste CRUD, image upload/get/delete via GridFS), WebSocket real-time collaboration (init, edit with rev tracking, language broadcast, presence, ping/pong, error handling), validation (slug format, reserved slugs, duplicates, expiry, content size), and serialization (ISO timestamps, no ObjectId leakage). No critical issues found. Backend is production-ready."
    - agent: "testing"
      message: "Installer PATH bug fix verification complete. Tested all 4 scenarios: (1) PATH-fix with ~/.local/bin not on PATH - installer automatically added export PATH to .bashrc and livepaste command works in new terminal, (2) Idempotency - re-running installer keeps only ONE PATH export line, (3) Already-on-PATH - no .bashrc modification when target dir already on PATH, (4) zsh profile - correctly uses .zshrc for zsh shell. The original bug (command not found after install) is completely resolved. Hosted preview backend remains healthy."