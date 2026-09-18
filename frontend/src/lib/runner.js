/**
 * Sandboxed code execution for Runnable Pastes.
 *
 * - JavaScript runs in a dedicated Web Worker with no DOM/network imports
 *   beyond fetch (kept — it's the same power the page has), a hard timeout,
 *   and captured console output. The worker has no access to the app's
 *   state, tokens, or localStorage.
 * - Python runs in a separate Pyodide worker loaded lazily from the CDN the
 *   first time a Python block is run (cached by the browser afterwards).
 *
 * Both runners communicate over a tiny promise-based API and never block
 * the editor thread.
 */

// ---------------- JS runner ----------------

const JS_WORKER_SRC = `
self.onmessage = (e) => {
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
      return "[" + v.map((x) => fmt(x, depth + 1)).join(", ") + "]";
    }
    if (typeof v === "object") {
      if (depth > 3) return "{...}";
      try {
        return "{ " + Object.entries(v).map(([k, x]) => k + ": " + fmt(x, depth + 1)).join(", ") + " }";
      } catch { return String(v); }
    }
    return String(v);
  };
  const push = (level, args) => {
    try { logs.push({ level, text: args.map((a) => fmt(a)).join(" ") }); } catch {}
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
    const result = fn(console, code);
    clearTimeout(timer);
    let out = "";
    if (result !== undefined) out = "⇒ " + fmt(result);
    self.postMessage({ ok: true, logs, result: out });
  } catch {
    clearTimeout(timer);
    logs.push({ level: "error", text: (err && err.stack) || String(err) });
    self.postMessage({ ok: false, logs, error: (err && err.message) || String(err) });
  }
};
`;

let jsWorkerUrl = null;

function runJavaScript(code, timeoutMs = 5000) {
  return new Promise((resolve) => {
    if (!jsWorkerUrl) {
      jsWorkerUrl = URL.createObjectURL(new Blob([JS_WORKER_SRC], { type: "text/javascript" }));
    }
    let worker;
    try {
      worker = new Worker(jsWorkerUrl);
    } catch {
      resolve({ ok: false, logs: [], error: "Could not start the sandbox worker" });
      return;
    }
    const logs = [];
    const timer = setTimeout(() => {
      worker.terminate();
      resolve({ ok: false, logs, error: "Execution timed out" });
    }, timeoutMs + 1000);
    worker.onmessage = (e) => {
      clearTimeout(timer);
      worker.terminate();
      resolve({ ...e.data, logs: [...(e.data.logs || [])] });
    };
    worker.onerror = (e) => {
      clearTimeout(timer);
      worker.terminate();
      resolve({ ok: false, logs, error: e.message || "Worker error" });
    };
    worker.postMessage({ code, timeoutMs });
  });
}

// ---------------- Python runner (Pyodide) ----------------

const PY_WORKER_SRC = `
let pyodide = null;
let loading = null;

async function ensurePyodide() {
  if (pyodide) return pyodide;
  if (!loading) {
    importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");
    loading = loadPyodide({ indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/" });
  }
  pyodide = await loading;
  return pyodide;
}

self.onmessage = async (e) => {
  const { id, code } = e.data;
  const logs = [];
  const push = (level, args) => logs.push({ level, text: args.map((a) => String(a)).join(" ") });
  try {
    const py = await ensurePyodide();
    py.setStdout({ batched: (s) => push("log", [s]) });
    py.setStderr({ batched: (s) => push("error", [s]) });
    let result = await py.runPythonAsync(code);
    if (result === undefined || result === null) result = "";
    self.postMessage({ id, ok: true, logs, result: result && result.toString ? String(result) : "" });
  } catch {
    self.postMessage({ id, ok: false, logs, error: String(err.message || err) });
  }
};
`;

let pyWorker = null;
let pySeq = 0;
const pyPending = new Map();

function getPyWorker() {
  if (pyWorker) return pyWorker;
  const blob = new Blob([PY_WORKER_SRC], { type: "text/javascript" });
  pyWorker = new Worker(URL.createObjectURL(blob));
  pyWorker.onmessage = (e) => {
    const { id } = e.data;
    const pending = pyPending.get(id);
    if (pending) {
      pyPending.delete(id);
      pending(e.data);
    }
  };
  return pyWorker;
}

function runPython(code, timeoutMs = 30000) {
  return new Promise((resolve) => {
    let worker;
    try {
      worker = getPyWorker();
    } catch {
      resolve({ ok: false, logs: [], error: "Could not start the Python sandbox" });
      return;
    }
    const id = (pySeq += 1);
    const timer = setTimeout(() => {
      pyPending.delete(id);
      // A hung Pyodide can't be interrupted safely — restart the worker.
      try { worker.terminate(); } catch { /* ignore */ }
      pyWorker = null;
      resolve({ ok: false, logs: [], error: "Execution timed out" });
    }, timeoutMs);
    pyPending.set(id, (data) => {
      clearTimeout(timer);
      resolve(data);
    });
    worker.postMessage({ id, code });
  });
}

// ---------------- public API ----------------

const JS_HINTS = /(^|\n)\s*(const |let |var |function |=>|console\.|return )/;

export function detectLanguageOf(text) {
  const t = (text || "").trim();
  if (/^\s*(def |import |print\(|from )/m.test(t)) return "python";
  if (JS_HINTS.test(t) || /;\s*$/m.test(t)) return "javascript";
  return null;
}

export function runnerFor(language) {
  if (language === "python") return runPython;
  if (language === "javascript" || language === "js" || language === "typescript") return runJavaScript;
  return null;
}

export const runInSandbox = (language, code) => {
  const runner = runnerFor(language);
  if (!runner) return Promise.resolve({ ok: false, logs: [], error: `No runner for ${language}` });
  return runner(code);
};

export const PYTHON_READY_HINT = "First run downloads the Python runtime (~10 MB, cached after that).";
