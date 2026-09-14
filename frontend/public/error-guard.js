// Global error guard (kept external so the CSP `script-src 'self'` policy holds).
// Suppresses a benign Safari DataCloneError noise from PerformanceServerTiming.
window.addEventListener(
  "error",
  function (e) {
    if (
      e.error instanceof DOMException &&
      e.error.name === "DataCloneError" &&
      e.message &&
      e.message.includes("PerformanceServerTiming")
    ) {
      e.stopImmediatePropagation();
      e.preventDefault();
    }
  },
  true,
);
