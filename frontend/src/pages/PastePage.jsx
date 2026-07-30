import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import Editor from "react-simple-code-editor";
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
  ImagePlus,
  Trash2,
  ExternalLink,
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
import { highlightCode } from "@/lib/prismSetup";
import {
  LANGUAGES,
  API_BASE,
  WS_BASE,
  copyToClipboard,
  formatTimeLeft,
} from "@/lib/constants";

const DEBOUNCE_MS = 250;
const PING_INTERVAL_MS = 25000;
const MAX_IMAGE_SIZE = 100 * 1024 * 1024; // 100MB
const IMG_TOKEN_RE = /!\[([^\]]*)\]\(([^)\s]*\/api\/image\/([a-fA-F0-9]{24}))\)/g;

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
  const editorWrapRef = useRef(null);
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

  // ---- images: parse inline refs ----
  const images = useMemo(() => {
    const found = [];
    const seen = new Set();
    let m;
    const re = new RegExp(IMG_TOKEN_RE.source, "g");
    while ((m = re.exec(content)) !== null) {
      if (!seen.has(m[3])) {
        seen.add(m[3]);
        found.push({ name: m[1] || "image", url: m[2], id: m[3], token: m[0] });
      }
    }
    return found;
  }, [content]);

  // ---- images: insert token at cursor ----
  const insertAtCursor = useCallback(
    (text) => {
      const ta = editorWrapRef.current?.querySelector("textarea");
      const current = contentRef.current;
      let pos = current.length;
      if (ta && typeof ta.selectionStart === "number") {
        pos = ta.selectionStart;
      }
      const before = current.slice(0, pos);
      const after = current.slice(pos);
      const prefix = before && !before.endsWith("\n") ? "\n" : "";
      const suffix = after.startsWith("\n") || after === "" ? "\n" : "\n";
      const inserted = `${prefix}${text}${suffix}`;
      const newContent = before + inserted + after;
      applyContent(newContent);
      requestAnimationFrame(() => {
        try {
          const newPos = pos + inserted.length;
          ta?.setSelectionRange(newPos, newPos);
        } catch (e) {
          /* ignore */
        }
      });
    },
    [applyContent],
  );

  // ---- images: upload ----
  const uploadImage = useCallback(
    async (file) => {
      if (!file) return;
      if (!file.type.startsWith("image/")) {
        toast.error(`"${file.name}" is not an image`);
        return;
      }
      if (file.size > MAX_IMAGE_SIZE) {
        toast.error(`"${file.name}" is over the 100MB limit`);
        return;
      }
      const form = new FormData();
      form.append("file", file);
      setUploadPct(0);
      try {
        const res = await axios.post(`${API_BASE}/api/paste/${slug}/image`, form, {
          onUploadProgress: (e) => {
            if (e.total) setUploadPct(Math.round((e.loaded / e.total) * 100));
          },
        });
        const { id, name } = res.data;
        const safeName = (name || "image").replace(/[[\]()]/g, "_");
        insertAtCursor(`![${safeName}](${API_BASE}/api/image/${id})`);
        toast.success(`Image "${name}" added`);
      } catch (err) {
        const msg = err?.response?.data?.detail || "Image upload failed";
        toast.error(msg);
      } finally {
        setUploadPct(null);
      }
    },
    [slug, insertAtCursor],
  );

  const uploadFiles = useCallback(
    async (files) => {
      const list = Array.from(files || []);
      if (!list.length) return;
      for (const f of list) {
        // eslint-disable-next-line no-await-in-loop
        await uploadImage(f);
      }
    },
    [uploadImage],
  );

  // ---- images: paste from clipboard ----
  const handlePaste = useCallback(
    (e) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      const imageFiles = [];
      for (const item of items) {
        if (item.kind === "file" && item.type.startsWith("image/")) {
          const f = item.getAsFile();
          if (f) imageFiles.push(f);
        }
      }
      if (imageFiles.length) {
        e.preventDefault();
        uploadFiles(imageFiles);
      }
    },
    [uploadFiles],
  );

  // ---- images: drag & drop ----
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

  // ---- images: delete ----
  const handleDeleteImage = async (img) => {
    // Remove every occurrence of this image's token from the text
    const re = new RegExp(
      `!\\[[^\\]]*\\]\\([^)\\s]*\\/api\\/image\\/${img.id}\\)\\n?`,
      "g",
    );
    const newContent = contentRef.current.replace(re, "");
    applyContent(newContent);
    try {
      await axios.delete(`${API_BASE}/api/image/${img.id}`);
      toast.success(`Image "${img.name}" deleted`);
    } catch (err) {
      toast.error("Could not delete image file (reference removed)");
    }
  };

  const handleCopyImageUrl = async (img) => {
    const ok = await copyToClipboard(`${API_BASE}/api/image/${img.id}`);
    if (ok) toast.success("Image URL copied");
    else toast.error("Could not copy URL");
  };

  const handleCopyLink = async () => {
    const ok = await copyToClipboard(window.location.href);
    if (ok) {
      toast.success("Link copied to clipboard");
      setCopiedLink(true);
      setTimeout(() => setCopiedLink(false), 900);
    } else {
      toast.error("Could not copy link");
    }
  };

  const handleCopyContent = async () => {
    const ok = await copyToClipboard(contentRef.current);
    if (ok) {
      toast.success("Content copied to clipboard");
      setCopiedContent(true);
      setTimeout(() => setCopiedContent(false), 900);
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
              data-testid="paste-toolbar-add-image-button"
              className="shrink-0 active:scale-[0.98]"
              aria-label="Add image"
              disabled={uploadPct !== null}
            >
              <ImagePlus className="h-3.5 w-3.5 sm:mr-1.5" />
              <span className="hidden sm:inline">Add image</span>
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              data-testid="paste-image-file-input"
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

      {/* Editor with line numbers + drop zone */}
      <div
        className="flex-1 overflow-auto bg-[hsl(var(--editor-bg))] relative"
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <div className="flex min-h-full w-max min-w-full">
          <div
            className="lp-gutter sticky left-0 z-10 shrink-0 select-none text-right bg-[hsl(var(--editor-gutter))] text-muted-foreground border-r border-border"
            aria-hidden="true"
            data-testid="paste-line-numbers"
          >
            {Array.from({ length: lineCount }, (_, i) => (
              <div key={i}>{i + 1}</div>
            ))}
          </div>
          <div
            className="lp-editor-wrap flex-1"
            data-testid="paste-live-editor"
            ref={editorWrapRef}
            onPaste={handlePaste}
          >
            <Editor
              value={content}
              onValueChange={handleChange}
              highlight={(code) => highlightCode(code, language)}
              padding={20}
              textareaClassName="code-input"
              placeholder="Start typing — everyone with this link sees it live. Paste or drop screenshots right here…"
              style={{
                minHeight: "calc(100vh - 130px)",
                color: "hsl(var(--editor-fg))",
                background: "transparent",
              }}
            />
          </div>
        </div>

        {dragging && (
          <div
            className="absolute inset-0 z-20 flex items-center justify-center bg-background/90 border-2 border-dashed border-primary rounded-none pointer-events-none"
            data-testid="paste-drop-overlay"
          >
            <div className="flex flex-col items-center gap-2 text-primary">
              <UploadCloud className="h-8 w-8" />
              <p className="text-sm font-medium">Drop images to add them to this paste</p>
            </div>
          </div>
        )}
      </div>

      {/* Attachments strip */}
      {images.length > 0 && (
        <div
          className="border-t border-border bg-card px-3 sm:px-4 py-2"
          data-testid="paste-attachments-strip"
        >
          <div className="flex items-center gap-3 overflow-x-auto">
            <span className="text-xs text-muted-foreground font-medium shrink-0">
              Images ({images.length})
            </span>
            {images.map((img) => (
              <div
                key={img.id}
                className="flex items-center gap-2 border border-border rounded-lg bg-background px-2 py-1.5 shrink-0"
                data-testid={`paste-attachment-${img.id}`}
              >
                <a href={`${API_BASE}/api/image/${img.id}`} target="_blank" rel="noreferrer">
                  <img
                    src={`${API_BASE}/api/image/${img.id}`}
                    alt={img.name}
                    className="h-12 w-12 object-cover rounded-md border border-border bg-muted"
                    loading="lazy"
                  />
                </a>
                <span className="font-mono text-xs max-w-[120px] truncate" title={img.name}>
                  {img.name}
                </span>
                <div className="flex items-center">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    aria-label={`Open ${img.name}`}
                    onClick={() => window.open(`${API_BASE}/api/image/${img.id}`, "_blank")}
                    data-testid={`paste-attachment-open-${img.id}`}
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    aria-label={`Copy URL of ${img.name}`}
                    onClick={() => handleCopyImageUrl(img)}
                    data-testid={`paste-attachment-copy-${img.id}`}
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-destructive hover:text-destructive"
                    aria-label={`Delete ${img.name}`}
                    onClick={() => handleDeleteImage(img)}
                    data-testid={`paste-attachment-delete-${img.id}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

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
          paste or drop images · Ctrl+V screenshots supported
        </span>
      </div>
    </div>
  );
}
