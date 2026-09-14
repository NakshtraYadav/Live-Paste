import { useMemo } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";

/**
 * Live markdown preview (v3.10.0).
 *
 * Renders the paste content as sanitized HTML. The sanitizer strips scripts,
 * event handlers and javascript: URLs — the paste is collaborative text from
 * untrusted humans, so this boundary is non-negotiable.
 */
export default function MarkdownView({ content }) {
  const html = useMemo(() => {
    const raw = marked.parse(content || "", {
      gfm: true,
      breaks: true,
    });
    return DOMPurify.sanitize(raw, {
      FORBID_TAGS: ["style", "form", "input", "iframe"],
      FORBID_ATTR: ["style"],
    });
  }, [content]);

  return (
    <div
      className="lp-markdown flex-1 overflow-auto px-6 py-4 text-sm leading-relaxed
        [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mt-4 [&_h1]:mb-2
        [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:mt-4 [&_h2]:mb-2
        [&_h3]:text-base [&_h3]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1.5
        [&_p]:my-2 [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:my-2
        [&_ol]:list-decimal [&_ol]:pl-6 [&_ol]:my-2
        [&_li]:my-0.5 [&_a]:text-primary [&_a]:underline
        [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_blockquote]:my-2
        [&_code]:bg-secondary [&_code]:rounded [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_code]:font-mono
        [&_pre]:bg-secondary [&_pre]:rounded-md [&_pre]:p-3 [&_pre]:overflow-x-auto [&_pre]:my-2
        [&_pre_code]:bg-transparent [&_pre_code]:p-0
        [&_hr]:border-border [&_hr]:my-4
        [&_table]:border-collapse [&_table]:my-2 [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1
        [&_img]:max-w-full [&_img]:rounded-md"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
