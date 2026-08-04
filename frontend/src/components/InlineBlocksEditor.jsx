import React, {
  useMemo,
  useRef,
  useCallback,
  forwardRef,
  useImperativeHandle,
} from "react";
import Editor from "react-simple-code-editor";
import axios from "axios";
import { ExternalLink, Copy, Trash2 } from "lucide-react";
import { highlightCode } from "@/lib/prismSetup";
import { API_BASE } from "@/lib/constants";

// A line that is exactly one image token, e.g. ![name](https://.../api/image/<id>)
const IMG_LINE_RE = /^\s*!\[([^\]]*)\]\(([^)\s]*\/api\/image\/([a-fA-F0-9]{24}))\)\s*$/;

/**
 * Parse content into an alternating list of blocks:
 *   [text, image, text, image, ..., text]
 * Text blocks: { type: "text", value: string | null }  (null = zero lines)
 * Image blocks: { type: "image", raw, name, url, id }
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
    const m = line.match(IMG_LINE_RE);
    if (m) {
      flushText();
      blocks.push({
        type: "image",
        raw: line,
        name: m[1] || "image",
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
    if (b.type === "image") lines.push(b.raw);
    else if (b.value !== null) lines.push(...b.value.split("\n"));
  }
  return lines.join("\n");
}

const lineCountOf = (block) => {
  if (block.type === "image") return 1;
  if (block.value === null) return 0;
  return block.value.split("\n").length;
};

const InlineBlocksEditor = forwardRef(function InlineBlocksEditor(
  { content, language, placeholder, onChange, onDeleteImage, onCopyImageUrl },
  ref,
) {
  const blocks = useMemo(() => parseBlocks(content), [content]);
  const rowRefs = useRef({});
  const focusRef = useRef(null); // { index, sel }

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

  // ---- imperative API: insert an image token at the current caret ----
  useImperativeHandle(ref, () => ({
    insertImageToken(token) {
      const m = token.match(IMG_LINE_RE);
      if (!m) return;
      const imgBlock = {
        type: "image",
        raw: token,
        name: m[1] || "image",
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
          imgBlock,
          afterBlock,
          ...blocks.slice(f.index + 1),
        ];
        focusIndex = f.index + 2;
      } else {
        // Append at the end of the document
        const last = blocks[blocks.length - 1];
        if (blocks.length === 1 && (last.value === "" || last.value === null)) {
          next = [{ type: "text", value: null }, imgBlock, { type: "text", value: "" }];
        } else {
          next = [...blocks, imgBlock, { type: "text", value: "" }];
        }
        focusIndex = next.length - 1;
      }
      commit(next);
      focusTextAt(focusIndex, 0);
    },
  }));

  // ---- delete an image block by its position; clean up file if orphaned ----
  const removeImageBlockAt = useCallback(
    (index) => {
      const img = blocks[index];
      if (!img || img.type !== "image") return;
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
      // If the image no longer appears anywhere, delete the stored file
      if (!newContent.includes(`/api/image/${img.id}`)) {
        axios.delete(`${API_BASE}/api/image/${img.id}`).catch(() => {});
      }
      focusTextAt(index - 1, caretPos);
    },
    [blocks, onChange, focusTextAt],
  );

  // ---- per-textarea handlers ----
  const trackSelection = (index) => (e) => {
    focusRef.current = { index, sel: e.target.selectionStart ?? 0 };
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
      removeImageBlockAt(index - 1);
      return;
    }
    if (e.key === "Delete" && atEnd && index < blocks.length - 1) {
      e.preventDefault();
      removeImageBlockAt(index + 1);
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

        if (block.type === "image") {
          return (
            <div className="lp-block-row" key={`img-${block.id}-${index}`}>
              <div
                className="lp-gutter-cell"
                style={{ width: gutterWidth }}
                aria-hidden="true"
              >
                <div>{startLine}</div>
              </div>
              <div className="lp-image-cell flex-1">
                <div
                  className="lp-inline-image group"
                  data-testid={`paste-inline-image-${block.id}`}
                >
                  <img
                    src={block.url}
                    alt={block.name}
                    loading="lazy"
                    draggable={false}
                  />
                  <div className="lp-image-actions opacity-0 group-hover:opacity-100">
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
                      title="Copy image URL"
                      onClick={() => onCopyImageUrl(block)}
                      data-testid={`paste-inline-image-copy-${block.id}`}
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      className="lp-danger"
                      aria-label={`Delete ${block.name}`}
                      title="Delete image"
                      onClick={() => onDeleteImage(block)}
                      data-testid={`paste-inline-image-delete-${block.id}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          );
        }

        // Zero-line text block: slim click-to-type zone between/around images
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
              <Editor
                value={block.value}
                onValueChange={handleBlockChange(index)}
                highlight={(code) => highlightCode(code, language)}
                padding={0}
                textareaClassName="code-input"
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
