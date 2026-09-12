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
  Pencil,
  Eye as EyeIcon,
  X,
  RotateCcw,
  ArrowUpCircle,
  Share2,
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
import InlineBlocksEditor from "@/components/InlineBlocksEditor";
import useCollab from "@/hooks/useCollab";
import {
  LANGUAGES,
  API_BASE,
  WS_BASE,
  copyToClipboard,
  formatTimeLeft,
} from "@/lib/constants";
import { editTokenStore, consumeEditTokenFromUrl } from "@/lib/editToken";

const DEBOUNCE_MS = 250;
const PING_INTERVAL_MS = 25000;
const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100MB

const formatBytes = (bytes) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export default function PastePage() {
  const { slug } = useParams();
  const navigate = useNavigate();

  const [status, setStatus] = useState("loading"); // loading | ready | notfound | expired
  const [content, setContent] = useState("");
  const [language, setLanguage] = useState("plaintext");
  const [viewers, setViewers] = useState(1);
  const [views, setViews] = useState(0);
  const [expiresAt, setExpiresAt] = useState(null);
  const [timeLeft, setTimeLeft] = useState(null);
  const [connState, setConnState] = useState("connecting"); // connecting | connected | reconnecting | disconnected
  const [copiedLink, setCopiedLink] = useState(false);
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
  const [editToken, setEditToken] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [revisions, setRevisions] = useState(null); // null = not loaded
  const [docVersion, setDocVersion] = useState(0); // bump when the Y.Doc instance is swapped
  const [revLoading, setRevLoading] = useState(false);
  const [serverVersion, setServerVersion] = useState(null);
  const [latestRelease, setLatestRelease] = useState(null);
  const [updateDismissed, setUpdateDismissed] = useState(false);

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
  const activeSheetRef = useRef("main");
  const sheetYdocsRef = useRef(new Map()); // sheetId → Y.Doc for background sheets
  const pendingUpdatesRef = useRef(new Map()); // sheetId → Uint8Array[] of missed updates

  useEffect(() => {
    document.title = `/${slug} — LivePaste`;
    setEditToken(consumeEditTokenFromUrl(slug));
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
    const token = editTokenStore.get(slug);
    const ws = new WebSocket(`${WS_BASE}/api/ws/${slug}${token ? `?token=${encodeURIComponent(token)}` : ""}`);
    wsRef.current = ws;
    activeSheetRef.current = activeSheet;

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
          setCanEdit(!!msg.canEdit);
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
            // No stored CRDT state — this is a fresh sheet: seed from REST content
            const ytext = ydocRef.current.getText("content");
            if (ytext.length === 0 && contentRef.current) {
              ydocRef.current.transact(() => ytext.insert(0, contentRef.current));
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
        case "error":
          if (msg.code === "not_found") {
            closedRef.current = true;
            setStatus("notfound");
          } else if (msg.code === "expired") {
            closedRef.current = true;
            setStatus("expired");
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, connectWs]);

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
    slug,
    canEdit,
    enabled: status !== "notfound" && status !== "expired",
    ydocRef,
    docVersion,
    sheetRef: activeSheetRef,
  });

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remotePulse, status, ytext]);

  // ---- send edits over WS (CRDT deltas; full-text as periodic backup) ----
  // The backup full-text channel is sheet-scoped: `edit` only ever refers to the
  // main sheet, other sheets go through `s:edit` so main is never clobbered.
  const sendEdit = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
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

      // Reuse cached doc or spin up a fresh one
      const cached = sheetYdocsRef.current.get(sheetId);
      const nextDoc = cached || new Y.Doc();
      sheetYdocsRef.current.set(sheetId, nextDoc);
      ydocRef.current = nextDoc;
      firstYRender.current = true;
      setDocVersion((v) => v + 1); // ytext memo follows the swapped doc

      try {
        const res = await axios.get(`${API_BASE}/api/paste/${slug}/sheets/${sheetId}`);
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
    [slug],
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
      await axios.delete(`${API_BASE}/api/file/${file.id}`);
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
    if (!editToken) return;
    const ok = await copyToClipboard(`${window.location.origin + window.location.pathname}?edit=${editToken}`);
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

  const handleRestoreRevision = async (rev) => {
    try {
      const res = await axios.get(`${API_BASE}/api/paste/${slug}/revisions/${rev}`);
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
                {canEdit && editToken && (
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

            <ThemeToggle testId="paste-toolbar-theme-toggle" />
          </div>
        </div>
      </div>

      {/* Sheet tabs */}
      <div
        className="flex items-center gap-1 px-3 sm:px-4 py-1 border-b border-border bg-background overflow-x-auto"
        data-testid="paste-sheets-bar"
      >
        {sheets.map((s) => {
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
        {!canEdit && (
          <div
            className="absolute top-2 left-1/2 -translate-x-1/2 z-30 flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground shadow-sm"
            data-testid="paste-readonly-banner"
          >
            <EyeIcon className="h-3.5 w-3.5" /> Read-only — ask the owner for an edit link
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
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleRestoreRevision(r.rev)}
                      className="shrink-0 h-7 text-xs"
                      data-testid={`paste-history-restore-${r.rev}`}
                    >
                      Restore
                    </Button>
                  )}
                </div>
              ))}
            </div>
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
    </div>
  );
}
