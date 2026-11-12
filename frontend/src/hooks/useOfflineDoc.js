import { offlineCacheKey, getDocumentEpoch } from "@/lib/documentCache";
import { useEffect, useState } from "react";
import * as Y from "yjs";
import { IndexeddbPersistence } from "y-indexeddb";

/**
 * Offline-first persistence for a paste's Y.Doc.
 *
 * Every CRDT update is mirrored into IndexedDB keyed by `<slug>::<sheetId>`,
 * so a paste (and any offline edits) survives reloads and lost connectivity.
 * When the WebSocket reconnects, useCollab flushes the queued updates and the
 * server merges them — offline edits auto-merge via Yjs semantics.
 *
 * `docVersion` must bump whenever the Y.Doc instance is swapped (paste load /
 * sheet switch) so the persistence follows the right doc.
 */
export function useOfflineDoc({ slug, ydocRef, docVersion, sheetRef, enabled }) {
  const [offlineSynced, setOfflineSynced] = useState(false);

  useEffect(() => {
    if (!enabled || !slug || !ydocRef.current) return undefined;
    const doc = ydocRef.current;
    const sid = sheetRef ? sheetRef.current : "main";
    const idb = new IndexeddbPersistence(offlineCacheKey(slug, sid), doc);
    setOfflineSynced(false);
    idb.on("synced", () => setOfflineSynced(true));
    return () => {
      try {
        idb.destroy();
      } catch {
        /* ignore */
      }
    };
  }, [slug, ydocRef, docVersion, sheetRef, enabled]);

  return { offlineSynced };
}

/**
 * Checks whether a locally persisted copy exists for `slug::sheetId` — used to
 * distinguish "server restarted & wiped the paste" from a genuinely dead link
 * (v3.4.0 reconnect-after-restart rescue).
 */
export async function hasOfflineDoc(slug, sheetId = "main") {
  try {
    const text = await readOfflineDoc(slug, sheetId, 1200);
    return Boolean(text && text.length > 0);
  } catch {
    return false;
  }
}

/**
 * Reads the locally persisted text for `slug::sheetId` without touching the
 * network — used for the offline cold start (server unreachable, paste cached).
 */
export async function readOfflineDoc(slug, sheetId = "main", timeoutMs = 2500, epoch) {
  const doc = new Y.Doc();
  const idb = new IndexeddbPersistence(offlineCacheKey(slug, sheetId, epoch), doc);
  try {
    await new Promise((resolve) => {
      const t = setTimeout(resolve, timeoutMs);
      idb.on("synced", () => {
        clearTimeout(t);
        resolve();
      });
    });
    return doc.getText("content").toString();
  } finally {
    try { await idb.destroy(); } catch { /* unavailable storage */ }
    doc.destroy();
  }
}

export async function readOfflineState(slug, sheetId = "main", timeoutMs = 2500, epoch) {
  const doc = new Y.Doc();
  const persistence = new IndexeddbPersistence(offlineCacheKey(slug, sheetId, epoch), doc);
  let timer;
  try {
    await Promise.race([persistence.whenSynced, new Promise(resolve => { timer = setTimeout(resolve, timeoutMs); })]);
    return getDocumentEpoch(slug, sheetId) || Y.encodeStateVector(doc).length > 1 ? Y.encodeStateAsUpdate(doc) : null;
  } finally {
    clearTimeout(timer);
    await persistence.destroy();
    doc.destroy();
  }
}

/** Tracks browser online/offline state for the offline indicator. */
export function useOnlineStatus() {
  const [online, setOnline] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine,
  );
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  return online;
}

// Keep an upload's original document durable even if its editor unmounts.
export function retainOfflineDoc(slug, sheetId, doc) {
  if (typeof indexedDB === "undefined") return null;
  try { return new IndexeddbPersistence(offlineCacheKey(slug, sheetId), doc); }
  catch { return null; }
}
