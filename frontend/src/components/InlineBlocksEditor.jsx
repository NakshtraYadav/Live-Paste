import React, {
  useMemo,
  useRef,
  useCallback,
  forwardRef,
  useImperativeHandle,
} from "react";
import Editor from "react-simple-code-editor";
import axios from "axios";
import { ExternalLink, Copy, Trash2, File, Download } from "lucide-react";import { highlightCode } from "@/lib/prismSetup";
import { API_BASE } from "@/lib/constants";
import { detectLanguageOf } from "@/lib/runner";

// A line that is exactly one file token:
//   ![name](https://.../api/image/<24-hex>)   (legacy)
//   ![name](https://.../api/file/<24-hex>)    (any file type)
const IMG_LINE_RE = /^\s*!\[([^\]]*)\]\(([^)\s]*\/api\/image\/([a-fA-F0-9]{24}))\)\s*$/;
const FILE_LINE_RE = /^\s*!\[([^\]]*)\]\(([^)\s]*\/api\/file\/([a-fA-F0-9]{24}))\)\s*$/;

// Extensions/basenames that should be previewed as an image
const IMAGE_EXT_RE = /\.(png|jpe?g|gif|webp|bmp|svg|avif|ico|heic|heif)$/i;

export const isImageName = (name) => {
  const n = (name || "").split("?")[0];
  return IMAGE_EXT_RE.test(n);
};

// Uppercased extension badge, e.g. "PDF", "EXE", "VYB"; "BIN" when none
export const extOf = (name) => {
  const n = (name || "").split("?")[0];
  const m = n.match(/\.([A-Za-z0-9]{1,12})$/);
  return m ? m[1].toUpperCase() : "BIN";
};

const fileIconColor = (name) => {
  const n = (name || "").toLowerCase();
  if (/\.(zip|tar|gz|7z|rar|bz2|xz)$/.test(n)) return "#f59e0b"; // archives — amber
  if (/\.(mp3|wav|ogg|flac|m4a|aac)$/.test(n)) return "#8b5cf6"; // audio — violet
  if (/\.(mp4|mkv|mov|avi|webm)$/.test(n)) return "#ec4899"; // video — pink
  if (/\.(pdf)$/.test(n)) return "#ef4444"; // pdf — red
  if (/\.(docx?|odt|rtf|pages)$/.test(n)) return "#3b82f6"; // docs — blue
  if (/\.(xlsx?|csv|numbers)$/.test(n)) return "#22c55e"; // sheets — green
  if (/\.(pptx?|key|odp)$/.test(n)) return "#f97316"; // slides — orange
  if (/\.(json|ya?ml|xml|csv|tsv|env|ini|toml|log|txt|md)$/.test(n)) return "#06b6d4"; // text data — cyan
  return "hsl(var(--muted-foreground))";
};

const formatBytes = (bytes) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

/**
 * Parse content into an alternating list of blocks:
 *   [text, file, text, file, ..., text]
 * Text blocks: { type: "text", value: string | null }  (null = zero lines)
 * File blocks: { type: "image" | "file", raw, name, url, id }
 * parse -> join is lossless.
 */
export function parseBlocks(content) {
  const lines = (content || "").split("\n");
  const blocks = [];
  let buf = null;
  const flushText = () => {
    blocks.push({ type: "text", value: buf === null ? null : buf.join("\n") });
    buf = null;
  };
  for (const line of lines) {
    const m = line.match(FILE_LINE_RE) || line.match(IMG_LINE_RE);
    if (m) {
      flushText();
      blocks.push({
        type: m[0].includes("/api/image/") ? "image" : "file",
        raw: line,
        name: m[1] || "file",
        url: m[2],
        id: m[3],
      });
    } else {
      if (buf === null) buf = [];
      buf.push(line);
    }
  }
  flushText();
  return blocks;
}

export function blocksToContent(blocks) {
  const lines = [];
  for (const b of blocks) {
    if (b.type === "image" || b.type === "file") lines.push(b.raw);
    else if (b.value !== null) lines.push(...b.value.split("\n"));
  }
  return lines.join("\n");
}

const isFileBlock = (b) => b.type === "image" || b.type === "file";

