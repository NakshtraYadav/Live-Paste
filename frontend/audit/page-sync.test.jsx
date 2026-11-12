import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import * as Y from "yjs";
import PastePage from "../src/pages/PastePage";

const sid = "0123456789ab";
vi.mock("axios", () => ({ default: {
  get: vi.fn(async (url) => ({ data: url.endsWith("/sheets") ? { sheets: [] } : { content: "", language: "plaintext" } })),
  post: vi.fn(), patch: vi.fn(), delete: vi.fn(),
} }));
vi.mock("../src/hooks/useOfflineDoc", () => ({
  useOfflineDoc: () => ({}), useOnlineStatus: () => true,
  hasOfflineDoc: async () => false, readOfflineDoc: async () => "", readOfflineState: vi.fn(async () => null), retainOfflineDoc: () => null,
}));
vi.mock("../src/hooks/useP2P", () => ({ default: () => ({ p2pPeers: 0, p2pStatus: "off" }) }));
vi.mock("../src/hooks/usePresence", () => ({ default: () => ({ peers: [], cursorsForSheet: () => [], sendCursor: () => {} }) }));

class Socket extends EventTarget {
  static OPEN = 1;
  static CONNECTING = 0;
  static instances = [];
  readyState = 1;
  constructor() { super(); Socket.instances.push(this); }
  send() {}
  close() { this.readyState = 3; }
  emit(data) {
    const event = new MessageEvent("message", { data: JSON.stringify(data) });
    this.onmessage?.(event);
    this.dispatchEvent(event);
  }
}
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("B17: secondary-page image updates must immediately render without a full-text backup", async () => {
  vi.stubGlobal("WebSocket", Socket);
  Socket.instances = [];
  render(<MemoryRouter initialEntries={["/audit-image"]}><Routes><Route path="/:slug" element={<PastePage />} /></Routes></MemoryRouter>);
  act(() => Socket.instances[0].emit({ type: "init", paste: { content: "", language: "plaintext" }, canEdit: true, isOwner: true, sheets: [{ sheetId: "main", name: "Page 1" }, { sheetId: sid, name: "Page 2" }] }));
  await waitFor(() => expect(screen.getByTestId(`paste-sheet-tab-${sid}`)).toBeInTheDocument());
  await act(async () => fireEvent.click(screen.getByTestId(`paste-sheet-tab-${sid}`)));
  const ws = Socket.instances.at(-1);
  act(() => ws.emit({ type: "s:state", sheetId: sid }));
  const remoteDoc = new Y.Doc();
  const imageId = "0123456789abcdef01234567";
  remoteDoc.getText("content").insert(0, `![test.png](/api/image/${imageId})`);
  const encoded = btoa(String.fromCharCode(...Y.encodeStateAsUpdate(remoteDoc)));
  act(() => ws.emit({ type: "s:yupdate", sheetId: sid, updateB64: encoded }));
  remoteDoc.destroy();
  // No s:edit backup is sent: the CRDT update itself must update the view.
  expect(screen.queryByTestId(`paste-inline-image-${imageId}`)).toBeInTheDocument();
});

