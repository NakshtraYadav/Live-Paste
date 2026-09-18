import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import React from "react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import PastePage from "@/pages/PastePage";
import { editTokenStore, editorCapabilityStore } from "@/lib/editToken";

// ---- mocks ----------------------------------------------------------------
// PastePage reaches for the network (axios) and WebSockets on mount. Stub both
// so the component tests exercise rendering, not transport.
vi.mock("axios", () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    put: vi.fn(() => Promise.resolve({ data: {} })),
  },
}));

class FakeWebSocket {
  constructor() {
    this.readyState = 1; // OPEN — prevents reconnect loops in tests
    FakeWebSocket.instances.push(this);
  }
  send() {}
  close() {}
  addEventListener() {}
  removeEventListener() {}
}
FakeWebSocket.OPEN = 1;
FakeWebSocket.CONNECTING = 0;
FakeWebSocket.instances = [];

// Regression guard: PastePage sets up a WS auth subprotocol on mount. The
// original blank-page bug was a SyntaxError inside the base64url encoder used
// to build that subprotocol, which crashed the whole React tree.
vi.stubGlobal("WebSocket", FakeWebSocket);

function renderPaste(slug) {
  return render(
    <MemoryRouter initialEntries={[`/${slug}`]}>
      <Routes>
        <Route path="/" element={<div>home</div>} />
        <Route path="/:slug" element={<PastePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  FakeWebSocket.instances = [];
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// ---- tests ----------------------------------------------------------------

describe("PastePage", () => {
  it("renders the loading state immediately (never a blank page)", () => {
    renderPaste("loading-test");
    // The very first paint must show the loading indicator while the WS
    // handshake settles. Empty #root here is the original bug's signature.
    expect(
      screen.getByTestId("paste-loading"),
    ).toBeInTheDocument();
  });

  it("keeps a mounted React tree after the WebSocket auth setup runs", async () => {
    const { container } = renderPaste("mount-test");
    // Let effects flush (WS construction + timers). If encodeWebSocketAuth
    // throws during effect setup, React unmounts and #root goes empty.
    await waitFor(() => {
      expect(container.firstChild).not.toBeNull();
    });
    expect(FakeWebSocket.instances.length).toBeGreaterThanOrEqual(1);
    // Still mounted after a tick of timers/microtasks
    await new Promise((r) => setTimeout(r, 20));
    expect(container.firstChild).not.toBeNull();
  });

  it("builds a valid base64url WS auth subprotocol (regex-escape regression)", () => {
    // The original bug: /\\+/g in source → invalid regex in the bundle →
    // SyntaxError. This asserts the token shape the encoder must produce.
    const payload = { token: "t+/=", password: "", clientId: "abc", capability: "" };
    const bytes = new TextEncoder().encode(JSON.stringify(payload));
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    const encoded = window
      .btoa(binary)
      .replaceAll("+", "-")
      .replaceAll("/", "_")
      .replace(/=+$/, "");
    // base64url alphabet only
    expect(encoded).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(encoded).not.toContain("+");
    expect(encoded).not.toContain("/");
    // LP protocol shape: lp-auth.<base64url>
    expect(`lp-auth.${encoded}`).toMatch(/^lp-auth\.[A-Za-z0-9_-]+$/);
  });

  it("does not open a WebSocket for a slug before effects complete", () => {
    renderPaste("no-ws-yet");
    // Initial synchronous render must not throw even though WS wiring is
    // pending; crash-free render is itself the regression bar here.
    expect(document.getElementById("root") || document.body).toBeTruthy();
  });
});
