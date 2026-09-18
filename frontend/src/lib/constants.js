export const LANGUAGES = [
  { value: "plaintext", label: "Plain text" },
  { value: "javascript", label: "JavaScript" },
  { value: "typescript", label: "TypeScript" },
  { value: "jsx", label: "JSX (React)" },
  { value: "tsx", label: "TSX (React)" },
  { value: "python", label: "Python" },
  { value: "java", label: "Java" },
  { value: "c", label: "C" },
  { value: "cpp", label: "C++" },
  { value: "csharp", label: "C#" },
  { value: "go", label: "Go" },
  { value: "rust", label: "Rust" },
  { value: "ruby", label: "Ruby" },
  { value: "php", label: "PHP" },
  { value: "bash", label: "Bash / Shell" },
  { value: "json", label: "JSON" },
  { value: "yaml", label: "YAML" },
  { value: "markdown", label: "Markdown" },
  { value: "sql", label: "SQL" },
  { value: "css", label: "CSS" },
  { value: "markup", label: "HTML / XML" },
  { value: "kotlin", label: "Kotlin" },
  { value: "swift", label: "Swift" },
];

export const EXPIRY_OPTIONS = [
  { value: "never", label: "Never expires" },
  { value: "1h", label: "Expires in 1 hour" },
  { value: "1d", label: "Expires in 1 day" },
  { value: "1w", label: "Expires in 1 week" },
];

// Backend base URL. When VITE_BACKEND_URL is not set at build time
// (self-hosted / packaged mode), fall back to the same origin the app is
// served from — API calls become relative and WebSockets use the page host.
export const API_BASE = import.meta.env.VITE_BACKEND_URL || "";

export const WS_BASE = API_BASE
  ? API_BASE.replace(/^http/, "ws")
  : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export const copyToClipboard = async (text) => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "0";
      ta.style.left = "-9999px";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      ta.setSelectionRange(0, ta.value.length);
      const copied = document.execCommand("copy");
      document.body.removeChild(ta);
      return copied;
    } catch {
      return false;
    }
  }
};

export const formatTimeLeft = (expiresAt) => {
  if (!expiresAt) return null;
  const diff = new Date(expiresAt).getTime() - Date.now();
  if (diff <= 0) return "Expired";
  const mins = Math.floor(diff / 60000);
  const days = Math.floor(mins / 1440);
  const hours = Math.floor((mins % 1440) / 60);
  const m = mins % 60;
  if (days > 0) return `${days}d ${hours}h left`;
  if (hours > 0) return `${hours}h ${m}m left`;
  if (mins >= 1) return `${m}m left`;
  return "<1m left";
};
