import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import * as Y from "yjs";
import useCollab, { encodeUpdate, decodeUpdate } from "../src/hooks/useCollab";
import { getIdentity } from "../src/lib/identity";
import { editorCapabilityStore } from "../src/lib/editToken";

class Socket extends EventTarget {
  static OPEN = 1;
  readyState = 1;
  sent = [];
  send(data) { this.sent.push(JSON.parse(data)); }
  receive(message) { this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(message) })); }
}
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
const encoded = doc => encodeUpdate(Y.encodeStateAsUpdate(doc));

it("keeps edit identity and its capability across a refresh", () => {
  sessionStorage.clear(); localStorage.clear(); delete window.__lpIdentity;
  const original = getIdentity().clientId;
  editorCapabilityStore.save("refresh", "secret-grant");
  delete window.__lpIdentity;
  expect(getIdentity().clientId).toBe(original);
  expect(editorCapabilityStore.get("refresh")).toBe("secret-grant");
});

it("resends restored offline state, retries lost acknowledgements, and ignores late acknowledgements", () => {
  vi.useFakeTimers(); vi.stubGlobal("WebSocket", Socket);
  const server = new Y.Doc(); server.getText("content").insert(0, "base");
  const beforeReload = new Y.Doc(); Y.applyUpdate(beforeReload, Y.encodeStateAsUpdate(server));
  beforeReload.getText("content").insert(4, " offline");
  const reloaded = new Y.Doc(); Y.applyUpdate(reloaded, Y.encodeStateAsUpdate(beforeReload), "indexeddb");
  const ws = new Socket(); const status = vi.fn();
  const docs = { current: new Map([["main", reloaded]]) };
  renderHook(() => useCollab({ wsRef: { current: ws }, enabled: true, canEdit: true,
    ydocRef: { current: reloaded }, documentsRef: docs, sheetRef: { current: "main" }, onSyncStatus: status }));
  act(() => ws.receive({ type: "init", canEdit: true, yUpdatesB64: [encoded(server)] }));
  expect(ws.sent).toHaveLength(1);
  Y.applyUpdate(server, decodeUpdate(ws.sent[0].updateB64));
  expect(server.getText("content").toString()).toBe("base offline");
  // Server persisted it, but its acknowledgement was lost.
  act(() => vi.advanceTimersByTime(6120));
  expect(ws.sent.length).toBeGreaterThan(1);
  const latest = ws.sent.at(-1);
  act(() => ws.receive({ type: "sync-ack", sheetId: "main", requestId: ws.sent[0].requestId, yUpdatesB64: [encoded(server)] }));
  expect(status).not.toHaveBeenLastCalledWith("connected");
  act(() => ws.receive({ type: "sync-ack", sheetId: "main", requestId: latest.requestId, yUpdatesB64: [encoded(server)] }));
  expect(status).toHaveBeenLastCalledWith("connected");
  expect(reloaded.getText("content").toString()).toBe("base offline");
});

it("preserves local typing when a new page receives its first server identity", () => {
  vi.stubGlobal("WebSocket", Socket);
  const doc = new Y.Doc(); doc.getText("content").insert(0, "typed before state arrived");
  const ws = new Socket();
  const mounted = renderHook(() => useCollab({ wsRef: { current: ws }, enabled: true, canEdit: true,
    documentKey: "new-page-race", ydocRef: { current: doc }, sheetRef: { current: "main" } }));
  act(() => ws.receive({ type:"init",canEdit:true,epoch:"a".repeat(32),yUpdatesB64:[encoded(new Y.Doc())] }));
  expect(doc.getText("content").toString()).toBe("typed before state arrived");
  mounted.unmount(); doc.destroy();
});
