import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
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
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ThemeToggle } from "@/components/ThemeToggle";
import InlineBlocksEditor from "@/components/InlineBlocksEditor";
import {
  LANGUAGES,
  API_BASE,
  WS_BASE,
  copyToClipboard,
  formatTimeLeft,
} from "@/lib/constants";

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
  const [uploadPct, setUploadPct] = useState(null); // null = not uploading
  const [dragging, setDragging] = useState(false);

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

  useEffect(() => {
    document.title = `/${slug} — LivePaste`;
  }, [slug]);

  // ---- initial REST load (handles view counting once per session) ----
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const viewedKey = `lp_viewed_${slug}`;
        const alreadyViewed = sessionStorage.getItem(viewedKey);
        const res = await axios.get(`${API_BASE}/api/paste/${slug}`, {
          params: { count_view: alreadyViewed ? false : true },
        });
        if (cancelled) return;
        sessionStorage.setItem(viewedKey, "1");
        const p = res.data;
        setContent(p.content);
        contentRef.current = p.content;
        setLanguage(p.language || "plaintext");
        setViews(p.views || 0);
        setExpiresAt(p.expiresAt);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        setStatus("notfound");
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [slug]);

  // ---- WebSocket connection with auto-reconnect ----
  const connectWs = useCallback(() => {
    if (closedRef.current) return;
    const ws = new WebSocket(`${WS_BASE}/api/ws/${slug}`);
    wsRef.current = ws;

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
          setContent(msg.paste.content);
          contentRef.current = msg.paste.content;
          setLanguage(msg.paste.language || "plaintext");
          setViews(msg.paste.views || 0);
          setExpiresAt(msg.paste.expiresAt);
          setViewers(msg.viewers || 1);
          break;
        case "edit":
          setContent(msg.content);
          contentRef.current = msg.content;
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
    if (status !== "ready") return undefined;
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

  // ---- send edits over WS ----
  const sendEdit = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "edit", content: contentRef.current }));
    }
  }, []);

  const applyContent = useCallback(
    (newContent) => {
      setContent(newContent);
      contentRef.current = newContent;
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(sendEdit, DEBOUNCE_MS);
    },
    [sendEdit],
  );

  const handleChange = (newContent) => {
    applyContent(newContent);
  };

  const handleLanguageChange = (lang) => {
    setLanguage(lang);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "language", language: lang }));
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
    const ok = await copyToClipboard(window.location.href);
    if (ok) {
      toast.success("Link copied to clipboard");
      setCopiedLink(true);
      setTimeout(() => setCopiedLink(false), 1600);
    } else {
      toast.error("Could not copy link");
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

  return (
    <div className="h-screen flex flex-col bg-background">
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
            <Button
              variant="outline"
              size="sm"
              onClick={handleCopyLink}
              data-testid="paste-toolbar-copy-link-button"
              className="shrink-0 active:scale-[0.98]"
              aria-label="Copy link"
            >
              {copiedLink ? <Check className="h-3.5 w-3.5 sm:mr-1.5" /> : <Link2 className="h-3.5 w-3.5 sm:mr-1.5" />}
              <span className="hidden sm:inline">{copiedLink ? "Copied" : "Copy link"}</span>
            </Button>
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
              onClick={() => fileInputRef.current?.click()}
              data-testid="paste-toolbar-add-file-button"
              className="shrink-0 active:scale-[0.98]"
              aria-label="Add file"
              disabled={uploadPct !== null}
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
            <Select value={language} onValueChange={handleLanguageChange}>
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

      {/* Editor with inline images + line numbers + drop zone */}
      <div
        className="flex-1 overflow-auto bg-[hsl(var(--editor-bg))] relative"
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onPaste={handlePaste}
      >
        <InlineBlocksEditor
          ref={editorApiRef}
          content={content}
          language={language}
          placeholder="Start typing — everyone with this link sees it live. Paste or drop files right here…"
          onChange={applyContent}
          onDeleteImage={handleDeleteFile}
          onCopyImageUrl={handleCopyFileUrl}
        />

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
