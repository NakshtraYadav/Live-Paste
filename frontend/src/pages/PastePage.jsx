import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import * as Y from "yjs";
import {
  Link2,
  Copy,
  Check,
  Users,
  Eye,
  Clock,
  Wifi,
  WifiOff,
  Home,
  Loader2,
  Paperclip,
  UploadCloud,
  History,
  KeyRound,
  Eye as EyeIcon,
  X,
  CloudOff,
  Network,
  Mic,
  Smile,
  QrCode,
  Flame,
  MonitorUp,
  CircleStop,
  RotateCcw,
  ArrowUpCircle,
  Share2,
  GitFork,
  ChevronLeft,
  ChevronRight,
  FileText,
  Globe,
  Search,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ThemeToggle } from "@/components/ThemeToggle";
import InlineBlocksEditor, { parseBlocks } from "@/components/InlineBlocksEditor";
import MarkdownView from "@/components/MarkdownView";
import DiffView from "@/components/DiffView";
import {
  Command,
  CommandDialog,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandShortcut,
} from "@/components/ui/command";
import useCollab from "@/hooks/useCollab";
import usePresence from "@/hooks/usePresence";
import useP2P from "@/hooks/useP2P";
import { useOfflineDoc, useOnlineStatus, readOfflineDoc, hasOfflineDoc } from "@/hooks/useOfflineDoc";
import { getIdentity, setDisplayName } from "@/lib/identity";
import { runInSandbox, detectLanguageOf } from "@/lib/runner";
import {
  LANGUAGES,
  API_BASE,
  WS_BASE,
  copyToClipboard,
  formatTimeLeft,
} from "@/lib/constants";
import {
  editTokenStore,
  editorCapabilityStore,
  consumeEditTokenFromUrl,
} from "@/lib/editToken";
import { useRecorder } from "@/hooks/useRecorder";
import { QRCodeSVG } from "qrcode.react";

const DEBOUNCE_MS = 250;
const PING_INTERVAL_MS = 25000;
const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100MB

const encodeWebSocketAuth = (payload) => {
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
};

