import { useEffect, useMemo, useRef, useState } from "react";
import * as Y from "yjs";
import { WS_BASE } from "@/lib/constants";

/**
 * Bridges a Yjs doc over LivePaste's existing WebSocket protocol.
 *
 * Wire format (server side, see livepaste/core.py):
 *   → { type: "yupdate", updateB64 }   CRDT update relay (editors only)
 *   ← { type: "yupdate", updateB64 }   fan-out to the whole room
 *   ← { type: "init", yStateB64 }      server's merged state on join
 *
 * Local typing applies Y.Text deltas to `ytext`; remote updates land in the
 * same ytext. `editorBinding` (see InlineBlocksEditor) maps the Y.Text to
 * per-block textareas so the block UI stays identical.
 */
export default function useCollab({ wsRef, slug, canEdit, enabled, ydocRef }) {
  const ytext = useMemo(() => (ydocRef.current ? ydocRef.current.getText("content") : null), [ydocRef]);
  const pendingRef = useRef([]);
  const [remotePulse, setRemotePulse] = useState(0);

  useEffect(() => {
    if (!enabled || !ydocRef.current) return undefined;
    const doc = ydocRef.current;

    const encode = (u) => {
      let s = "";
      for (const b of u) s += String.fromCharCode(b);
      return btoa(s);
    };

    const flush = () => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const list = pendingRef.current;
      pendingRef.current = [];
      for (const u of list) {
        try {
          ws.send(JSON.stringify({ type: "yupdate", updateB64: encode(u) }));
        } catch (e) {
          /* ignore */
        }
      }
    };

    const onUpdate = (update, origin) => {
      // origin === null → local transaction; relay it
      if (origin !== null) return;
      pendingRef.current.push(update);
      flush();
    };
    doc.on("update", onUpdate);

    // Periodic flush keeps coalescing cheap while typing fast
    const iv = setInterval(flush, 120);
    return () => {
      clearInterval(iv);
      doc.off("update", onUpdate);
    };
  }, [enabled, wsRef, ydocRef]);

  // Handle server messages: initial state + relays
  useEffect(() => {
    if (!enabled || !ydocRef.current) return undefined;
    const doc = ydocRef.current;

    const applyB64 = (b64) => {
      try {
        const bin = atob(b64);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
        Y.applyUpdate(doc, bytes, "remote");
        return true;
      } catch (e) {
        return false;
      }
    };

    const onMessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      if (msg.type === "init" && msg.yStateB64) {
        applyB64(msg.yStateB64);
        setRemotePulse((n) => n + 1);
      } else if (msg.type === "yupdate" && msg.updateB64) {
        if (applyB64(msg.updateB64)) setRemotePulse((n) => n + 1);
      } else if (msg.type === "restore" && msg.content != null) {
        // A revision restore replaced the canonical text
        doc.transact(() => {
          ytext.delete(0, ytext.length);
          ytext.insert(0, msg.content);
        }, "restore");
        setRemotePulse((n) => n + 1);
      }
    };
    const ws = wsRef.current;
    if (!ws) return undefined;
    ws.addEventListener("message", onMessage);
    return () => ws.removeEventListener("message", onMessage);
  }, [enabled, wsRef, ydocRef, slug]);

  const relayPending = () => {
    const doc = ydocRef.current;
    const ws = wsRef.current;
    if (!doc || !ws || ws.readyState !== WebSocket.OPEN) return;
    const sv = Y.encodeStateVector(doc);
    let s = "";
    for (const b of sv) s += String.fromCharCode(b);
    try {
      ws.send(JSON.stringify({ type: "yupdate", updateB64: btoa(s) }));
    } catch (e) {
      /* ignore */
    }
  };

  return { ytext, relayPending, remotePulse };
}