it("attaches an upload to its original page when the user switches pages while uploading", async () => {
  const axios = (await import("axios")).default;
  let completeUpload;
  axios.post.mockImplementation((url) => url.endsWith("/file") ? new Promise(resolve => { completeUpload = resolve; }) : Promise.resolve({ data: {} }));
  vi.stubGlobal("WebSocket", Socket);
  Socket.instances = [];
  const mounted = render(<MemoryRouter initialEntries={["/audit-upload"]}><Routes><Route path="/:slug" element={<PastePage />} /></Routes></MemoryRouter>);
  act(() => Socket.instances[0].emit({ type: "init", paste: { content: "", language: "plaintext" }, canEdit: true, isOwner: true, sheets: [{ sheetId: "main", name: "Page 1" }, { sheetId: sid, name: "Page 2" }] }));
  const input = mounted.container.querySelector('input[type="file"]');
  await act(async () => fireEvent.change(input, { target: { files: [new File(["fixture"], "fixture.txt", { type: "text/plain" })] } }));
  await act(async () => fireEvent.click(screen.getByTestId(`paste-sheet-tab-${sid}`)));
  await act(async () => completeUpload({ data: { id: "0123456789abcdef01234567", name: "fixture.txt", contentType: "text/plain" } }));
  const completion = axios.post.mock.calls.find(([url]) => url.includes("/sync/"));
  expect(completion[0]).toBe("/api/paste/audit-upload/sync/main");
  const original = new Y.Doc();
  Y.applyUpdate(original, Uint8Array.from(atob(completion[1].updateB64), c => c.charCodeAt(0)));
  expect(original.getText("content").toString()).toContain("fixture.txt");
  expect(screen.queryByTestId("paste-inline-file-0123456789abcdef01234567")).not.toBeInTheDocument();
  original.destroy();
});

it("never hydrates a loaded secondary page from the main cache during a long outage", async () => {
  const offline = await import("../src/hooks/useOfflineDoc");
  const main = new Y.Doc(); main.getText("content").insert(0, "MAIN CACHE MUST NOT LEAK");
  offline.readOfflineState.mockResolvedValue(Y.encodeStateAsUpdate(main));
  vi.stubGlobal("WebSocket", Socket); Socket.instances = [];
  render(<MemoryRouter initialEntries={["/audit-outage"]}><Routes><Route path="/:slug" element={<PastePage />} /></Routes></MemoryRouter>);
  act(() => Socket.instances[0].emit({ type: "init", paste: { content: "", language: "plaintext" }, canEdit: true, isOwner: true, sheets: [{ sheetId: "main", name: "Page 1" }, { sheetId: sid, name: "Page 2" }] }));
  await act(async () => fireEvent.click(screen.getByTestId(`paste-sheet-tab-${sid}`)));
  const second = new Y.Doc(); second.getText("content").insert(0, "SECOND PAGE");
  const ws = Socket.instances.at(-1);
  act(() => ws.emit({ type: "s:state", sheetId: sid, yUpdatesB64: [btoa(String.fromCharCode(...Y.encodeStateAsUpdate(second)))] }));
  vi.useFakeTimers();
  act(() => { ws.readyState = 3; ws.onclose(); });
  await act(async () => vi.advanceTimersByTimeAsync(5500));
  expect(screen.getByRole("textbox")).toHaveValue("SECOND PAGE");
  main.destroy(); second.destroy();
});

it("keeps rapid typing after a page switch out of the previous page", async () => {
  vi.stubGlobal("WebSocket", Socket); Socket.instances = [];
  const main = new Y.Doc(); main.getText("content").insert(0, "MAIN MUST STAY");
  render(<MemoryRouter initialEntries={["/atomic-switch"]}><Routes><Route path="/:slug" element={<PastePage />} /></Routes></MemoryRouter>);
  act(() => Socket.instances[0].emit({ type:"init",protocol:2,epoch:"b".repeat(32),paste:{content:"MAIN MUST STAY",language:"plaintext"},yUpdatesB64:[btoa(String.fromCharCode(...Y.encodeStateAsUpdate(main)))],canEdit:true,isOwner:true,sheets:[{sheetId:"main",name:"Page 1"},{sheetId:sid,name:"Page 2"}] }));
  const outgoing = screen.getByRole("textbox");
  act(() => {
    fireEvent.click(screen.getByTestId(`paste-sheet-tab-${sid}`));
    fireEvent.change(outgoing, { target: { value: "SECOND PAGE TYPING" } });
  });
  await act(async () => fireEvent.click(screen.getByTestId("paste-sheet-tab-main")));
  expect(screen.getByRole("textbox")).toHaveValue("MAIN MUST STAY");
  main.destroy();
});
