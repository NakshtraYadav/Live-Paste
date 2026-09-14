import { useEffect, useMemo, useRef, useState } from "react";
import * as Y from "yjs";
import { WS_BASE } from "@/lib/constants";

/**
 * Bridges a Yjs doc over LivePaste's existing WebSocket protocol.
 *
 * Wire format (server side, see livepaste/core.py):
 *   → { type: "yupdate", updateB64 }        CRDT update relay (editors only)
 *   ← { type: "yupdate", updateB64 }        fan-out to the whole room
 *   ← { type: "init", yUpdatesB64: [...] }  server's stored update list on join
 *   ← { type: "s:state", yUpdatesB64 }      per-sheet update list (handled in PastePage)
 *
 * Local typing applies Y.Text deltas to `ytext`; remote updates land in the
 * same ytext. The editor binding maps the Y.Text to per-block textareas so the
 * block UI stays identical.
 *
 * `docVersion` bumps whenever the underlying Y.Doc instance is swapped
 * (paste change / sheet switch) so the memoized ytext follows it.
 *
 * `sheetRef` holds the active sheet id: edits on the implicit "main" sheet are
 * relayed as plain `yupdate` messages, edits on any other sheet as sheet-scoped
 * `s:yupdate` messages — and incoming plain `yupdate`s are only applied while
 * "main" is the active sheet, so multi-sheet docs never cross-contaminate.
 */
export default function useCollab({ wsRef, slug, canEdit, enabled, ydocRef, docVersion = 0, sheetRef }) {
  const ytext = useMemo(
    () => (ydocRef.current ? ydocRef.current.getText("content") : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ydocRef, docVersion],
  );
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
      for (const { sid, update } of list) {
        // Each queued update carries the sheet it was typed on. Stamping at
        // QUEUE time (not flush time) is critical: a sheet switch within the
        // 120ms coalescing window used to re-label page-1 edits onto the new
        // page, making fresh pages inherit the previous page's content.
        const msg = sid === "main" ? { type: "yupdate" } : { type: "s:yupdate", sheetId: sid };
        try {
          ws.send(JSON.stringify({ ...msg, updateB64: encode(update) }));
        } catch (e) {
          /* ignore */
        }
      }
    };

    const onUpdate = (update, origin) => {
      // origin === null → local transaction; relay it so peers merge our delta
      if (origin !== null) return;
      const sid = sheetRef ? sheetRef.current : "main";
      pendingRef.current.push({ sid, update });
      flush();
    };
    doc.on("update", onUpdate);

    // Periodic flush keeps coalescing cheap while typing fast
    const iv = setInterval(flush, 120);
    return () => {
      clearInterval(iv);
      doc.off("update", onUpdate);
    };
  }, [enabled, wsRef, ydocRef, docVersion]);

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
      if (msg.type === "init" && Array.isArray(msg.yUpdatesB64) && msg.yUpdatesB64.length) {
        let applied = 0;
        for (const b64 of msg.yUpdatesB64) if (applyB64(b64)) applied += 1;
        if (applied) setRemotePulse((n) => n + 1);
      } else if (msg.type === "init" && msg.yStateB64) {
        // Backward compat with an older single-state payload
        if (applyB64(msg.yStateB64)) setRemotePulse((n) => n + 1);
      } else if (msg.type === "yupdate" && msg.updateB64) {
        // Plain relays belong to the main sheet only
        if ((!sheetRef || sheetRef.current === "main") && applyB64(msg.updateB64)) {
          setRemotePulse((n) => n + 1);
        }
      } else if (
        msg.type === "restore" &&
        msg.content != null &&
        (!sheetRef || sheetRef.current === "main")
      ) {
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
  }, [enabled, wsRef, ydocRef, docVersion, ytext]);

  return { ytext, remotePulse };
}
