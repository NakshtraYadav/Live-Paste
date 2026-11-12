// Ordinary regression specifications for defects confirmed in the original audit.
// Included in yarn test; every assertion must pass.
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import * as Y from "yjs";
import useCollab from "../src/hooks/useCollab";
import { useRecorder } from "../src/hooks/useRecorder";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("known frontend bug specifications", () => {
  it("B06: reconnect init must not merge main-sheet history into an active secondary page", () => {
    const ws = new EventTarget();
    const second = new Y.Doc();
    second.getText("content").insert(0, "SECOND PAGE");
    const main = new Y.Doc();
    main.getText("content").insert(0, "MAIN PAGE");
    const encoded = btoa(String.fromCharCode(...Y.encodeStateAsUpdate(main)));
    const mounted = renderHook(() => useCollab({
      wsRef: { current: ws }, enabled: true, ydocRef: { current: second },
      sheetRef: { current: "0123456789ab" }, connectionVersion: 1,
    }));
    act(() => ws.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({ type: "init", yUpdatesB64: [encoded] }) })));
    const actual = second.getText("content").toString();
    mounted.unmount(); main.destroy(); second.destroy();
    expect(actual).toBe("SECOND PAGE");
  });

  it("B18: screen recording must select a video MIME type when video is supported", async () => {
    const tracks = [{ stop: vi.fn(), addEventListener: vi.fn() }];
    const stream = { getTracks: () => tracks, addTrack: vi.fn() };
    let selectedMime;
    vi.stubGlobal("navigator", { mediaDevices: {
      getDisplayMedia: vi.fn(async () => stream),
      getUserMedia: vi.fn(async () => ({ getAudioTracks: () => [] })),
    } });
    class Recorder {
      static isTypeSupported() { return true; }
      constructor(_, options) { selectedMime = options.mimeType; this.state = "inactive"; }
      start() { this.state = "recording"; }
      stop() { this.state = "inactive"; }
    }
    vi.stubGlobal("MediaRecorder", Recorder);
    const mounted = renderHook(() => useRecorder({ onComplete: vi.fn() }));
    let result;
    await act(async () => { result = await mounted.result.current.start("screen"); });
    mounted.unmount();
    expect(result).toBe("recording");
    expect(selectedMime).toMatch(/^video\//);
  });
});
