import { getDocumentEpoch, setDocumentEpoch } from "@/lib/documentCache";
import { useEffect, useMemo, useRef, useState } from "react";
import * as Y from "yjs";

export const encodeUpdate = (update) => {
  let binary = "";
  for (const byte of update) binary += String.fromCharCode(byte);
  return btoa(binary);
};
export const decodeUpdate = (encoded) => Uint8Array.from(atob(encoded), c => c.charCodeAt(0));

/** One document per page; durable Yjs state is the retry queue, never plain text. */
export default function useCollab({ wsRef, enabled, ydocRef, docVersion = 0,
  connectionVersion = 0, sheetRef, documentsRef, documentKey = "", canEdit = false, onSyncStatus, onEpochChange, onRecovery }) {
  const fallbackDocs = useRef(new Map());
  const documents = documentsRef || fallbackDocs;
  const dirty = useRef(new Map());
  const versions = useRef(new Map());
  const rejected = useRef(new Map());
  const serverVectors = useRef(new Map());
  const inFlight = useRef(new Map());
  const initialized = useRef(false);
  const editable = useRef(canEdit);
  const sequence = useRef(0);
  const status = useRef(onSyncStatus);
  status.current = onSyncStatus;
  editable.current = canEdit;
  const [remotePulse, setRemotePulse] = useState(0);
  const ytext = useMemo(() => ydocRef.current?.getText("content") || null, [ydocRef, docVersion]);

  useEffect(() => {
    dirty.current.clear(); versions.current.clear(); rejected.current.clear(); serverVectors.current.clear(); inFlight.current.clear(); initialized.current = false;
  }, [documentKey]);

  const send = (sid) => {
    const ws = wsRef.current;
    if (!editable.current || !initialized.current || !dirty.current.get(sid) || inFlight.current.has(sid) || ws?.readyState !== WebSocket.OPEN) return;
    const doc = documents.current.get(sid);
    if (!doc || rejected.current.get(sid) === (versions.current.get(sid) || 0)) return;
    const requestId = `${connectionVersion}:${++sequence.current}`;
    const pending = { requestId, version: versions.current.get(sid) || 0, sentAt: Date.now() };
    try {
      ws.send(JSON.stringify({ type: "sync", sheetId: sid, requestId, epoch: getDocumentEpoch(documentKey, sid), stateVectorB64: encodeUpdate(Y.encodeStateVector(doc)), updateB64: encodeUpdate(Y.encodeStateAsUpdate(doc, serverVectors.current.get(sid))) }));
      inFlight.current.set(sid, pending);
      status.current?.("syncing");
    } catch {
      status.current?.("reconnecting");
    }
  };

  useEffect(() => {
    if (!enabled || !ydocRef.current) return undefined;
    const doc = ydocRef.current;
    const sid = sheetRef?.current || "main";
    documents.current.set(sid, doc);
    const changed = (_update, origin) => {
      setRemotePulse(n => n + 1);
      if (origin === "remote") return;
      versions.current.set(sid, (versions.current.get(sid) || 0) + 1);
      dirty.current.set(sid, true);
      status.current?.(editable.current ? (wsRef.current?.readyState === WebSocket.OPEN ? "syncing" : "disconnected") : "local");
    };
    doc.on("update", changed);
    const flush = setInterval(() => {
      for (const [id, pending] of inFlight.current) {
        if (Date.now() - pending.sentAt > 5000) {
          // No durable acknowledgement: resend idempotently after timeout.
          inFlight.current.delete(id);
          status.current?.("syncing");
        }
      }
      for (const id of dirty.current.keys()) send(id);
    }, 120);
    return () => { clearInterval(flush); doc.off("update", changed); };
  }, [enabled, docVersion, canEdit, connectionVersion]);

  useEffect(() => {
    if (!enabled) return undefined;
    const ws = wsRef.current;
    if (!ws) return undefined;
    initialized.current = false;
    inFlight.current.clear();
    serverVectors.current.clear();
    const getDoc = (sid) => {
      if (sid === (sheetRef?.current || "main")) documents.current.set(sid, ydocRef.current);
      if (!documents.current.has(sid)) documents.current.set(sid, new Y.Doc());
      return documents.current.get(sid);
    };
    const apply = (sid, list, epoch, authoritative = false) => {
      let doc = getDoc(sid);
      if (epoch) {
        const previous = getDocumentEpoch(documentKey, sid);
        if (previous !== epoch) {
          if (doc.getText("content").length && (previous || doc._lpLegacyCache)) {
            onRecovery?.(doc.getText("content").toString());
            doc = new Y.Doc();
            documents.current.set(sid, doc);
            if (sid === (sheetRef?.current || "main")) ydocRef.current = doc;
          }
          setDocumentEpoch(documentKey, sid, epoch);
          onEpochChange?.(sid, epoch, previous);
        }
      }
      for (const update of list) Y.applyUpdate(doc, decodeUpdate(update), "remote");
      if (authoritative) doc._lpLoaded = true;
      setRemotePulse(n => n + 1);
    };
    const receive = (event) => {
      if (wsRef.current !== ws) return;
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }
      try {
        if (msg.type === "init") {
          // init always describes MAIN, irrespective of the selected page.
          apply("main", msg.yUpdatesB64 || (msg.yStateB64 ? [msg.yStateB64] : []), msg.epoch, true);
          if (msg.stateVectorB64) serverVectors.current.set("main", decodeUpdate(msg.stateVectorB64));
          initialized.current = true;
          editable.current = !!msg.canEdit;
          if (!editable.current && typeof msg.paste?.content === "string" && getDoc("main").getText("content").toString() !== msg.paste.content) dirty.current.set("main", true);
          if (editable.current) {
            for (const sid of documents.current.keys()) { dirty.current.set(sid, true); send(sid); }
          } else status.current?.(dirty.current.size ? "local" : "connected");
          if (sheetRef?.current && sheetRef.current !== "main") ws.send(JSON.stringify({ type: "s:open", sheetId: sheetRef.current }));
        } else if (msg.type === "s:state" || msg.type === "sync-ack") {
          const sid = msg.sheetId || "main";
          apply(sid, msg.yUpdatesB64 || [], msg.epoch, true);
          if (!editable.current && typeof msg.content === "string" && getDoc(sid).getText("content").toString() !== msg.content) {
            dirty.current.set(sid, true); status.current?.("local");
          }
          if (msg.type === "sync-ack") {
            if (msg.stateVectorB64) serverVectors.current.set(sid, decodeUpdate(msg.stateVectorB64));
            const pending = inFlight.current.get(sid);
            if (pending?.requestId === msg.requestId) {
              inFlight.current.delete(sid);
              if (pending.version === (versions.current.get(sid) || 0)) dirty.current.delete(sid);
            }
            if (![...dirty.current.values()].some(Boolean) && !inFlight.current.size) status.current?.("connected");
          }
        } else if (msg.type === "yupdate" || msg.type === "s:yupdate") {
          apply(msg.type === "yupdate" ? "main" : msg.sheetId, [msg.updateB64]);
        } else if (msg.type === "restore" && msg.yUpdatesB64) {
          apply("main", msg.yUpdatesB64);
        } else if (msg.type === "error" && msg.code === "read_only") {
          editable.current = false;
          inFlight.current.clear();
          status.current?.(dirty.current.size ? "local" : "connected");
        } else if (msg.type === "error" && msg.code === "invalid_update") {
          const sid = msg.sheetId || "main";
          inFlight.current.delete(sid);
          rejected.current.set(sid, versions.current.get(sid) || 0);
          status.current?.("local");
        }
      } catch {
        status.current?.("syncing");
        // Never replace a valid local document with malformed remote state.
      }
    };
    ws.addEventListener("message", receive);
    ws._collabReady = true;
    for (const message of ws._collabInbox || []) receive({ data: JSON.stringify(message) });
    ws._collabInbox = [];
    return () => { ws._collabReady = false; ws.removeEventListener("message", receive); };
  }, [enabled, connectionVersion]);

  // A live grant starts a sync; a revocation never sends queued changes.
  useEffect(() => {
    if (canEdit && initialized.current) for (const sid of dirty.current.keys()) send(sid);
  }, [canEdit]);

  return { ytext, remotePulse };
}
