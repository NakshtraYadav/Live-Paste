import { useEffect, useRef, useState } from "react";
import { WebrtcProvider } from "y-webrtc";

/**
 * P2P LAN mode — peer-to-peer sync over WebRTC data channels.
 *
 * When enabled, a WebrtcProvider joins the same Y.Doc on the topic
 * `lp:<slug>:<sheet>`, so browsers on the same network exchange document
 * updates DIRECTLY with each other; the LivePaste server only brokers the
 * initial handshake (SDP + ICE) through its dumb signaling relay at
 * /api/ws/signaling and never touches the data.
 *
 * The provider attaches an extra sync path to the SAME Y.Doc the server
 * CRDT sync (useCollab) already uses — Yjs merges everything idempotently,
 * so both transports can run at once without conflicts.
 *
 * `docVersion` must bump whenever the Y.Doc instance is swapped (paste load /
 * sheet switch) so a new provider is created for the right doc.
 */
export default function useP2P({ slug, ydocRef, docVersion = 0, sheetId = "main", enabled }) {
  const providerRef = useRef(null);
  const [p2pPeers, setP2pPeers] = useState(0);
  const [p2pStatus, setP2pStatus] = useState("off"); // off | connecting | connected

  useEffect(() => {
    if (!enabled || !slug || !ydocRef.current) {
      setP2pStatus("off");
      setP2pPeers(0);
      return undefined;
    }
    const doc = ydocRef.current;
    const sid = sheetId || "main";
    // v3.4.0: the provider now FOLLOWS the active sheet — the topic changes
    // with it (sheetId is a real dependency), so peers only sync the page
    // they are actually on, and switching pages re-attaches the data channel
    // to the new Y.Doc.
    const provider = new WebrtcProvider(`lp:${slug}:${sid}`, doc, {
      // Our own relay — localhost/LAN first, no third-party signaling servers.
      // If the relay is unreachable, peers on the same page can still discover
      // each other via BroadcastChannel (same-browser tabs) and the doc keeps
      // syncing through the normal server CRDT path.
      signaling: [
        `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/api/webrtc/signaling`,
      ],
      maxConns: 12,
    });
    providerRef.current = provider;
    setP2pStatus("connecting");
    setP2pPeers(0);

    const onPeers = ({ added, removed, webrtcPeers }) => {
      setP2pPeers(webrtcPeers ? webrtcPeers.length : 0);
      if (webrtcPeers && webrtcPeers.length > 0) setP2pStatus("connected");
    };
    provider.on("peers", onPeers);
    provider.on("synced", () => setP2pStatus("connected"));

    return () => {
      try {
        provider.destroy();
      } catch (e) {
        /* ignore */
      }
      providerRef.current = null;
      setP2pStatus("off");
      setP2pPeers(0);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, sheetId, ydocRef, docVersion, enabled]);

  return { p2pPeers, p2pStatus };
}
