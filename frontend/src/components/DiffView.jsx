import { useMemo } from "react";

/**
 * Minimal line-level diff for revision history (v3.12.0).
 *
 * Longest Common Subsequence on lines. Revisions are capped at 400KB and the
 * history panel shows one diff at a time, so O(n*m) here stays tiny
 * (400KB worst case is rare; typical pastes are a few KB).
 */
export function diffLines(oldText, newText) {
  const a = (oldText || "").split("\n");
  const b = (newText || "").split("\n");
  const n = a.length;
  const m = b.length;

  // Guard rail: skip LCS for pathological sizes, fall back to replace-all
  if (n * m > 4_000_000) {
    return [
      ...a.map((l) => ({ type: "del", text: l })),
      ...b.map((l) => ({ type: "add", text: l })),
    ];
  }

  // LCS table
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const out = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ type: "same", text: a[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ type: "del", text: a[i] });
      i += 1;
    } else {
      out.push({ type: "add", text: b[j] });
      j += 1;
    }
  }
  while (i < n) {
    out.push({ type: "del", text: a[i] });
    i += 1;
  }
  while (j < m) {
    out.push({ type: "add", text: b[j] });
    j += 1;
  }
  return out;
}

export default function DiffView({ oldText, newText }) {
  const rows = useMemo(() => diffLines(oldText, newText), [oldText, newText]);
  const adds = rows.filter((r) => r.type === "add").length;
  const dels = rows.filter((r) => r.type === "del").length;

  return (
    <div className="flex-1 overflow-auto font-mono text-[11px] leading-4" data-testid="paste-diff-view">
      <div className="sticky top-0 bg-background/95 px-2 py-1 border-b border-border text-[11px] text-muted-foreground">
        <span className="text-green-600 dark:text-green-400">+{adds} added</span>
        {" · "}
        <span className="text-red-600 dark:text-red-400">-{dels} removed</span>
      </div>
      {rows.map((r, idx) => {
        if (r.type === "same") {
          return (
            <div key={idx} className="px-2 text-muted-foreground/60 whitespace-pre-wrap break-all">
              {"  "}{r.text}
            </div>
          );
        }
        const isAdd = r.type === "add";
        return (
          <div
            key={idx}
            className={`px-2 whitespace-pre-wrap break-all ${
              isAdd
                ? "bg-green-500/10 text-green-700 dark:text-green-300"
                : "bg-red-500/10 text-red-700 dark:text-red-300"
            }`}
          >
            {isAdd ? "+" : "-"} {r.text}
          </div>
        );
      })}
    </div>
  );
}