const lineCountOf = (block) => {
  if (isFileBlock(block)) return 1;
  if (block.value === null) return 0;
  return block.value.split("\n").length;
};

const InlineBlocksEditor = forwardRef(function InlineBlocksEditor(
  { content, language, placeholder, onChange, onDeleteImage, onCopyImageUrl, readOnly, remoteCursors, onSelectionChange, runOutput, onRunBlock },
  ref,
) {
  const blocks = useMemo(() => parseBlocks(content), [content]);
  const rowRefs = useRef({});
  const focusRef = useRef(null); // { index, sel }

  // ---- remote cursors: map plain-text offsets to (blockIndex, caretPos) ----
  const cursorMap = useMemo(() => {
    const map = {}; // blockIndex -> [{ name, color, caretPos, selStart, selEnd }]
    if (!remoteCursors || !remoteCursors.length) return map;
    // Char offsets of each block's first character in the joined content —
    // mirrors blocksToContent(): files contribute their raw line, text blocks
    // their value, null blocks nothing; blocks are joined with "\n".
    const starts = [];
    let acc = 0;
    for (const b of blocks) {
      starts.push(acc);
      if (isFileBlock(b)) acc += (b.raw?.length || 0) + 1;
      else if (b.value !== null) acc += b.value.length + 1;
    }
    const total = Math.max(acc - 1, 0);
    for (const cur of remoteCursors) {
      const head = Math.min(Math.max(cur.head, 0), total);
      const anchor = Math.min(Math.max(cur.anchor, 0), total);
      let bi = 0;
      for (let i = 0; i < blocks.length; i += 1) {
        if (head >= starts[i]) bi = i;
        else break;
      }
      const pos = head - starts[bi];
      const isText = !isFileBlock(blocks[bi]);
      let ai = 0;
      for (let i = 0; i < blocks.length; i += 1) {
        if (anchor >= starts[i]) ai = i;
        else break;
      }
      const aPos = anchor - starts[ai];
      if (!map[bi]) map[bi] = [];
      map[bi].push({
        name: cur.name,
        color: cur.color,
        caretPos: isText ? pos : 0,
        inNullZone: !isText,
        selStart: ai === bi && aPos <= pos ? aPos : null,
        selEnd: ai === bi && aPos <= pos ? pos : null,
        selReverse: ai === bi && aPos > pos ? { start: pos, end: aPos } : null,
      });
    }
    return map;
  }, [remoteCursors, blocks]);

  const totalLines = useMemo(
    () => blocks.reduce((n, b) => n + lineCountOf(b), 0) || 1,
    [blocks],
  );
  const gutterWidth = Math.max(52, 26 + String(totalLines).length * 9);

  const getTextarea = (index) =>
    rowRefs.current[index]?.querySelector("textarea") || null;

  const focusTextAt = useCallback((index, pos) => {
    // Defer until React committed the new blocks
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const ta = getTextarea(index);
        if (ta) {
          ta.focus();
          const p = pos === "end" ? ta.value.length : pos;
          try {
            ta.setSelectionRange(p, p);
          } catch (e) {
            /* ignore */
          }
          focusRef.current = { index, sel: p === "end" ? ta.value.length : p };
        }
      });
    });
  }, []);

  const commit = useCallback(
    (newBlocks) => {
      onChange(blocksToContent(newBlocks));
    },
    [onChange],
  );

  // Materialize a null text block into an editable empty line, then focus it
  const materializeAndFocus = useCallback(
    (index) => {
      const next = blocks.map((b, i) =>
        i === index && b.type === "text" && b.value === null
          ? { ...b, value: "" }
          : b,
      );
      commit(next);
      focusTextAt(index, 0);
    },
    [blocks, commit, focusTextAt],
  );

  // ---- imperative API: insert a file/image token at the current caret ----
  useImperativeHandle(ref, () => ({
    insertImageToken(token) {
      const m = token.match(FILE_LINE_RE) || token.match(IMG_LINE_RE);
      if (!m) return;
      const fileBlock = {
        type: m[0].includes("/api/image/") ? "image" : "file",
        raw: token,
        name: m[1] || "file",
        url: m[2],
        id: m[3],
      };
      const f = focusRef.current;
      let next;
      let focusIndex;
      if (
        f &&
        blocks[f.index] &&
        blocks[f.index].type === "text" &&
        typeof f.sel === "number"
      ) {
        const v = blocks[f.index].value ?? "";
        const sel = Math.min(f.sel, v.length);
        const before = v.slice(0, sel);
        const after = v.slice(sel);
        const beforeBlock = {
          type: "text",
          value: before === "" ? null : before,
        };
        const afterBlock = { type: "text", value: after };
        next = [
          ...blocks.slice(0, f.index),
          beforeBlock,
          fileBlock,
          afterBlock,
          ...blocks.slice(f.index + 1),
        ];
        focusIndex = f.index + 2;
      } else {
        // Append at the end of the document
        const last = blocks[blocks.length - 1];
        if (blocks.length === 1 && (last.value === "" || last.value === null)) {
          next = [{ type: "text", value: null }, fileBlock, { type: "text", value: "" }];
        } else {
          next = [...blocks, fileBlock, { type: "text", value: "" }];
        }
        focusIndex = next.length - 1;
      }
      commit(next);
      focusTextAt(focusIndex, 0);
    },
    insertFileToken(token) {
      // Alias — same behavior, clearer name for non-image files
      return this.insertImageToken(token);
    },
  }));

  // ---- delete a file block by its position; clean up file if orphaned ----
  const removeFileBlockAt = useCallback(
    (index) => {
      const blk = blocks[index];
      if (!isFileBlock(blk)) return;
      // Merge surrounding text blocks (they always exist by construction)
      const prev = blocks[index - 1];
      const nextB = blocks[index + 1];
      const mergedValue =
        prev.value === null && nextB.value === null
          ? null
          : `${prev.value ?? ""}${prev.value !== null && nextB.value !== null ? "\n" : ""}${nextB.value ?? ""}`;
      const caretPos = (prev.value ?? "").length;
      const next = [
        ...blocks.slice(0, index - 1),
        { type: "text", value: mergedValue },
        ...blocks.slice(index + 2),
      ];
      const newContent = blocksToContent(next);
      onChange(newContent);
      // If the file no longer appears anywhere, delete the stored file
      if (
        !newContent.includes(`/api/file/${blk.id}`) &&
        !newContent.includes(`/api/image/${blk.id}`)
      ) {
        axios
          .delete(blk.url.startsWith("http") ? blk.url : `${API_BASE}${blk.url}`)
          .catch(() => {});
      }
      focusTextAt(index - 1, caretPos);
    },
    [blocks, onChange, focusTextAt],
  );

  // ---- per-textarea handlers ----
  const trackSelection = (index) => (e) => {
    const ta = e.target;
    focusRef.current = { index, sel: ta.selectionStart ?? 0 };
    if (onSelectionChange) {
      // Report my absolute plain-text offset so peers can draw my caret
      // (same accounting as blocksToContent: raw/value lengths + separators)
      let offset = 0;
      for (let i = 0; i < index; i += 1) {
        const b = blocks[i];
        if (isFileBlock(b)) offset += (b.raw?.length || 0) + 1;
        else if (b.value !== null) offset += b.value.length + 1;
      }
      onSelectionChange(offset + (ta.selectionStart ?? 0), offset + (ta.selectionEnd ?? 0));
    }
  };

  const handleKeyDown = (index) => (e) => {
    const ta = e.target;
    const v = ta.value;
    const s = ta.selectionStart;
    const en = ta.selectionEnd;
    const atStart = s === 0 && en === 0;
    const atEnd = s === v.length && en === v.length;
    const onFirstLine = !v.slice(0, s).includes("\n");
    const onLastLine = !v.slice(en).includes("\n");

    if (e.key === "Backspace" && atStart && index > 0) {
      e.preventDefault();
      removeFileBlockAt(index - 1);
      return;
    }
    if (e.key === "Delete" && atEnd && index < blocks.length - 1) {
      e.preventDefault();
      removeFileBlockAt(index + 1);
      return;
    }
    if ((e.key === "ArrowUp" && onFirstLine) || (e.key === "ArrowLeft" && atStart)) {
      if (index > 0) {
        e.preventDefault();
        const target = index - 2;
        if (blocks[target]?.value === null) materializeAndFocus(target);
        else focusTextAt(target, "end");
      }
      return;
    }
    if ((e.key === "ArrowDown" && onLastLine) || (e.key === "ArrowRight" && atEnd)) {
      if (index < blocks.length - 1) {
        e.preventDefault();
        const target = index + 2;
        if (blocks[target]?.value === null) materializeAndFocus(target);
        else focusTextAt(target, 0);
      }
    }
  };

  const handleBlockChange = (index) => (newValue) => {
    const next = blocks.map((b, i) =>
      i === index ? { ...b, value: newValue } : b,
    );
    commit(next);
  };

  // ---- remote caret chip (name tag above a colored caret) ----
  const caretChip = (cur, i) => (
    <span
      key={`${cur.name}-${i}`}
      className="lp-remote-caret-label"
      style={{ backgroundColor: cur.color }}
    >
      {cur.name}
    </span>
  );

  // Map a plain-text offset inside `value` to (line, column) for positioning.
  const lineStartsOf = (value) => {
    const starts = [0];
    for (let k = 0; k < value.length; k += 1) {
      if (value[k] === "\n") starts.push(k + 1);
    }
    return starts;
  };
  const caretXY = (value, pos) => {
    if (!value) return { line: 0, col: 0 };
    const starts = lineStartsOf(value);
    let li = 0;
    for (let i = 0; i < starts.length; i += 1) {
      if (pos >= starts[i]) li = i;
      else break;
    }
    return { line: li, col: pos - starts[li] };
  };

  // ---- remote selection highlight strips for a text block ----
  const selectionOverlays = (list, blockValue) =>
    list.map((cur, i) => {
      const s = cur.selReverse ? cur.selReverse.start : cur.selStart;
      const e2 = cur.selReverse ? cur.selReverse.end : cur.selEnd;
      if (s == null || e2 == null || s === e2 || !blockValue) return null;
      const lineStarts = lineStartsOf(blockValue);
      const strips = [];
      for (let li = 0; li < lineStarts.length; li += 1) {
        const ls = lineStarts[li];
        const le = li + 1 < lineStarts.length ? lineStarts[li + 1] - 1 : blockValue.length;
        const a = Math.max(s, ls);
        const b = Math.min(e2, le);
        if (b > a) strips.push({ top: li * 22.275, left: a - ls, width: b - a });
      }
      return strips.map((st, j) => (
        <span
          key={`${cur.name}-sel-${i}-${j}`}
          className="lp-remote-selection"
          style={{ backgroundColor: cur.color, top: st.top, left: st.left * 8.1, width: Math.max(st.width * 8.1, 4) }}
        />
      ));
    });

  // ---- render: a file block as an image preview or a file card ----
  const renderFileBlock = (block, index, startLine) => {
    const previewAsImage =
      block.type === "image" || isImageName(block.name);
    // Media previews (v2.7.0): video files, audio files and PDFs render
    // inline instead of a bare download card.
    const lower = (block.name || "").toLowerCase();
    const previewKind = previewAsImage
      ? "image"
      : /\.(mp4|webm|mov|mkv)$/.test(lower)
        ? "video"
        : /\.(mp3|wav|ogg|m4a|flac|aac)$/.test(lower)
          ? "audio"
          : /\.pdf$/.test(lower)
            ? "pdf"
            : null;
    const fileCursors = cursorMap[index] || [];

    return (
      <div className="lp-block-row" key={`${block.type}-${block.id}-${index}`}>
        <div
          className="lp-gutter-cell"
          style={{ width: gutterWidth }}
          aria-hidden="true"
        >
          <div>{startLine}</div>
        </div>
        <div className="lp-image-cell flex-1">
          {fileCursors.map((cur, i) => (
            <span
              key={`fc-${cur.name}-${i}`}
              className="lp-remote-caret"
              style={{
                backgroundColor: cur.color,
                left: 20 + i * 2,
                top: 6,
              }}
            >
              {caretChip(cur, i)}
            </span>
          ))}
          {previewKind === "video" && (
            <video
              className="lp-inline-media"
              src={block.url}
              controls
              preload="metadata"
              playsInline
              data-testid={`paste-inline-video-${block.id}`}
            />
          )}
          {previewKind === "pdf" && (
            <object
              className="lp-inline-pdf"
              data={block.url}
              type="application/pdf"
              aria-label={`PDF preview of ${block.name}`}
              data-testid={`paste-inline-pdf-${block.id}`}
            >
              <iframe src={block.url} title={block.name} />
            </object>
          )}
          {previewAsImage ? (
            <div
              className="lp-inline-image group"
              data-testid={`paste-inline-image-${block.id}`}
            >
              <img
                src={block.url}
                alt={block.name}
                loading="lazy"
                draggable={false}
              />                  <div className={`lp-image-actions opacity-0 group-hover:opacity-100 ${readOnly ? "hidden" : ""}`}>
                <button
                  type="button"
                  aria-label={`Open ${block.name}`}
                  title="Open full size"
                  onClick={() => window.open(block.url, "_blank")}
                  data-testid={`paste-inline-image-open-${block.id}`}
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  aria-label={`Copy URL of ${block.name}`}
                  title="Copy file URL"
                  onClick={() => onCopyImageUrl(block)}
                  data-testid={`paste-inline-image-copy-${block.id}`}
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  className="lp-danger"
                  aria-label={`Delete ${block.name}`}
                  title="Delete file"
                  onClick={() => onDeleteImage(block)}
                  data-testid={`paste-inline-image-delete-${block.id}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ) : (
            <div
              className="lp-inline-file group"
              data-testid={`paste-inline-file-${block.id}`}
            >
              {previewKind === "audio" && (
                <audio
                  controls
                  preload="metadata"
                  src={block.url}
                  className="lp-inline-audio w-full mb-2"
                  data-testid={`paste-inline-audio-${block.id}`}
                />
              )}
              <span
                className="lp-file-icon"
                style={{ color: fileIconColor(block.name) }}
                aria-hidden="true"
              >
                <File className="h-5 w-5" />
              </span>
              <div className="lp-file-meta min-w-0">
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="lp-file-name truncate">{block.name}</span>
                  <span
                    className="lp-file-ext shrink-0"
                    style={{ color: fileIconColor(block.name) }}
                  >
                    {extOf(block.name)}
                  </span>
                </div>
                <span className="lp-file-url truncate">{block.url}</span>
              </div>
              <div className={`lp-image-actions lp-file-actions ${readOnly ? "hidden" : ""}`}>
                <button
                  type="button"
                  aria-label={`Open ${block.name}`}
                  title="Open in new tab"
                  onClick={() => window.open(block.url, "_blank")}
                  data-testid={`paste-inline-file-open-${block.id}`}
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                </button>
                <a
                  href={block.url}
                  download={block.name}
                  aria-label={`Download ${block.name}`}
                  title="Download"
                  className="lp-file-download"
                  data-testid={`paste-inline-file-download-${block.id}`}
                >
                  <Download className="h-3.5 w-3.5" />
                </a>
                <button
                  type="button"
                  aria-label={`Copy URL of ${block.name}`}
                  title="Copy file URL"
                  onClick={() => onCopyImageUrl(block)}
                  data-testid={`paste-inline-file-copy-${block.id}`}
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  className="lp-danger"
                  aria-label={`Delete ${block.name}`}
                  title="Delete file"
                  onClick={() => onDeleteImage(block)}
                  data-testid={`paste-inline-file-delete-${block.id}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  // ---- render ----
  let lineNo = 1;
  const isSingleEmptyDoc = blocks.length === 1;

  return (
    <div className="lp-blocks min-w-full w-max flex flex-col min-h-full" data-testid="paste-live-editor">
      {/* top spacer */}
      <div className="lp-block-row" style={{ height: 14 }}>
        <div className="lp-gutter-cell" style={{ width: gutterWidth }} />
        <div className="flex-1" />
      </div>

      {blocks.map((block, index) => {
        const startLine = lineNo;
        const n = lineCountOf(block);
        lineNo += n;

        if (isFileBlock(block)) {
          return renderFileBlock(block, index, startLine);
        }

        // Zero-line text block: slim click-to-type zone between/around files
        if (block.value === null) {
          return (
            <div className="lp-block-row" key={`null-${index}`}>
              <div className="lp-gutter-cell" style={{ width: gutterWidth }} />
              <button
                type="button"
                className="lp-null-zone flex-1"
                aria-label="Click to type here"
                data-testid={`paste-insert-zone-${index}`}
                onClick={() => materializeAndFocus(index)}
              >
                <span className="lp-null-hint">click to type here</span>
              </button>
            </div>
          );
        }

        const isLast = index === blocks.length - 1;
        const RUNNABLE_SHEET = { javascript: true, js: true, typescript: true, python: true };
        const runnable =
          !!onRunBlock &&
          typeof block.value === "string" &&
          block.value.trim().length > 0 &&
          (RUNNABLE_SHEET[language] || !!detectLanguageOf(block.value));
        const showRun = runOutput && runOutput.blockIndex === index;
        return (
          <div
            className={`lp-block-row ${isLast ? "flex-1" : ""}`}
            key={`txt-${index}`}
          >
            <div
              className="lp-gutter-cell"
              style={{ width: gutterWidth }}
              aria-hidden="true"
            >
              {Array.from({ length: n }, (_, i) => (
                <div key={i}>{startLine + i}</div>
              ))}
            </div>
            {runnable && (
              <button
                type="button"
                className="lp-run-button"
                title="Run this block in a sandbox"
                aria-label="Run block"
                data-testid={`paste-run-button-${index}`}
                onClick={() => onRunBlock(index)}
              >
                {showRun && runOutput.status === "running" ? (
                  <span className="lp-run-spinner" aria-hidden="true" />
                ) : (
                  "▶"
                )}
                Run
              </button>
            )}
            <div
              className="lp-block-text flex-1"
              ref={(el) => {
                rowRefs.current[index] = el;
              }}
              onMouseDown={(e) => {
                // Clicking empty space below the last block focuses its end
                if (isLast && e.target === e.currentTarget) {
                  e.preventDefault();
                  focusTextAt(index, "end");
                }
              }}
            >
              {(cursorMap[index] || []).map((cur, i) =>
                cur.inNullZone ? null : (
                  <span
                    key={`rc-${cur.name}-${i}`}
                    className="lp-remote-caret"
                    style={{
                      backgroundColor: cur.color,
                      top: caretXY(block.value, cur.caretPos).line * 22.275 + 6,
                      left: 20 + caretXY(block.value, cur.caretPos).col * 8.1,
                    }}
                  >
                    {caretChip(cur, i)}
                  </span>
                ),
              )}
              {selectionOverlays(cursorMap[index] || [], block.value)}
              <Editor
                value={block.value}
                onValueChange={readOnly ? undefined : handleBlockChange(index)}
                highlight={(code) => highlightCode(code, language)}
                padding={0}
                textareaClassName="code-input"
                readOnly={readOnly || undefined}
                placeholder={
                  isSingleEmptyDoc
                    ? placeholder
                    : undefined
                }
                onFocus={trackSelection(index)}
                onClick={trackSelection(index)}
                onKeyUp={trackSelection(index)}
                onKeyDown={handleKeyDown(index)}
                style={{
                  minHeight: 23,
                  color: "hsl(var(--editor-fg))",
                  background: "transparent",
                }}
              />
              {showRun && (
                <pre
                  className={`lp-run-output ${runOutput.status === "error" ? "lp-run-error" : ""}`}
                  data-testid={`paste-run-output-${index}`}
                >
                  {runOutput.output || (runOutput.status === "running" ? "Running…" : "(no output)")}
                </pre>
              )}
            </div>
          </div>
        );
      })}

      {/* bottom filler keeps the gutter column continuous */}
      <div className="lp-block-row" style={{ minHeight: 40 }}>
        <div className="lp-gutter-cell" style={{ width: gutterWidth }} />
        <div
          className="flex-1"
          onMouseDown={(e) => {
            e.preventDefault();
            const lastIdx = blocks.length - 1;
            if (blocks[lastIdx]?.value === null) materializeAndFocus(lastIdx);
            else focusTextAt(lastIdx, "end");
          }}
        />
      </div>
    </div>
  );
});

export default InlineBlocksEditor;
