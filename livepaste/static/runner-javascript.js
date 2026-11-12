
self.onmessage = async (e) => {
  const { code, timeoutMs } = e.data;
  const logs = [];
  const fmt = (v, depth = 0) => {
    if (typeof v === "string") return depth === 0 ? v : JSON.stringify(v);
    if (v === undefined) return "undefined";
    if (v === null) return "null";
    if (typeof v === "function") return "[Function " + (v.name || "anonymous") + "]";
    if (v instanceof Error) return v.stack || String(v);
    if (Array.isArray(v)) {
      if (depth > 3) return "[...]";
      return "[" + v.slice(0, 100).map((x) => fmt(x, depth + 1)).join(", ") + "]";
    }
    if (typeof v === "object") {
      if (depth > 3) return "{...}";
      try {
        return "{ " + Object.entries(v).slice(0, 100).map(([k, x]) => k + ": " + fmt(x, depth + 1)).join(", ") + " }";
      } catch { return String(v); }
    }
    return String(v);
  };
  const push = (level, args) => {
    try { if (logs.length < 500) logs.push({ level, text: args.map((a) => fmt(a)).join(" ").slice(0, 10000) }); } catch {}
  };
  const console = {
    log: (...a) => push("log", a),
    info: (...a) => push("info", a),
    warn: (...a) => push("warn", a),
    error: (...a) => push("error", a),
    debug: (...a) => push("debug", a),
    table: (...a) => push("log", a),
  };
  const timer = setTimeout(() => {
    self.postMessage({ ok: false, logs, error: "Execution timed out after " + timeoutMs + "ms" });
    self.close();
  }, timeoutMs);
  try {
    // Direct eval inside this function: user code sees the console shim, and
    // eval returns the completion value of the last expression (REPL feel).
    const fn = new Function("console", "code", "return eval(code)");
    const result = await fn(console, code);
    clearTimeout(timer);
    let out = "";
    if (result !== undefined) out = "⇒ " + fmt(result);
    self.postMessage({ ok: true, logs, result: out });
  } catch (err) {
    clearTimeout(timer);
    const message = err && err.message ? err.message : String(err);
    logs.push({ level: "error", text: (err && err.stack) || message });
    self.postMessage({ ok: false, logs, error: message });
  }
};
