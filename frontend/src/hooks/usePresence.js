import { useEffect, useRef, useState } from "react";
import { getIdentity, colorForPeer } from "@/lib/identity";

/**
 * Presence + live cursors over LivePaste's existing WebSocket.
 *
 * Wire format (server side, see livepaste/core.py):
 *   → { type: "hello", i: {clientId,name,color,initials,sheetId} }
 *   → { type: "cursor", c: {clientId, sheetId, anchor, head} }   (editors only)
 *   ← { type: "peers", p: [peer…] }                              reply to hello
 *   ← { type: "peer-joined", p }   /  ← { type: "peer-left", clientId }
 *   ← { type: "cursor", c }                                      relay
 *
 * Cursor offsets are plain indices into the ACTIVE SHEET's plain text —
 * everyone in the room sees the same block order, so they line up. Good
 * enough for Google-Docs-style colored carets without heavier machinery.
 *
 * `connState` re-runs the effect whenever the socket reconnects so the
 * hello handshake is replayed on the new socket.
 */
export default function usePresence({
  wsRef,
  slug,
  enabled,
  connState, // eslint-disable-line no-unused-vars — re-handshake trigger
  canEdit,
  sheetRef,
}) {
  const [peers, setPeers] = useState([]); // [{clientId,name,color,initials,sheetId}]
  const [cursors, setCursors] = useState({}); // clientId -> {sheetId, anchor, head, ts}
  const peersRef = useRef(new Map()); // clientId -> meta (source of truth)
  const cursorsRef = useRef({});

  const commitPeers = () => setPeers(Array.from(peersRef.current.values()));

  useEffect(() => {
    if (!enabled || !wsRef.current) return undefined;
    const ws = wsRef.current;
    const me = getIdentity();
    const cursorsTimers = {};

    // Drop stale cursors (peers who stopped sending) after 15s
    const sweep = () => {
      const now = Date.now();
      let dirty = false;
      for (const [cid, cur] of Object.entries(cursorsRef.current)) {
        if (now - cur.ts > 15000) {
          delete cursorsRef.current[cid];
          delete cursorsTimers[cid];
          dirty = true;
        }
      }
      if (dirty) setCursors({ ...cursorsRef.current });
    };
    const sweepIv = setInterval(sweep, 5000);

    const onOpen = () => {
      try {
        ws.send(
          JSON.stringify({
            type: "hello",
            i: {
              clientId: me.clientId,
              name: me.name,
              color: me.color,
              initials: me.initials,
              sheetId: sheetRef ? sheetRef.current : "main",
            },
          }),
        );
      } catch (e) {
        /* ignore */
      }
    };

    const onMessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      if (msg.type === "peers" && Array.isArray(msg.p)) {
        for (const p of msg.p) {
          if (p && p.clientId && p.clientId !== me.clientId) {
            peersRef.current.set(p.clientId, p);
          }
        }
        commitPeers();
      } else if (msg.type === "peer-joined" && msg.p && msg.p.clientId) {
        if (msg.p.clientId !== me.clientId) {
          peersRef.current.set(msg.p.clientId, msg.p);
          commitPeers();
        }
      } else if (msg.type === "peer-left" && msg.clientId) {
        peersRef.current.delete(msg.clientId);
        delete cursorsRef.current[msg.clientId];
        delete cursorsTimers[msg.clientId];
        commitPeers();
        setCursors({ ...cursorsRef.current });
      } else if (msg.type === "cursor" && msg.c && msg.c.clientId) {
        const c = msg.c;
        if (c.clientId === me.clientId) return;
        cursorsRef.current[c.clientId] = {
          sheetId: c.sheetId || "main",
          anchor: Number(c.anchor) || 0,
          head: Number(c.head) || Number(c.anchor) || 0,
          ts: Date.now(),
        };
        setCursors({ ...cursorsRef.current });
        clearTimeout(cursorsTimers[c.clientId]);
        cursorsTimers[c.clientId] = setTimeout(() => {
          delete cursorsRef.current[c.clientId];
          setCursors({ ...cursorsRef.current });
        }, 15000);
      }
    };

    if (ws.readyState === WebSocket.OPEN) onOpen();
    ws.addEventListener("open", onOpen);
    ws.addEventListener("message", onMessage);
    return () => {
      clearInterval(sweepIv);
      ws.removeEventListener("open", onOpen);
      ws.removeEventListener("message", onMessage);
      Object.values(cursorsTimers).forEach((t) => clearTimeout(t));
    };
  }, [enabled, wsRef, slug, sheetRef, connState]);

  // Send my selection (throttled). Called by the editor on selection changes
  // and by the idle heartbeat.
  const lastSentRef = useRef(0);
  const sendCursor = (anchor, head) => {
    if (!canEdit) return;
    const now = Date.now();
    if (now - lastSentRef.current < 90) return;
    lastSentRef.current = now;
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      ws.send(
        JSON.stringify({
          type: "cursor",
          c: {
            clientId: getIdentity().clientId,
            sheetId: sheetRef ? sheetRef.current : "main",
            anchor: Math.max(0, Math.floor(anchor) || 0),
            head: Math.max(0, Math.floor(head) || 0),
          },
        }),
      );
    } catch (e) {
      /* ignore */
    }
  };

  const cursorsForSheet = (sid) => {
    const out = [];
    for (const [cid, cur] of Object.entries(cursors)) {
      if (cur.sheetId !== sid) continue;
      const meta = peersRef.current.get(cid);
      out.push({
        clientId: cid,
        name: meta?.name || "Guest",
        color: meta?.color || colorForPeer(cid),
        initials: meta?.initials || "?",
        anchor: cur.anchor,
        head: cur.head,
      });
    }
    return out;
  };

  return { peers, cursorsForSheet, sendCursor };
}
