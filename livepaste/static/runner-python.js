
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
  } catch (err) {
    const message = err && err.message ? err.message : String(err);
    self.postMessage({ id, ok: false, logs, error: message });
  }
};