const formatBytes = (bytes) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export default function PastePage() {
  const { slug } = useParams();
  const navigate = useNavigate();

  const [status, setStatus] = useState("loading"); // loading | ready | notfound | expired | locked
  const [burnAfterViews, setBurnAfterViews] = useState(null);
  const [showQr, setShowQr] = useState(false);
  const [reactions, setReactions] = useState([]); // {id, emoji, name, color, x}
  const [showReactionBar, setShowReactionBar] = useState(false);
  const [content, setContent] = useState("");
  const [language, setLanguage] = useState("plaintext");
  const [viewers, setViewers] = useState(1);
  const [views, setViews] = useState(0);
  const [expiresAt, setExpiresAt] = useState(null);
  const [timeLeft, setTimeLeft] = useState(null);
  const [connState, setConnState] = useState("connecting"); // connecting | connected | reconnecting | disconnected
  const [copiedLink, setCopiedLink] = useState(false);
  const [forking, setForking] = useState(false); // v3.7.0
  const [copiedContent, setCopiedContent] = useState(false);
  const [copiedEdit, setCopiedEdit] = useState(false);
  const [uploadPct, setUploadPct] = useState(null); // null = not uploading
  const [dragging, setDragging] = useState(false);
  const [sheets, setSheets] = useState([{ sheetId: "main", name: "Page 1", position: 0 }]);
  const [activeSheet, setActiveSheet] = useState("main");
  const [sheetContents, setSheetContents] = useState({ main: "" }); // sheetId → text for non-active rendering
  const [renamingSheet, setRenamingSheet] = useState(null); // sheetId being renamed
  const [renameValue, setRenameValue] = useState("");
  const [canEdit, setCanEdit] = useState(false);
  const [isOwner, setIsOwner] = useState(false);
  const [editors, setEditors] = useState([]); // clientIds granted edit permission
  const [localCopyAvailable, setLocalCopyAvailable] = useState(false); // server wiped, we have an offline copy
  // Seed from localStorage synchronously. The first render happens before the
  // slug effect runs; actions such as upload/copy can otherwise see an empty
  // token during that short handshake window.
  const [editToken, setEditToken] = useState(() => editTokenStore.get(slug));
  const [editorCapability, setEditorCapability] = useState(() => editorCapabilityStore.get(slug));
  const [showHistory, setShowHistory] = useState(false);
  const [mdPreview, setMdPreview] = useState(false); // v3.10.0 markdown preview toggle
  const [htmlPreview, setHtmlPreview] = useState(false); // v3.11.0 sandboxed HTML preview
  const [diffRev, setDiffRev] = useState(null); // v3.12.0 revision being diffed
  const [diffData, setDiffData] = useState(null); // { oldText, newText }
  const [showFind, setShowFind] = useState(false); // v3.13.0 find & replace
  const [findText, setFindText] = useState("");
  const [replaceText, setReplaceText] = useState("");
  const [findCase, setFindCase] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false); // v3.14.0 command palette
  const [revisions, setRevisions] = useState(null); // null = not loaded
  const [docVersion, setDocVersion] = useState(0); // bump when the Y.Doc instance is swapped
  const [revLoading, setRevLoading] = useState(false);
  const [serverVersion, setServerVersion] = useState(null);
  const [latestRelease, setLatestRelease] = useState(null);
  const [updateDismissed, setUpdateDismissed] = useState(false);
  const [runOutput, setRunOutput] = useState(null); // {blockIndex, status, output}

  const wsRef = useRef(null);
  const debounceRef = useRef(null);
  const pingRef = useRef(null);
  const reconnectRef = useRef(null);
  const retriesRef = useRef(0);
  const closedRef = useRef(false);
  const contentRef = useRef("");
  const editorApiRef = useRef(null);
  const fileInputRef = useRef(null);
  const dragDepthRef = useRef(0);
  const ydocRef = useRef(new Y.Doc());
  const applyingRemoteRef = useRef(false);
  const gotInitRef = useRef(false);
  const offlineTimerRef = useRef(null);
  // Session-only view passwords for locked pastes (never persisted to disk)
  const lockedPastePasswords = useRef({});
  const activeSheetRef = useRef("main");
  const sheetYdocsRef = useRef(new Map()); // sheetId → Y.Doc for background sheets
  const pendingUpdatesRef = useRef(new Map()); // sheetId → Uint8Array[] of missed updates

  useEffect(() => {
    document.title = `/${slug} — LivePaste`;
    setEditToken(consumeEditTokenFromUrl(slug));
    setEditorCapability(editorCapabilityStore.get(slug));
    // Fresh Y.Doc per paste
    ydocRef.current = new Y.Doc();
    setDocVersion((v) => v + 1);
    return () => {
      ydocRef.current.destroy();
      ydocRef.current = new Y.Doc();
    };
  }, [slug]);

  // ---- server version + latest release (update banner) ----
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const v = await axios.get(`${API_BASE}/api/version`);
        if (!cancelled) setServerVersion(v.data.version);
      } catch (e) {
        /* older server */
      }
      try {
        const r = await axios.get(
          "https://api.github.com/repos/NakshtraYadav/Live-Paste/releases/latest",
        );
        if (!cancelled) setLatestRelease(r.data.tag_name?.replace(/^v/, ""));
      } catch (e) {
        /* offline or no releases */
      }
    };
    check();
    return () => {
      cancelled = true;
    };
  }, []);

  // ---- WebSocket connection with auto-reconnect ----
  const connectWs = useCallback(() => {
    if (closedRef.current) return;
    const existing = wsRef.current;
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) return;
    const token = editTokenStore.get(slug);
    const pw = lockedPastePasswords.current[slug] || "";
    const clientId = getIdentity().clientId;
    const params = new URLSearchParams();
    if (clientId) params.set("clientId", clientId);
    const capability = editorCapabilityStore.get(slug) || editorCapability;
    const qs = params.toString();
    const authProtocol = `lp-auth.${encodeWebSocketAuth({
      token,
      password: pw,
      clientId,
      capability,
    })}`;
    const ws = new WebSocket(
      `${WS_BASE}/api/ws/${slug}${qs ? `?${qs}` : ""}`,
      [authProtocol],
    );
    wsRef.current = ws;
    activeSheetRef.current = activeSheet;

    // Offline cold start: if the handshake never completes (server down, no
    // network), hydrate the editor from the IndexedDB mirror so the paste is
    // still readable/editable. Queued CRDT updates merge on reconnect.
    gotInitRef.current = false;
    if (offlineTimerRef.current) clearTimeout(offlineTimerRef.current);
    offlineTimerRef.current = setTimeout(async () => {
      if (gotInitRef.current || closedRef.current) return;
      let cached = null;
      try {
        cached = await readOfflineDoc(slug, "main");
      } catch (e) {
        cached = null;
      }
      if (gotInitRef.current || closedRef.current) return;
      if (cached) {
        setContent(cached);
        contentRef.current = cached;
        const ytext = ydocRef.current.getText("content");
        if (ytext.length === 0 && cached) {
          ydocRef.current.transact(() => ytext.insert(0, cached));
        }
        setStatus("ready");
        setConnState("disconnected");
        toast.info("Offline — showing your locally saved copy. Edits sync when you reconnect.");
      } else {
        setConnState("disconnected");
      }
    }, 3500);

    ws.onopen = () => {
      retriesRef.current = 0;
      setConnState("connected");
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      switch (msg.type) {
        case "init":
          gotInitRef.current = true;
          if (offlineTimerRef.current) clearTimeout(offlineTimerRef.current);
          setCanEdit(!!msg.canEdit);
          setIsOwner(!!msg.isOwner);
          if (msg.editorCapability) {
            editorCapabilityStore.save(slug, msg.editorCapability);
            setEditorCapability(msg.editorCapability);
          }
          setEditors(Array.isArray(msg.editors) ? msg.editors : []);
          setBurnAfterViews(msg.burnAfterViews || null);
          {
            const c = msg.paste.content || "";
            setContent(c);
            contentRef.current = c;
            // Seed the CRDT doc if empty; otherwise remote yupdates apply on top
            const ytext = ydocRef.current.getText("content");
            if (ytext.length === 0 && c && !msg.yUpdatesB64) {
              ydocRef.current.transact(() => ytext.insert(0, c));
            }
          }
          if (Array.isArray(msg.sheets) && msg.sheets.length) {
            setSheets(msg.sheets);
          }
          setLanguage(msg.paste.language || "plaintext");
          setViews(msg.paste.views || 0);
          setExpiresAt(msg.paste.expiresAt);
          setViewers(msg.viewers || 1);
          setStatus("ready");
          break;
        case "yupdate":
          // Applied inside useCollab; a re-render pulse arrives via remotePulse
          break;
        case "s:state": {
          // CRDT history for a sheet we just opened
          if (msg.sheetId !== activeSheetRef.current) break;
          const list = msg.yUpdatesB64 || [];
          if (list.length) {
            for (const b64 of list) {
              try {
                const bin = atob(b64);
                const bytes = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
                Y.applyUpdate(ydocRef.current, bytes, `s:${msg.sheetId}`);
              } catch (e) {
                /* ignore bad update */
              }
            }
            // Sync React state from the merged doc right away
            const merged = ydocRef.current.getText("content").toString();
            applyingRemoteRef.current = true;
            setContent(merged);
            contentRef.current = merged;
            applyingRemoteRef.current = false;
          } else {
            // No stored CRDT state — this is a fresh sheet. Seed ONLY when the
            // REST text is actually non-empty (a brand-new page must start
            // blank, never inherit the previous page) and the user hasn't
            // started typing while the answer was in flight (a stale s:state
            // must not clobber fresh local edits).
            const ytext = ydocRef.current.getText("content");
            const rest = contentRef.current || "";
            if (ytext.length === 0 && rest.length > 0) {
              ydocRef.current.transact(() => ytext.insert(0, rest));
            }
          }
          break;
        }
        case "s:yupdate": {
          if (msg.sheetId === activeSheetRef.current) {
            const ytext = ydocRef.current.getText("content");
            try {
              const bin = atob(msg.updateB64);
              const bytes = new Uint8Array(bin.length);
              for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
              Y.applyUpdate(ydocRef.current, bytes, "remote");
            } catch (e) {
              /* ignore */
            }
          } else {
            // background sheet: cache the update until it's opened
            try {
              const bin = atob(msg.updateB64);
              const bytes = new Uint8Array(bin.length);
              for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
              const doc = sheetYdocsRef.current.get(msg.sheetId);
              if (doc) Y.applyUpdate(doc, bytes, "remote");
              pendingUpdatesRef.current.set(
                msg.sheetId,
                [...(pendingUpdatesRef.current.get(msg.sheetId) || []), bytes],
              );
            } catch (e) {
              /* ignore */
            }
          }
          break;
        }
        case "s:edit":
          if (msg.sheetId === activeSheetRef.current) {
            setContent(msg.content);
            contentRef.current = msg.content;
          } else {
            setSheetContents((m) => ({ ...m, [msg.sheetId]: msg.content }));
          }
          break;
        case "s:language":
          if (msg.sheetId === activeSheetRef.current) setLanguage(msg.language || "plaintext");
          break;
        case "sheets-changed":
          refreshSheets();
          if (msg.action === "deleted" && msg.sheetId === activeSheetRef.current) {
            switchSheet("main");
            toast.info("This page was deleted by another editor");
          }
          break;
        case "restore":
          if (activeSheetRef.current === "main") {
            setContent(msg.content);
            contentRef.current = msg.content;
            const ytext = ydocRef.current.getText("content");
            ydocRef.current.transact(() => {
              ytext.delete(0, ytext.length);
              ytext.insert(0, msg.content);
            }, "restore");
            toast.info("Paste was restored to an earlier version");
          }
          break;
        case "edit":
          // Fallback full-text sync (only when CRDT is not in play)
          if (activeSheetRef.current === "main") {
            setContent(msg.content);
            contentRef.current = msg.content;
          }
          break;
        case "files-changed":
          // Another client added/removed an attachment — nothing to do;
          // file cards re-resolve from their URLs automatically.
          break;
        case "language":
          setLanguage(msg.language || "plaintext");
          break;
        case "presence":
          setViewers(msg.viewers || 1);
          break;
        case "editor-capability":
          editorCapabilityStore.save(slug, msg.capability || "");
          setEditorCapability(msg.capability || "");
          break;
        case "editors": {
          // v3.3.0: my edit rights may have changed live (grant/revoke).
          setEditors(Array.isArray(msg.editors) ? msg.editors : []);
          if (msg.granted && msg.changed === getIdentity().clientId) {
            setCanEdit(true);
            toast.success("You were granted edit access ✏️");
          } else if (!msg.granted && msg.changed === getIdentity().clientId) {
            setCanEdit(false);
            toast.info("Your edit access was revoked");
          }
          break;
        }
        case "reaction":
          if (msg.r) spawnReaction(msg.r);
          break;
        case "error":
          if (msg.code === "not_found") {
            closedRef.current = true;
            // v3.4.0: distinguish "server restarted in ephemeral mode and
            // wiped the paste" from a genuinely dead link — if the browser
            // holds an offline copy, offer to restore it. (Fire-and-forget:
            // the message handler stays synchronous so messages are never
            // processed out of order.)
            setStatus("notfound");
            hasOfflineDoc(slug, "main").then((have) => {
              if (have) setLocalCopyAvailable(true);
            });
          } else if (msg.code === "expired") {
            closedRef.current = true;
            setStatus("expired");
          } else if (msg.code === "password_required") {
            closedRef.current = true;
            setStatus("locked");
          } else if (msg.code === "too_many_attempts") {
            closedRef.current = true;
            setStatus("locked");
            toast.error(msg.message || "Too many attempts — try again in a few minutes");
          } else if (msg.code === "too_large") {
            toast.error(msg.message || "Content too large");
          } else if (msg.code === "read_only") {
            toast.error("This link is read-only — ask the owner for an edit link");
          }
          break;
        default:
          break;
      }
    };

    ws.onclose = () => {
      if (closedRef.current) return;
      setConnState("reconnecting");
      const delay = Math.min(1000 * 2 ** retriesRef.current, 10000);
      retriesRef.current += 1;
      if (retriesRef.current > 8) {
        setConnState("disconnected");
        return;
      }
      reconnectRef.current = setTimeout(connectWs, delay);
    };

    ws.onerror = () => {
      try {
        ws.close();
      } catch (e) {
        /* ignore */
      }
    };
  }, [slug]);

  useEffect(() => {
    // Connect as soon as the page mounts — the WS `init` message itself tells us
    // whether the paste exists (error paths below flip status to notfound/expired).
    if (status === "notfound" || status === "expired") return undefined;
    closedRef.current = false;
    retriesRef.current = 0;
    connectWs();

    pingRef.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, PING_INTERVAL_MS);

    return () => {
      closedRef.current = true;
      clearInterval(pingRef.current);
      clearTimeout(reconnectRef.current);
      clearTimeout(debounceRef.current);
      try {
        wsRef.current?.close();
      } catch (e) {
        /* ignore */
      }
    };
  }, [status, connectWs]);

  // Close the socket the moment the page starts unloading (refresh, back,
  // tab close). React unmount can race the browser teardown; this tells the
  // server immediately instead of mid-handshake (fixes 1001 handshake noise).
  useEffect(() => {
    const bye = () => {
      closedRef.current = true;
      try {
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.close(1001, "client navigating away");
          wsRef.current = null;
        }
      } catch (e) {
        /* ignore */
      }
    };
    window.addEventListener("pagehide", bye);
    window.addEventListener("beforeunload", bye);
    return () => {
      window.removeEventListener("pagehide", bye);
      window.removeEventListener("beforeunload", bye);
    };
  }, []);

  // ---- expiry countdown ----
  useEffect(() => {
    if (!expiresAt) {
      setTimeLeft(null);
      return undefined;
    }
    const update = () => {
      const t = formatTimeLeft(expiresAt);
      setTimeLeft(t);
      if (t === "Expired") setStatus("expired");
    };
    update();
    const iv = setInterval(update, 30000);
    return () => clearInterval(iv);
  }, [expiresAt]);

  // ---- CRDT plumbing (active once the WS is up) ----
  const { ytext, remotePulse } = useCollab({
    wsRef,
    enabled: status !== "notfound" && status !== "expired",
    ydocRef,
    docVersion,
    sheetRef: activeSheetRef,
  });

  // ---- presence: live cursors + avatar bar (awareness) ----
  const { peers, cursorsForSheet, sendCursor } = usePresence({
    wsRef,
    slug,
    enabled: status !== "notfound" && status !== "expired",
    connState,
    canEdit,
    sheetRef: activeSheetRef,
  });
  const [myName, setMyName] = useState(() => getIdentity().name);

  // ---- offline-first: mirror the Y.Doc into IndexedDB (survives reloads & offline) ----
  useOfflineDoc({
    slug,
    ydocRef,
    docVersion,
    sheetRef: activeSheetRef,
    enabled: status === "ready",
  });
  const online = useOnlineStatus();

  // ---- floating emoji reactions (v3.1.0) ----
  const spawnReaction = useCallback((data) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setReactions((list) => [...list.slice(-14), { id, ...data }]);
    setTimeout(() => {
      setReactions((list) => list.filter((r) => r.id !== id));
    }, 3200);
  }, []);

  const sendReaction = useCallback(
    (emoji) => {
      const me = getIdentity();
      const payload = { emoji, name: me.name, color: me.color, x: 0.35 + Math.random() * 0.3 };
      spawnReaction(payload); // show my own bubble immediately
      const ws = wsRef.current;
      if (ws?.readyState === WebSocket.OPEN && canEdit) {
        ws.send(JSON.stringify({ type: "reaction", r: payload }));
      }
    },
    [canEdit, spawnReaction],
  );
  const [p2pEnabled, setP2pEnabled] = useState(() => {
    try {
      return localStorage.getItem("lp_p2p") === "1";
    } catch (e) {
      return false;
    }
  });
  const { p2pPeers, p2pStatus } = useP2P({
    slug,
    ydocRef,
    docVersion,
    sheetId: activeSheet, // v3.4.0: re-attach the data channel on page switch
    enabled: p2pEnabled && status === "ready",
  });
  const toggleP2P = useCallback(() => {
    setP2pEnabled((v) => {
      const next = !v;
      try {
        localStorage.setItem("lp_p2p", next ? "1" : "0");
      } catch (e) {
        /* private mode */
      }
      return next;
    });
  }, []);

  // ---- voice & screen notes: record → upload as a regular paste file ----
  const recorder = useRecorder({
    onComplete: async (blob, label) => {
      const ext = blob.type.includes("webm")
        ? "webm"
        : blob.type.includes("mp4")
          ? "m4a"
          : blob.type.includes("ogg")
            ? "ogg"
            : "bin";
      await uploadFile(new File([blob], `${label}-${Date.now()}.${ext}`, { type: blob.type }));
    },
  });
  const handleRecord = useCallback(
    async (kind) => {
      const res = await recorder.start(kind);
      if (res === "denied") toast.error("Microphone/screen access was denied — check browser permissions");
      else if (res === "unsupported") toast.error("Recording isn't supported in this browser");
    },
    [recorder],
  );

  // When connectivity returns after being fully offline, retry the socket so
  // locally queued CRDT edits drain to the server. A slow periodic retry keeps
  // recovery alive even after the exponential backoff has given up.
  useEffect(() => {
    if (online && connState === "disconnected" && !closedRef.current) {
      retriesRef.current = 0;
      connectWs();
      const iv = setInterval(() => {
        const ws = wsRef.current;
        if (
          !ws ||
          (ws.readyState !== WebSocket.OPEN && ws.readyState !== WebSocket.CONNECTING)
        ) {
          retriesRef.current = 0;
          connectWs();
        }
      }, 10000);
      return () => clearInterval(iv);
    }
    return undefined;
  }, [online, connState, connectWs]);

  // Idle heartbeat: keeps my cursor entry fresh on peers' screens while I'm
  // present but not typing (server prunes after 30s of silence).
  useEffect(() => {
    if (!canEdit || status === "notfound" || status === "expired") return undefined;
    const iv = setInterval(() => {
      const ed = document.querySelector(".lp-blocks textarea");
      const pos = ed ? ed.selectionStart ?? 0 : 0;
      sendCursor(pos, pos);
    }, 12000);
    return () => clearInterval(iv);
  }, [canEdit, status, sendCursor]);

  // ---- Runnable pastes: execute a text block in a sandbox ----
  const handleRunBlock = useCallback(
    async (blockIndex) => {
      const blocks = parseBlocks(contentRef.current);
      const block = blocks[blockIndex];
      if (!block || block.type !== "text" || typeof block.value !== "string") return;
      const code = block.value;
      // The sheet's language if it's directly runnable, else sniff the code
      const runnableSheet = { javascript: "javascript", js: "javascript", typescript: "javascript", python: "python" }[language];
      const lang = runnableSheet || detectLanguageOf(code);
      if (!lang) {
        toast.error("Only JavaScript and Python blocks can run");
        return;
      }
      setRunOutput({ blockIndex, status: "running", output: "" });
      const res = await runInSandbox(lang, code);
      const parts = (res.logs || []).map((l) => (l.level === "error" ? `✗ ${l.text}` : l.text));
      if (res.result) parts.push(res.result);
      if (!res.ok && res.error) parts.push(`Error: ${res.error}`);
      setRunOutput({
        blockIndex,
        status: res.ok ? "done" : "error",
        output: parts.join("\n") || (res.ok ? "(no output)" : res.error || "Error"),
      });
    },
    [language],
  );

  // Mirror remote CRDT changes into React state (text blocks re-render)
  const firstYRender = useRef(true);
  useEffect(() => {
    if (status === "notfound" || status === "expired" || !ytext) return;
    const txt = ytext.toString();
    if (firstYRender.current) {
      firstYRender.current = false;
      if (txt === "" && contentRef.current) {
        // Seed doc from loaded paste content (single client case)
        ydocRef.current.transact(() => ytext.insert(0, contentRef.current));
        return;
      }
    }
    if (txt !== contentRef.current) {
      applyingRemoteRef.current = true;
      setContent(txt);
      contentRef.current = txt;
      applyingRemoteRef.current = false;
    }
  }, [remotePulse, status, ytext]);

  // ---- send edits over WS (CRDT deltas; full-text as periodic backup) ----
  // The backup full-text channel is sheet-scoped: `edit` only ever refers to the
  // main sheet, other sheets go through `s:edit` so main is never clobbered.
  // v3.5.1 (bug): the full-text backup also fires per keystroke; on the server
  // each one appended a revision, so a 200-word burst produced ~50 identical
  // snapshots and evicted real history (cap is 50). The backup is now throttled
  // to at most one full-text sync per 5s — CRDT deltas still flow per keystroke.
  const lastFullSyncRef = useRef(0);
  const sendEdit = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const now = Date.now();
    if (now - lastFullSyncRef.current < 5000) return;
    lastFullSyncRef.current = now;
    if (activeSheetRef.current === "main") {
      ws.send(JSON.stringify({ type: "edit", content: contentRef.current }));
    } else {
      ws.send(
        JSON.stringify({ type: "s:edit", sheetId: activeSheetRef.current, content: contentRef.current }),
      );
    }
  }, []);

  // Replace the whole Y.Text with newContent using minimal (prefix/suffix) edits
  // so concurrent editors' changes merge instead of clobbering each other.
  const replaceYText = useCallback(
    (ydoc, text, newContent) => {
      const old = text.toString();
      if (old === newContent) return;
      let start = 0;
      const minLen = Math.min(old.length, newContent.length);
      while (start < minLen && old.charCodeAt(start) === newContent.charCodeAt(start)) start += 1;
      let endOld = old.length;
      let endNew = newContent.length;
      while (endOld > start && endNew > start && old.charCodeAt(endOld - 1) === newContent.charCodeAt(endNew - 1)) {
        endOld -= 1;
        endNew -= 1;
      }
      ydoc.transact(() => {
        if (endOld > start) text.delete(start, endOld - start);
        if (endNew > start) text.insert(start, newContent.slice(start, endNew));
      });
    },
    [],
  );

  const applyContent = useCallback(
    (newContent, { fromUser = true } = {}) => {
      setContent(newContent);
      contentRef.current = newContent;
      // Route user typing through the Y.Doc as minimal deltas so peers merge cleanly
      if (fromUser && ytext) {
        replaceYText(ydocRef.current, ytext, newContent);
      }
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(sendEdit, DEBOUNCE_MS);
    },
    [sendEdit, ytext, ydocRef, replaceYText],
  );

  // v3.13.0 — find & replace over the whole paste content.
  const matchCount = useMemo(() => {
    if (!findText) return 0;
    try {
      const hay = findCase ? content : content.toLowerCase();
      const needle = findCase ? findText : findText.toLowerCase();
      let count = 0;
      let pos = hay.indexOf(needle);
      while (pos !== -1) {
        count += 1;
        pos = hay.indexOf(needle, pos + needle.length || 1);
      }
      return count;
    } catch {
      return 0;
    }
  }, [content, findText, findCase]);

  const handleReplaceAll = useCallback(() => {
    if (!findText || !canEdit) return;
    const flags = findCase ? "g" : "gi";
    const escaped = findText.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(escaped, flags);
    const next = content.replace(re, replaceText);
    if (next !== content) {
      applyContent(next);
      toast.success(`Replaced ${matchCount} occurrence${matchCount === 1 ? "" : "s"}`);
    }
  }, [findText, replaceText, findCase, content, canEdit, applyContent, matchCount]);

  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "h") {
        e.preventDefault();
        setShowFind((v) => !v);
      }
      if ((e.metaKey || e.ctrlKey) && (e.key.toLowerCase() === "k" || e.key.toLowerCase() === "p")) {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
      if (e.key === "Escape") setShowFind(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ---- sheets (pages) ----
  const refreshSheets = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/api/paste/${slug}/sheets`);
      if (Array.isArray(res.data.sheets)) setSheets(res.data.sheets);
    } catch (e) {
      /* ignore */
    }
  }, [slug]);

  const switchSheet = useCallback(
    async (sheetId) => {
      if (sheetId === activeSheetRef.current) return;
      // Flush any pending edit for the outgoing sheet BEFORE switching context,
      // otherwise the debounce fires later and writes the old text to the new sheet.
      clearTimeout(debounceRef.current);
      const wsNow = wsRef.current;
      if (wsNow?.readyState === WebSocket.OPEN) {
        const prev = activeSheetRef.current;
        const payload =
          prev === "main"
            ? { type: "edit", content: contentRef.current }
            : { type: "s:edit", sheetId: prev, content: contentRef.current };
        wsNow.send(JSON.stringify(payload));
      }
      // Save current sheet's Y.Doc aside (stays in memory for background sync)
      sheetYdocsRef.current.set(activeSheetRef.current, ydocRef.current);
      activeSheetRef.current = sheetId;
      setActiveSheet(sheetId);
      // v3.4.0 (bug: new pages inherited the previous page's text): reset the
      // content refs BEFORE any await. Swapping the doc bumps docVersion, the
      // mirror effect fires immediately with the fresh (empty) Y.Text, and if
      // contentRef still held the outgoing page it would seed the new page's
      // doc with that text — and relay it to the server for this sheet.
      contentRef.current = "";
      setContent("");
      // Re-announce which sheet I'm on so remote carets re-scope
      try {
        const me = getIdentity();
        const wsP = wsRef.current;
        if (wsP?.readyState === WebSocket.OPEN) {
          wsP.send(JSON.stringify({ type: "hello", i: { clientId: me.clientId, name: me.name, color: me.color, initials: me.initials, sheetId } }));
        }
      } catch (e) { /* ignore */ }

      // Reuse cached doc or spin up a fresh one
      const cached = sheetYdocsRef.current.get(sheetId);
      const nextDoc = cached || new Y.Doc();
      sheetYdocsRef.current.set(sheetId, nextDoc);
      ydocRef.current = nextDoc;
      firstYRender.current = true;
      setDocVersion((v) => v + 1); // ytext memo follows the swapped doc

      try {
        // v3.5.1: locked pastes send the session password in a header, not a URL
        const viewPassword = lockedPastePasswords.current[slug] || "";
        const res = await axios.get(`${API_BASE}/api/paste/${slug}/sheets/${sheetId}`, {
          headers: viewPassword ? { "X-View-Password": viewPassword } : {},
        });
        setLanguage(res.data.language || "plaintext");
        const c = res.data.content || "";
        setContent(c);
        contentRef.current = c;
        // NOTE: the Y.Doc is NOT seeded here — the `s:state` response below is
        // authoritative. If it carries no CRDT history we seed from this text then.
      } catch (e) {
        toast.error("Could not open that page");
        return;
      }
      // Ask the server for this sheet's CRDT history
      const ws = wsRef.current;
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "s:open", sheetId }));
        // replay updates that arrived while the sheet was in the background
        const pending = pendingUpdatesRef.current.get(sheetId) || [];
        for (const bytes of pending) {
          try {
            Y.applyUpdate(nextDoc, bytes, "remote");
          } catch (err) {
            /* ignore */
          }
        }
        pendingUpdatesRef.current.set(sheetId, []);
      }
    },
    [slug],
  );

  const createSheet = useCallback(async () => {
    if (!canEdit) {
      toast.error("This link is read-only");
      return;
    }
    try {
      const res = await axios.post(`${API_BASE}/api/paste/${slug}/sheets`, {
        editToken: editTokenStore.get(slug),
        content: "",
      });
      await refreshSheets();
      await switchSheet(res.data.sheetId);
      toast.success(`"${res.data.name}" created`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not create page");
    }
  }, [canEdit, slug, refreshSheets, switchSheet]);

  // v3.9.0 — move a page left/right within the tab bar (main stays first).
  const moveSheet = useCallback(
    async (sheetId, delta) => {
      if (!canEdit) return;
      const order = sheets.map((s) => s.sheetId);
      const from = order.indexOf(sheetId);
      const to = from + delta;
      if (from < 1 || to < 1 || to >= order.length) return; // never move "main"
      order.splice(to, 0, order.splice(from, 1)[0]);
      try {
        await axios.post(`${API_BASE}/api/paste/${slug}/sheets/reorder`, {
          editToken: editTokenStore.get(slug),
          order,
        });
        await refreshSheets();
      } catch (err) {
        toast.error(err?.response?.data?.detail || "Reorder failed");
      }
    },
    [canEdit, sheets, slug, refreshSheets],
  );

  // v3.8.0 — duplicate a page (content + CRDT history) right after it.
  const duplicateSheet = useCallback(
    async (sheetId) => {
      if (!canEdit) {
        toast.error("This link is read-only");
        return;
      }
      try {
        const res = await axios.post(
          `${API_BASE}/api/paste/${slug}/sheets/${sheetId}/duplicate`,
          { editToken: editTokenStore.get(slug) },
        );
        await refreshSheets();
        toast.success(`"${res.data.name}" created`);
      } catch (err) {
        toast.error(err?.response?.data?.detail || "Duplicate failed");
      }
    },
    [canEdit, slug, refreshSheets],
  );

  const renameSheet = useCallback(
    async (sheetId, name) => {
      try {
        await axios.patch(`${API_BASE}/api/paste/${slug}/sheets/${sheetId}`, {
          editToken: editTokenStore.get(slug),
          name,
        });
        await refreshSheets();
      } catch (err) {
        toast.error(err?.response?.data?.detail || "Rename failed");
      }
    },
    [slug, refreshSheets],
  );

  const deleteSheet = useCallback(
    async (sheetId) => {
      if (!canEdit) {
        toast.error("This link is read-only");
        return;
      }
      try {
        await axios.delete(
          `${API_BASE}/api/paste/${slug}/sheets/${sheetId}?editToken=${encodeURIComponent(editTokenStore.get(slug))}`,
        );
        await refreshSheets();
        if (activeSheetRef.current === sheetId) switchSheet("main");
        toast.success("Page deleted");
      } catch (err) {
        toast.error(err?.response?.data?.detail || "Delete failed");
      }
    },
    [canEdit, slug, refreshSheets, switchSheet],
  );

  const handleChange = (newContent) => {
    if (!canEdit) {
      toast.error("This link is read-only");
      return;
    }
    applyContent(newContent);
  };

  const handleLanguageChange = (lang) => {
    setLanguage(lang);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const type = activeSheetRef.current === "main" ? "language" : "s:language";
      wsRef.current.send(
        JSON.stringify({ type, language: lang, sheetId: activeSheetRef.current }),
      );
    }
  };

  // ---- files (any type): upload ----
  const uploadFile = useCallback(
    async (file) => {
      if (!file) return;
      if (file.size > MAX_FILE_SIZE) {
        toast.error(`"${file.name}" is over the 100MB limit`);
        return;
      }
      const form = new FormData();
      form.append("file", file);
      // Read the token at action time as well as from React state. The page
      // opens the socket before the async handshake updates `editToken`; the
      // old closure therefore uploaded without the creator's token and the
      // server correctly replied "Edit permission required".
      const currentEditToken = editTokenStore.get(slug) || editToken;
      if (currentEditToken) form.append("editToken", currentEditToken);
      const clientId = getIdentity().clientId;
      if (clientId) form.append("clientId", clientId);
      const currentCapability = editorCapabilityStore.get(slug) || editorCapability;
      if (currentCapability) form.append("capability", currentCapability);
      setUploadPct(0);
      try {
        const res = await axios.post(`${API_BASE}/api/paste/${slug}/file`, form, {
          onUploadProgress: (e) => {
            if (e.total) setUploadPct(Math.round((e.loaded / e.total) * 100));
          },
        });
        const { id, name, contentType } = res.data;
        const safeName = (name || "file").replace(/[[\]()]/g, "_");
        const endpoint = (contentType || file.type || "").startsWith("image/") ? "image" : "file";
        editorApiRef.current?.insertFileToken(
          `![${safeName}](${API_BASE}/api/${endpoint}/${id})`,
        );
        toast.success(`File "${name}" added`);
      } catch (err) {
        const msg = err?.response?.data?.detail || "File upload failed";
        toast.error(msg);
      } finally {
        setUploadPct(null);
      }
    },
    [slug, editToken, editorCapability],
  );

  const uploadFiles = useCallback(
    async (files) => {
      const list = Array.from(files || []);
      if (!list.length) return;
      for (const f of list) {
        // eslint-disable-next-line no-await-in-loop
        await uploadFile(f);
      }
    },
    [uploadFile],
  );

  // ---- files: paste from clipboard ----
  const handlePaste = useCallback(
    (e) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const droppedFiles = [];
      for (const item of items) {
        if (item.kind === "file") {
          const f = item.getAsFile();
          if (f) droppedFiles.push(f);
        }
      }
      if (droppedFiles.length) {
        e.preventDefault();
        uploadFiles(droppedFiles);
      }
    },
    [uploadFiles],
  );

  // ---- files: drag & drop ----
  const handleDragEnter = (e) => {
    e.preventDefault();
    dragDepthRef.current += 1;
    if (e.dataTransfer?.types?.includes("Files")) setDragging(true);
  };
  const handleDragOver = (e) => {
    e.preventDefault();
  };
  const handleDragLeave = (e) => {
    e.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDragging(false);
  };
  const handleDrop = (e) => {
    e.preventDefault();
    dragDepthRef.current = 0;
    setDragging(false);
    if (e.dataTransfer?.files?.length) {
      uploadFiles(e.dataTransfer.files);
    }
  };

  // ---- files: delete ----
  const handleDeleteFile = async (file) => {
    // Remove every occurrence of this file's token (image or file URL) from the text
    const re = new RegExp(
      `!\\[[^\\]]*\\]\\([^)\\s]*\\/api\\/(?:image|file)\\/${file.id}\\)\\n?`,
      "g",
    );
    const newContent = contentRef.current.replace(re, "");
    applyContent(newContent);
    try {
      await axios.delete(`${API_BASE}/api/file/${file.id}`, {
        params: {
          editToken: editTokenStore.get(slug) || editToken || "",
          clientId: getIdentity().clientId || "",
          capability: editorCapabilityStore.get(slug) || editorCapability || "",
        },
      });
      toast.success(`File "${file.name}" deleted`);
    } catch (err) {
      toast.error("Could not delete file (reference removed)");
    }
  };

  const handleCopyFileUrl = async (file) => {
    const ok = await copyToClipboard(`${API_BASE}/api/file/${file.id}`);
    if (ok) toast.success("File URL copied");
    else toast.error("Could not copy URL");
  };

  // v3.7.0 — fork: server-side full copy (content, pages, files); the new
  // paste's edit token is stored locally so the creator lands in edit mode.
  const handleFork = async () => {
    try {
      setForking(true);
      const clientId = getIdentity().clientId;
      const capability = editorCapabilityStore.get(slug) || editorCapability;
      const res = await axios.post(
        `${API_BASE}/api/paste/${slug}/fork`,
        { editToken: editToken || "", copyFiles: true },
        { params: { ...(clientId ? { clientId } : {}), ...(capability ? { capability } : {}) } },
      );
      const { slug: newSlug, editToken: newToken } = res.data;
      if (newToken) {
        try {
          localStorage.setItem(`lp_edit_${newSlug}`, newToken);
        } catch {
          /* private mode */
        }
      }
      toast.success("Fork created — opening your copy");
      navigate(`/${newSlug}`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Fork failed");
    } finally {
      setForking(false);
    }
  };

  const handleCopyLink = async () => {
    const ok = await copyToClipboard(window.location.origin + `/${slug}`);
    if (ok) {
      toast.success("View-only link copied");
      setCopiedLink(true);
      setTimeout(() => setCopiedLink(false), 1600);
    } else {
      toast.error("Could not copy link");
    }
  };

  const handleCopyEditLink = async () => {
    // localStorage is the source of truth for the creator token. React state
    // can briefly lag while the WebSocket handshake is completing.
    const currentEditToken = editTokenStore.get(slug) || editToken;
    if (!currentEditToken) {
      toast.error("Your edit token is unavailable — reload this paste");
      return;
    }
    const editUrl = new URL(window.location.pathname, window.location.origin);
    editUrl.hash = `edit=${encodeURIComponent(currentEditToken)}`;
    const ok = await copyToClipboard(editUrl.toString());
    if (ok) {
      toast.success("Edit link copied — anyone with it can edit this paste");
      setCopiedEdit(true);
      setTimeout(() => setCopiedEdit(false), 1600);
    } else {
      toast.error("Could not copy edit link");
    }
  };

  // ---- revision history ----
  const loadRevisions = useCallback(async () => {
    setRevLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/api/paste/${slug}/revisions`);
      setRevisions(res.data.revisions || []);
    } catch (err) {
      setRevisions([]);
      toast.error("Could not load history");
    } finally {
      setRevLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    if (showHistory && revisions === null) loadRevisions();
  }, [showHistory, revisions, loadRevisions]);

  // v3.12.0 — load a revision and diff it against the current content.
  const handleDiffRevision = async (rev) => {
    try {
      const viewPassword = lockedPastePasswords.current[slug] || "";
      const res = await axios.get(`${API_BASE}/api/paste/${slug}/revisions/${rev}`, {
        headers: viewPassword ? { "X-View-Password": viewPassword } : {},
      });
      setDiffData({ oldText: res.data.content || "", newText: contentRef.current || "" });
      setDiffRev(rev);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not load revision");
    }
  };

  const handleRestoreRevision = async (rev) => {
    try {
      const viewPassword = lockedPastePasswords.current[slug] || "";
      const res = await axios.get(`${API_BASE}/api/paste/${slug}/revisions/${rev}`, {
        headers: viewPassword ? { "X-View-Password": viewPassword } : {},
      });
      const restored = res.data.content;
      await axios.post(`${API_BASE}/api/paste/${slug}/restore`, {
        editToken,
        content: restored,
      });
      applyContent(restored, { fromUser: false });
      toast.success(`Restored revision ${rev}`);
      setShowHistory(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Restore failed");
    }
  };

  const handleCopyContent = async () => {
    const ok = await copyToClipboard(contentRef.current);
    if (ok) {
      toast.success("Content copied to clipboard");
      setCopiedContent(true);
      setTimeout(() => setCopiedContent(false), 1600);
    } else {
      toast.error("Could not copy content");
    }
  };

  // v3.15.0 — command palette actions. MUST stay below every function it lists in
  // its dependency array (createSheet, duplicateSheet, handleCopy*): the deps array
  // is evaluated during render, so an earlier position is a TDZ ReferenceError.
  const paletteActions = useMemo(() => {
    const acts = [
      { group: "Pages", label: "Add new page", shortcut: "", run: createSheet, disabled: !canEdit, testid: "palette-add-page" },
      { group: "Pages", label: "Duplicate current page", run: () => duplicateSheet(activeSheetRef.current), disabled: !canEdit, testid: "palette-duplicate-page" },
      { group: "Edit", label: "Find & replace", shortcut: "⌘H", run: () => setShowFind(true), disabled: false, testid: "palette-find" },
      { group: "View", label: mdPreview ? "Hide markdown preview" : "Markdown preview", run: () => setMdPreview((v) => !v), disabled: false, testid: "palette-md" },
      { group: "View", label: htmlPreview ? "Hide HTML preview" : "HTML preview", run: () => setHtmlPreview((v) => !v), disabled: !(language === "html" || /<html[\s>]|<!doctype html/i.test(content || "")), testid: "palette-html" },
      { group: "View", label: showHistory ? "Close revision history" : "Revision history", run: () => setShowHistory((v) => !v), disabled: false, testid: "palette-history" },
      { group: "Share", label: "Copy view-only link", run: handleCopyLink, disabled: false, testid: "palette-copy-view-link" },
      { group: "Share", label: "Copy content", run: handleCopyContent, disabled: false, testid: "palette-copy-content" },
      { group: "Share", label: "Fork this paste", run: handleFork, disabled: false, testid: "palette-fork" },
    ];
    if (canEdit && (editToken || editTokenStore.get(slug))) {
      acts.splice(2, 0, { group: "Share", label: "Copy edit link", run: handleCopyEditLink, disabled: false, testid: "palette-copy-edit-link" });
    }
    return acts;
  }, [canEdit, editToken, mdPreview, htmlPreview, showHistory, language, content, slug, createSheet, duplicateSheet, handleCopyLink, handleCopyEditLink, handleCopyContent, handleFork]);

  // ---- derived stats ----
  const lineCount = useMemo(() => content.split("\n").length, [content]);
  const charCount = content.length;

  // ---------- render states ----------
  if (status === "loading") {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="flex items-center gap-3 text-muted-foreground" data-testid="paste-loading">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="font-mono text-sm">Loading /{slug}…</span>
        </div>
      </div>
    );
  }

  if (status === "locked") {
    const submitPassword = async (e) => {
      e.preventDefault();
      const val = document.getElementById("lp-pw-input")?.value || "";
      try {
        const res = await axios.post(`${API_BASE}/api/paste/${slug}/password`, { password: val });
        if (res.data.ok) {
          lockedPastePasswords.current[slug] = val;
          closedRef.current = false;
          retriesRef.current = 0;
          setStatus("loading");
          connectWs();
        } else {
          toast.error("Wrong password");
        }
      } catch (err) {
        if (err?.response?.status === 429) {
          toast.error("Too many attempts — try again in a few minutes");
        } else {
          toast.error(err?.response?.data?.detail === "Paste not found or expired" ? "Paste not found" : "Could not verify password");
        }
      }
    };
    return (
      <div className="min-h-screen bg-background flex items-center justify-center px-4">
        <div className="w-full max-w-sm border border-border bg-card rounded-xl p-6 sm:p-8" data-testid="locked-state">
          <div className="h-10 w-10 rounded-lg bg-secondary flex items-center justify-center">
            <KeyRound className="h-5 w-5 text-muted-foreground" />
          </div>
          <h1 className="mt-4 text-xl font-semibold">This paste is locked</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Enter the view password the owner shared with you.
          </p>
          <form onSubmit={submitPassword} className="mt-5 flex gap-2">
            <input
              id="lp-pw-input"
              type="password"
              autoFocus
              data-testid="locked-password-input"
              placeholder="Password"
              className="flex-1 font-mono text-sm bg-[hsl(var(--editor-bg))] text-[hsl(var(--editor-fg))] border border-border rounded-md px-3 h-9 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]"
            />
            <Button type="submit" data-testid="locked-password-submit">Unlock</Button>
          </form>
        </div>
      </div>
    );
  }

  if (status === "notfound" || status === "expired") {
    const expired = status === "expired";
    return (
      <div className="min-h-screen bg-background">
        <header className="border-b border-border">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
            <button
              onClick={() => navigate("/")}
              className="flex items-center gap-2"
              data-testid="paste-header-logo"
            >
              <div className="h-7 w-7 rounded-md bg-primary flex items-center justify-center">
                <Link2 className="h-4 w-4 text-primary-foreground" />
              </div>
              <span className="font-semibold tracking-tight text-lg">LivePaste</span>
            </button>
            <ThemeToggle testId="paste-theme-toggle" />
          </div>
        </header>
        <div className="max-w-xl mx-auto px-4 sm:px-6 py-14" data-testid="not-found-state">
          <div className="border border-border bg-card rounded-xl p-6 sm:p-8">
            <div className="h-10 w-10 rounded-lg bg-secondary flex items-center justify-center">
              <Clock className="h-5 w-5 text-muted-foreground" />
            </div>
            <h1 className="mt-4 text-xl sm:text-2xl font-semibold">
              {expired ? "This link expired" : "Nothing at this link"}
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {expired
                ? "The paste at this address reached its expiry and was deleted."
                : `There's no paste at /${slug}. It may have expired, been deleted, or the URL is wrong.`}
            </p>
            {localCopyAvailable && !expired && (
              <div className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm" data-testid="local-copy-rescue">
                <p className="font-medium">You have a local copy of this paste.</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  The server may have restarted in temporary mode and wiped it. You can restore your
                  offline copy as a brand-new paste — everything you had is preserved.
                </p>
                <Button
                  size="sm"
                  className="mt-2"
                  data-testid="restore-local-copy-button"
                  onClick={async () => {
                    try {
                      const text = await readOfflineDoc(slug, "main");
                      const create = await fetch("/api/paste", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ content: text || "", expiry: "never" }),
                      }).then((r) => r.json());
                      if (create.slug) {
                        editTokenStore.save(create.slug, create.editToken || "");
                        toast.success("Restored as a new paste");
                        window.location.assign(`/${create.slug}`);
                      } else {
                        toast.error("Could not restore — try creating a paste manually");
                      }
                    } catch (e) {
                      toast.error("Could not read the local copy");
                    }
                  }}
                >
                  <RotateCcw className="h-4 w-4 mr-2" /> Restore local copy as new paste
                </Button>
              </div>
            )}
            <Button
              className="mt-6"
              onClick={() => navigate("/")}
              data-testid="not-found-create-new-button"
            >
              <Home className="h-4 w-4 mr-2" /> Create a new paste
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const connLabel =
    connState === "connected"
      ? "Live"
      : connState === "reconnecting"
        ? "Reconnecting"
        : connState === "connecting"
          ? "Connecting"
          : "Offline";

  const updateAvailable =
    !!serverVersion &&
    !!latestRelease &&
    latestRelease !== serverVersion &&
    !updateDismissed;

  return (
    <div className="h-screen flex flex-col bg-background">
      {/* Update banner */}
      {updateAvailable && (
        <div
          className="flex items-center justify-center gap-2 px-4 py-1.5 text-xs bg-primary/10 border-b border-primary/20 text-foreground"
          data-testid="paste-update-banner"
        >
          <ArrowUpCircle className="h-3.5 w-3.5 text-primary shrink-0" />
          <span>
            LivePaste <span className="font-mono">v{latestRelease}</span> is available — you're running{" "}
            <span className="font-mono">v{serverVersion}</span>.
          </span>
          <a
            href={`https://github.com/NakshtraYadav/Live-Paste/releases/tag/v${latestRelease}`}
            target="_blank"
            rel="noreferrer"
            className="underline text-primary font-medium"
          >
            What's new
          </a>
          <button
            onClick={() => setUpdateDismissed(true)}
            aria-label="Dismiss update banner"
            className="ml-1 p-0.5 rounded hover:bg-secondary"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Toolbar */}
      <div className="sticky top-0 z-40 bg-background border-b border-border">
        <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <button
              onClick={() => navigate("/")}
              aria-label="Go to home"
              data-testid="paste-header-logo"
              className="h-7 w-7 shrink-0 rounded-md bg-primary flex items-center justify-center active:scale-[0.98]"
            >
              <Link2 className="h-4 w-4 text-primary-foreground" />
            </button>
            <span
              className="font-mono text-xs sm:text-sm truncate max-w-[40vw] sm:max-w-[320px] text-muted-foreground"
              data-testid="paste-toolbar-slug-text"
            >
              {window.location.host}/<span className="text-foreground">{slug}</span>
            </span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  data-testid="paste-toolbar-share-button"
                  className="shrink-0 active:scale-[0.98]"
                  aria-label="Share"
                >
                  <Share2 className="h-3.5 w-3.5 sm:mr-1.5" />
                  <span className="hidden sm:inline">Share</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-72">
                <DropdownMenuItem
                  onSelect={handleCopyLink}
                  data-testid="paste-toolbar-copy-link-button"
                >
                  {copiedLink ? <Check className="mr-2 h-4 w-4" /> : <Link2 className="mr-2 h-4 w-4" />}
                  <span className="flex-1">
                    <span className="block text-sm font-medium">Copy view-only link</span>
                    <span className="block text-xs text-muted-foreground">Anyone can read & copy</span>
                  </span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => setShowQr((v) => !v)}
                  data-testid="paste-toolbar-qr-toggle"
                >
                  <QrCode className="mr-2 h-4 w-4" />
                  <span className="flex-1">
                    <span className="block text-sm font-medium">Show QR code</span>
                    <span className="block text-xs text-muted-foreground">Scan to open on your phone</span>
                  </span>
                </DropdownMenuItem>
                {canEdit && (editToken || editTokenStore.get(slug)) && (
                  <DropdownMenuItem
                    onSelect={handleCopyEditLink}
                    data-testid="paste-toolbar-copy-edit-link-button"
                  >
                    {copiedEdit ? <Check className="mr-2 h-4 w-4" /> : <KeyRound className="mr-2 h-4 w-4" />}
                    <span className="flex-1">
                      <span className="block text-sm font-medium">Copy edit link</span>
                      <span className="block text-xs text-muted-foreground">Anyone with it can edit</span>
                    </span>
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem
                  onSelect={handleFork}
                  data-testid="paste-toolbar-fork-button"
                >
                  <GitFork className="mr-2 h-4 w-4" />
                  <span className="flex-1">
                    <span className="block text-sm font-medium">Fork this paste</span>
                    <span className="block text-xs text-muted-foreground">
                      Full independent copy — pages, files and all
                    </span>
                  </span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              variant="outline"
              size="sm"
              onClick={handleCopyContent}
              data-testid="paste-toolbar-copy-content-button"
              className="shrink-0 active:scale-[0.98]"
              aria-label="Copy content"
            >
              {copiedContent ? <Check className="h-3.5 w-3.5 sm:mr-1.5" /> : <Copy className="h-3.5 w-3.5 sm:mr-1.5" />}
              <span className="hidden sm:inline">{copiedContent ? "Copied" : "Copy text"}</span>
            </Button>
            <Button
              variant={mdPreview ? "default" : "outline"}
              size="sm"
              onClick={() => setMdPreview((v) => !v)}
              data-testid="paste-toolbar-markdown-button"
              className="shrink-0 active:scale-[0.98]"
              aria-label="Toggle markdown preview"
              aria-pressed={mdPreview}
            >
              <FileText className="h-3.5 w-3.5 sm:mr-1.5" />
              <span className="hidden sm:inline">MD</span>
            </Button>
            {(language === "html" || /<html[\s>]|<!doctype html/i.test(content || "")) && (
              <Button
                variant={htmlPreview ? "default" : "outline"}
                size="sm"
                onClick={() => setHtmlPreview((v) => !v)}
                data-testid="paste-toolbar-html-preview-button"
                className="shrink-0 active:scale-[0.98]"
                aria-label="Toggle sandboxed HTML preview"
                aria-pressed={htmlPreview}
              >
                <Globe className="h-3.5 w-3.5 sm:mr-1.5" />
                <span className="hidden sm:inline">Run HTML</span>
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowHistory(true)}
              data-testid="paste-toolbar-history-button"
              className="shrink-0 active:scale-[0.98]"
              aria-label="Revision history"
            >
              <History className="h-3.5 w-3.5 sm:mr-1.5" />
              <span className="hidden sm:inline">History</span>
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              data-testid="paste-toolbar-add-file-button"
              className="shrink-0 active:scale-[0.98]"
              aria-label="Add file"
              disabled={uploadPct !== null || !canEdit}
            >
              <Paperclip className="h-3.5 w-3.5 sm:mr-1.5" />
              <span className="hidden sm:inline">Add file</span>
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              data-testid="paste-file-input"
              onChange={(e) => {
                uploadFiles(e.target.files);
                e.target.value = "";
              }}
            />
            {uploadPct !== null && (
              <span
                className="inline-flex items-center gap-1.5 text-xs font-mono text-primary shrink-0"
                data-testid="paste-upload-progress"
              >
                <UploadCloud className="h-3.5 w-3.5 lp-pulse" /> {uploadPct}%
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2 sm:justify-end">
            <Select value={language} onValueChange={handleLanguageChange} disabled={!canEdit}>
              <SelectTrigger
                data-testid="paste-toolbar-language-select"
                className="h-8 w-[130px] sm:w-[150px] text-xs"
                aria-label={`Language: ${language}`}
              >
                <SelectValue placeholder="Language" />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {LANGUAGES.map((l) => (
                  <SelectItem key={l.value} value={l.value}>
                    {l.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Badge
              variant="secondary"
              className="rounded-full gap-1.5 font-mono text-xs"
              data-testid="paste-toolbar-viewer-count"
            >
              <Users className="h-3 w-3" /> {viewers} online
            </Badge>

            {/* Presence: my avatar + remote peers' avatars */}
            <div className="flex items-center" data-testid="paste-presence-bar">
              {[{ clientId: "me", name: myName, color: getIdentity().color, initials: getIdentity().initials, me: true }, ...peers].slice(0, 6).map((p, i, arr) => (
                <button
                  key={p.clientId}
                  type="button"
                  title={p.me ? `${p.name} (you) — click to rename` : p.name}
                  onClick={p.me ? () => {
                    // eslint-disable-next-line no-alert
                    const next = window.prompt("Your display name", myName);
                    if (next && next.trim()) {
                      const id = setDisplayName(next.trim());
                      setMyName(id.name);
                      // v3.4.0: re-announce immediately so everyone's avatar
                      // chips and cursor tags update live, not on next keystroke
                      try {
                        const w = wsRef.current;
                        if (w?.readyState === WebSocket.OPEN) {
                          w.send(JSON.stringify({ type: "hello", i: { clientId: id.clientId, name: id.name, color: id.color, initials: id.initials, sheetId: activeSheetRef.current } }));
                        }
                      } catch (e) { /* ignore */ }
                    }
                  } : isOwner && !p.me ? () => {
                    // v3.3.0: owner clicks a peer's avatar to grant/revoke edit access
                    const granted = editors.includes(p.clientId);
                    if (wsRef.current?.readyState === WebSocket.OPEN) {
                      wsRef.current.send(JSON.stringify({ type: granted ? "revoke-edit" : "grant-edit", clientId: p.clientId }));
                      toast.info(granted ? `Revoked edit access from ${p.name}` : `Granted edit access to ${p.name} ✏️`);
                    }
                  } : undefined}
                  className={`relative inline-flex h-7 w-7 items-center justify-center rounded-full text-[10px] font-semibold text-white ring-2 ring-background ${i > 0 ? "-ml-2" : ""} hover:z-10 transition-transform hover:scale-110 ${isOwner && !p.me && editors.includes(p.clientId) ? "ring-2 ring-emerald-400" : ""}`}
                  style={{ backgroundColor: p.color, zIndex: arr.length - i }}
                  data-testid={`paste-presence-avatar-${p.clientId}`}
                  data-editable={isOwner && !p.me ? String(editors.includes(p.clientId)) : undefined}
                >
                  {p.initials}
                  {isOwner && !p.me && editors.includes(p.clientId) && (
                    <span className="absolute -bottom-1 -right-1 flex h-3 w-3 items-center justify-center rounded-full bg-emerald-500 text-[7px] text-white">✎</span>
                  )}
                </button>
              ))}
              {peers.length > 5 && (
                <span className="-ml-2 inline-flex h-7 items-center justify-center rounded-full bg-muted px-1.5 text-[10px] font-semibold text-muted-foreground ring-2 ring-background" style={{ zIndex: 0 }}>
                  +{peers.length - 5}
                </span>
              )}
            </div>

            <span
              className="inline-flex items-center gap-1 text-xs text-muted-foreground font-mono"
              data-testid="paste-toolbar-total-view-count"
            >
              <Eye className="h-3 w-3" /> {views}
            </span>

            {timeLeft && (
              <Badge
                variant="outline"
                className="rounded-full gap-1.5 font-mono text-xs text-muted-foreground"
                data-testid="paste-toolbar-expiry-badge"
              >
                <Clock className="h-3 w-3" /> {timeLeft}
              </Badge>
            )}

            {burnAfterViews && (
              <Badge
                variant="outline"
                className="rounded-full gap-1.5 font-mono text-xs text-orange-600 border-orange-500/40"
                data-testid="paste-toolbar-burn-badge"
              >
                <Flame className="h-3 w-3" /> burns after {burnAfterViews} views
              </Badge>
            )}

            {canEdit && (
              <div className="relative">
                <button
                  onClick={() => setShowReactionBar((v) => !v)}
                  data-testid="paste-reaction-button"
                  className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
                  title="React with an emoji — everyone sees it float up"
                >
                  <Smile className="h-3 w-3" />
                </button>
                {showReactionBar && (
                  <div
                    className="absolute right-0 top-full mt-1 z-50 flex items-center gap-0.5 rounded-full border border-border bg-popular bg-popover p-1 shadow-lg"
                    data-testid="paste-reaction-bar"
                  >
                    {["🎉", "❤️", "😂", "🔥", "👍", "👀", "🚀", "✨"].map((emo) => (
                      <button
                        key={emo}
                        onClick={() => {
                          sendReaction(emo);
                          setShowReactionBar(false);
                        }}
                        className="rounded-full px-1.5 py-0.5 text-lg leading-none hover:bg-accent transition-transform hover:scale-125"
                        data-testid={`paste-reaction-emoji`}
                      >
                        {emo}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {showQr && (
              <div
                className="lp-qr-overlay"
                data-testid="paste-toolbar-qr"
                onClick={() => setShowQr(false)}
              >
                <div
                  className="flex flex-col items-center gap-2 rounded-xl border border-border bg-card p-4 shadow-lg"
                  onClick={(e) => e.stopPropagation()}
                >
                  <QRCodeSVG
                    value={`${window.location.origin}/${slug}`}
                    size={148}
                    bgColor="transparent"
                    fgColor="currentColor"
                    data-testid="paste-toolbar-qr-canvas"
                  />
                  <span className="text-xs font-medium">scan to open this paste</span>
                  <span className="text-[10px] text-muted-foreground">{window.location.origin}/{slug}</span>
                </div>
              </div>
            )}

            <span
              className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-2.5 py-1 text-xs font-medium"
              data-testid="paste-toolbar-connection-status"
            >
              {connState === "connected" ? (
                <Wifi className="h-3 w-3 text-primary" />
              ) : (
                <WifiOff
                  className={`h-3 w-3 ${connState === "disconnected" ? "text-destructive" : "text-muted-foreground lp-pulse"}`}
                />
              )}
              <span className="sr-only">Connection status:</span>
              {connLabel}
            </span>

            {!online && (
              <Badge
                variant="outline"
                className="rounded-full gap-1.5 font-mono text-xs text-amber-600 border-amber-500/40"
                data-testid="paste-toolbar-offline-badge"
              >
                <CloudOff className="h-3 w-3" /> Offline — edits will sync
              </Badge>
            )}

            <button
              onClick={toggleP2P}
              title={
                p2pEnabled
                  ? "P2P sync is ON — document data flows browser-to-browser, the server only brokers the handshake"
                  : "Enable P2P sync — peers on your network exchange data directly, no server hop"
              }
              data-testid="paste-toolbar-p2p-toggle"
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                p2pEnabled
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-border bg-card text-muted-foreground hover:text-foreground"
              }`}
            >
              <Network className="h-3 w-3" />
              <span className="hidden md:inline">P2P</span>
              {p2pEnabled && (
                <span className="font-mono" data-testid="paste-toolbar-p2p-status">
                  {p2pStatus === "connected"
                    ? `${p2pPeers} peer${p2pPeers === 1 ? "" : "s"}`
                    : p2pStatus}
                </span>
              )}
            </button>

            {recorder.recording ? (
              <button
                onClick={recorder.stop}
                data-testid="paste-recording-indicator"
                className="inline-flex items-center gap-1.5 rounded-full border border-destructive/50 bg-destructive/10 px-2.5 py-1 text-xs font-medium text-destructive animate-pulse"
                title="Click to stop and attach the recording"
              >
                <Mic className="h-3 w-3" />
                <span className="font-mono">REC {String(Math.floor(recorder.seconds / 60)).padStart(2, "0")}:{String(recorder.seconds % 60).padStart(2, "0")}</span>
                <CircleStop className="h-3 w-3" />
              </button>
            ) : (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    data-testid="paste-record-button"
                    className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
                    title="Record a voice note or your screen"
                  >
                    <Mic className="h-3 w-3" />
                    <span className="hidden md:inline">Record</span>
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onSelect={() => handleRecord("voice")}
                    data-testid="paste-record-voice"
                  >
                    <Mic className="mr-2 h-4 w-4" />
                    <span className="flex-1">
                      <span className="block text-sm font-medium">Voice note</span>
                      <span className="block text-xs text-muted-foreground">Record from your microphone</span>
                    </span>
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() => handleRecord("screen")}
                    data-testid="paste-record-screen"
                  >
                    <MonitorUp className="mr-2 h-4 w-4" />
                    <span className="flex-1">
                      <span className="block text-sm font-medium">Screen note</span>
                      <span className="block text-xs text-muted-foreground">Capture your screen (+ mic)</span>
                    </span>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}

            <ThemeToggle testId="paste-toolbar-theme-toggle" />
          </div>
        </div>
      </div>

      {/* Sheet tabs */}
      <div
        className="flex items-center gap-1 px-3 sm:px-4 py-1 border-b border-border bg-background overflow-x-auto"
        data-testid="paste-sheets-bar"
      >
        {sheets.map((s, idx) => {
          const active = s.sheetId === activeSheet;
          const isRenaming = renamingSheet === s.sheetId;
          return (
            <div
              key={s.sheetId}
              className={`group flex items-center rounded-t-md border border-b-0 px-2.5 py-1 text-xs cursor-pointer select-none shrink-0 ${
                active
                  ? "border-border bg-[hsl(var(--editor-bg))] text-foreground font-medium"
                  : "border-transparent text-muted-foreground hover:bg-secondary"
              }`}
              data-testid={`paste-sheet-tab-${s.sheetId}`}
              onClick={() => !isRenaming && switchSheet(s.sheetId)}
              onDoubleClick={() => {
                if (!canEdit || s.sheetId === "main") return;
                setRenamingSheet(s.sheetId);
                setRenameValue(s.name);
              }}
            >
              {isRenaming ? (
                <input
                  autoFocus
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onBlur={() => {
                    setRenamingSheet(null);
                    if (renameValue.trim() && renameValue !== s.name) renameSheet(s.sheetId, renameValue.trim());
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") e.target.blur();
                    if (e.key === "Escape") setRenamingSheet(null);
                  }}
                  className="bg-transparent outline-none w-24 font-mono"
                  data-testid={`paste-sheet-rename-input`}
                />
              ) : (
                <>
                  <span className="max-w-[160px] truncate">{s.name}</span>
                  {canEdit && (
                    <button
                      className="ml-1.5 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground"
                      aria-label={`Duplicate ${s.name}`}
                      data-testid={`paste-sheet-duplicate-${s.sheetId}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        duplicateSheet(s.sheetId);
                      }}
                    >
                      <Copy className="h-3 w-3" />
                    </button>
                  )}
                  {canEdit && s.sheetId !== "main" && (
                    <span
                      className="ml-0.5 flex opacity-0 group-hover:opacity-100"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        className="text-muted-foreground hover:text-foreground disabled:opacity-30"
                        aria-label={`Move ${s.name} left`}
                        disabled={idx === 0}
                        onClick={() => moveSheet(s.sheetId, -1)}
                      >
                        <ChevronLeft className="h-3 w-3" />
                      </button>
                      <button
                        className="text-muted-foreground hover:text-foreground disabled:opacity-30"
                        aria-label={`Move ${s.name} right`}
                        disabled={idx === sheets.length - 1}
                        onClick={() => moveSheet(s.sheetId, 1)}
                      >
                        <ChevronRight className="h-3 w-3" />
                      </button>
                    </span>
                  )}
                  {canEdit && s.sheetId !== "main" && (
                    <button
                      className="ml-1.5 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
                      aria-label={`Delete ${s.name}`}
                      data-testid={`paste-sheet-delete-${s.sheetId}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        deleteSheet(s.sheetId);
                      }}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </>
              )}
            </div>
          );
        })}
        {canEdit && (
          <button
            onClick={createSheet}
            className="shrink-0 inline-flex items-center gap-1 px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary rounded-md"
            aria-label="Add page"
            data-testid="paste-sheet-add-button"
          >
            <span className="text-base leading-none">+</span> Page
          </button>
        )}
      </div>

      {/* Editor with inline images + line numbers + drop zone */}
      <div
        className="flex-1 overflow-auto bg-[hsl(var(--editor-bg))] relative"
        onDragEnter={canEdit ? handleDragEnter : undefined}
        onDragOver={canEdit ? handleDragOver : undefined}
        onDragLeave={canEdit ? handleDragLeave : undefined}
        onDrop={canEdit ? handleDrop : undefined}
        onPaste={canEdit ? handlePaste : undefined}
      >
        {/* Floating emoji reactions (v3.1.0) */}
        <div className="pointer-events-none absolute inset-0 z-40 overflow-hidden" data-testid="paste-reaction-layer">
          {reactions.map((r) => (
            <div
              key={r.id}
              className="lp-reaction-float absolute"
              style={{ left: `${Math.round(r.x * 100)}%` }}
            >
              <span className="lp-reaction-emoji">{r.emoji}</span>
              <span
                className="lp-reaction-name"
                style={{ backgroundColor: r.color }}
              >
                {r.name}
              </span>
            </div>
          ))}
        </div>

        {!canEdit && (
          <div
            className="absolute top-2 left-1/2 -translate-x-1/2 z-30 flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground shadow-sm"
            data-testid="paste-readonly-banner"
          >
            <EyeIcon className="h-3.5 w-3.5" /> Read-only — ask the owner for an edit link
          </div>
        )}
        {showFind && (
          <div
            className="absolute top-2 right-2 z-40 flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 shadow-md"
            data-testid="paste-find-bar"
          >
            <Search className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            <input
              autoFocus
              value={findText}
              onChange={(e) => setFindText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleReplaceAll()}
              placeholder="Find…"
              className="bg-transparent outline-none text-xs w-32 sm:w-44"
              data-testid="paste-find-input"
            />
            <button
              onClick={() => setFindCase((v) => !v)}
              className={`text-[10px] font-mono px-1 rounded ${findCase ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground"}`}
              aria-label="Match case"
              title="Match case"
            >
              Aa
            </button>
            <span className="text-[10px] text-muted-foreground tabular-nums w-10 text-center">
              {findText ? `${matchCount} hit${matchCount === 1 ? "" : "s"}` : ""}
            </span>
            <input
              value={replaceText}
              onChange={(e) => setReplaceText(e.target.value)}
              placeholder="Replace with…"
              className="bg-transparent outline-none text-xs w-32 sm:w-44 border-l border-border pl-2"
              data-testid="paste-replace-input"
            />
            <Button
              variant="outline"
              size="sm"
              className="h-6 text-[11px] px-2"
              disabled={!canEdit || !findText || matchCount === 0}
              onClick={handleReplaceAll}
              data-testid="paste-replace-all-button"
            >
              Replace all
            </Button>
            <button
              onClick={() => setShowFind(false)}
              className="text-muted-foreground hover:text-foreground"
              aria-label="Close find bar"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
        {mdPreview && (
          <div className="absolute inset-0 z-20 bg-[hsl(var(--editor-bg))] flex flex-col" data-testid="paste-markdown-preview">
            <div className="flex items-center justify-between px-4 py-2 border-b border-border text-xs text-muted-foreground">
              <span className="font-medium">Markdown preview — live</span>
              <Button variant="ghost" size="sm" onClick={() => setMdPreview(false)} aria-label="Back to editor" data-testid="paste-markdown-close">
                <X className="h-3.5 w-3.5 mr-1" /> Edit
              </Button>
            </div>
            <MarkdownView content={content} />
          </div>
        )}
        {htmlPreview && (
          <div className="absolute inset-0 z-20 bg-[hsl(var(--editor-bg))] flex flex-col" data-testid="paste-html-preview">
            <div className="flex items-center justify-between px-4 py-2 border-b border-border text-xs text-muted-foreground">
              <span className="font-medium">HTML preview — sandboxed, scripts run in isolation</span>
              <Button variant="ghost" size="sm" onClick={() => setHtmlPreview(false)} aria-label="Back to editor" data-testid="paste-html-close">
                <X className="h-3.5 w-3.5 mr-1" /> Edit
              </Button>
            </div>
            {/* sandbox="allow-scripts" without allow-same-origin: the frame gets
                a unique opaque origin — it can run JS but cannot touch this
                app's storage/cookies/DOM, and cannot make same-origin reads. */}
            <iframe
              title="HTML preview"
              className="flex-1 w-full bg-white"
              sandbox="allow-scripts allow-modals"
              srcDoc={content}
            />
          </div>
        )}
        <InlineBlocksEditor
          ref={editorApiRef}
          content={content}
          language={language}
          readOnly={!canEdit}
          placeholder="Start typing — everyone with this link sees it live. Paste or drop files right here…"
          onChange={applyContent}
          onDeleteImage={handleDeleteFile}
          onCopyImageUrl={handleCopyFileUrl}
          remoteCursors={cursorsForSheet(activeSheet)}
          onSelectionChange={sendCursor}
          runOutput={runOutput}
          onRunBlock={handleRunBlock}
          onRequestAttachFile={canEdit ? () => fileInputRef.current?.click() : undefined}
        />

        {/* History side panel */}
        {showHistory && (
          <div
            className="absolute inset-y-0 right-0 z-30 w-full max-w-sm border-l border-border bg-background/95 backdrop-blur flex flex-col shadow-xl"
            data-testid="paste-history-panel"
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <div className="flex items-center gap-2 text-sm font-medium">
                <History className="h-4 w-4 text-primary" /> Revision history
              </div>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="sm" onClick={loadRevisions} disabled={revLoading} aria-label="Refresh history">
                  {revLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setShowHistory(false)} aria-label="Close history">
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <div className="flex-1 overflow-auto p-3 space-y-2">
              {(revisions || []).length === 0 && !revLoading && (
                <p className="text-xs text-muted-foreground px-1 py-4 text-center">
                  No snapshots yet — every edit creates one automatically.
                </p>
              )}
              {(revisions || []).map((r) => (
                <div
                  key={r.rev}
                  className="flex items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2"
                  data-testid={`paste-history-row-${r.rev}`}
                >
                  <div className="min-w-0">
                    <div className="text-xs font-mono">rev {r.rev}</div>
                    <div className="text-[11px] text-muted-foreground">
                      {r.createdAt ? new Date(r.createdAt).toLocaleString() : ""} · {r.size} chars
                    </div>
                  </div>
                  {canEdit && (
                    <div className="flex items-center gap-1 shrink-0">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleDiffRevision(r.rev)}
                        className="h-7 text-xs"
                        data-testid={`paste-history-diff-${r.rev}`}
                      >
                        Diff
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleRestoreRevision(r.rev)}
                        className="h-7 text-xs"
                        data-testid={`paste-history-restore-${r.rev}`}
                      >
                        Restore
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
            {diffRev !== null && diffData && (
              <div className="border-t border-border flex flex-col" style={{ height: "45%" }}>
                <div className="flex items-center justify-between px-3 py-2 border-b border-border">
                  <span className="text-xs font-medium" data-testid="paste-diff-title">
                    rev {diffRev} → current
                  </span>
                  <Button variant="ghost" size="sm" onClick={() => { setDiffRev(null); setDiffData(null); }} aria-label="Close diff">
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
                <DiffView oldText={diffData.oldText} newText={diffData.newText} />
              </div>
            )}
          </div>
        )}

        {dragging && (
          <div
            className="absolute inset-0 z-20 flex items-center justify-center bg-background/90 border-2 border-dashed border-primary rounded-none pointer-events-none"
            data-testid="paste-drop-overlay"
          >
            <div className="flex flex-col items-center gap-2 text-primary">
              <UploadCloud className="h-8 w-8" />
              <p className="text-sm font-medium">Drop files to add them to this paste</p>
            </div>
          </div>
        )}
      </div>

      {/* Status bar */}
      <div
        className="border-t border-border bg-background px-3 sm:px-4 py-1.5 flex items-center justify-between"
        data-testid="paste-status-bar"
      >
        <span className="font-mono text-xs text-muted-foreground" data-testid="paste-status-line-count">
          {lineCount} {lineCount === 1 ? "line" : "lines"} · {charCount} chars
          {charCount > 0 ? ` · ${formatBytes(new Blob([content]).size)}` : ""}
        </span>
        <span className="font-mono text-xs text-muted-foreground hidden sm:inline">
          paste or drop any file · images, PDFs, zips, everything
        </span>
      </div>

      {/* v3.14.0 — command palette (Ctrl/Cmd+K) */}
      <CommandDialog open={paletteOpen} onOpenChange={setPaletteOpen}>
        <CommandInput placeholder="Type a command…" data-testid="palette-input" />
        <CommandList>
          <CommandEmpty>No matching command.</CommandEmpty>
          {["Pages", "Edit", "View", "Share"].map((group) => {
            const items = paletteActions.filter((a) => a.group === group && !a.disabled);
            if (!items.length) return null;
            return (
              <CommandGroup key={group} heading={group}>
                {items.map((a) => (
                  <CommandItem
                    key={a.testid}
                    onSelect={() => {
                      setPaletteOpen(false);
                      setTimeout(() => a.run(), 60);
                    }}
                    data-testid={a.testid}
                  >
                    <span className="flex-1">{a.label}</span>
                    {a.shortcut ? <CommandShortcut>{a.shortcut}</CommandShortcut> : null}
                  </CommandItem>
                ))}
              </CommandGroup>
            );
          })}
        </CommandList>
      </CommandDialog>
    </div>
  );
}
