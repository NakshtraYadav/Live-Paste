const memoryEpochs = new Map();
const keyFor = (slug, sid) => `lp_doc_epoch_${slug}_${sid}`;
export function getDocumentEpoch(slug, sid = "main") {
  const key = keyFor(slug, sid);
  try { return localStorage.getItem(key) || memoryEpochs.get(key) || ""; }
  catch { return memoryEpochs.get(key) || ""; }
}
export function setDocumentEpoch(slug, sid, epoch) {
  if (!/^[a-f0-9]{32}$/.test(epoch || "")) return;
  const key = keyFor(slug, sid);
  memoryEpochs.set(key, epoch);
  try { localStorage.setItem(key, epoch); } catch { /* memory-only browser */ }
}
export function offlineCacheKey(slug, sid = "main", epoch = getDocumentEpoch(slug, sid)) {
  return epoch ? `lp-v2:${slug}:${epoch}::${sid}` : `${slug}::${sid}`;
}
