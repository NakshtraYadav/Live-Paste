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


let jsWorkerUrl = null;

function runJavaScript(code, timeoutMs = 5000) {
  return new Promise((resolve) => {
    jsWorkerUrl = "/runner-javascript.js";
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


let pyWorker = null;
let pySeq = 0;
const pyPending = new Map();

function getPyWorker() {
  if (pyWorker) return pyWorker;
  pyWorker = new Worker("/runner-python.js");
  pyWorker.onerror = (event) => {
    for (const settle of pyPending.values()) settle({ ok: false, logs: [], error: event.message || "Python worker failed" });
    pyPending.clear();
    pyWorker?.terminate();
    pyWorker = null;
  };
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
      for (const [otherId, settle] of pyPending) {
        settle({ id: otherId, ok: false, logs: [], error: "Python worker restarted after a timeout" });
      }
      pyPending.clear();
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
