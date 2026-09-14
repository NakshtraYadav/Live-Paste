/**
 * Per-tab collaboration identity for live cursors + presence.
 *
 * The id is random per browser tab (each tab = one participant), a friendly
 * display name is derived from it, and the palette color is stable per id so
 * a peer keeps "their" color across reconnects. The name survives page
 * reloads via localStorage so you stay "the same person" on your machine.
 */

const NAME_KEY = "lp_display_name";

export const PEER_COLORS = [
  "#f43f5e", // rose
  "#f59e0b", // amber
  "#10b981", // emerald
  "#3b82f6", // blue
  "#8b5cf6", // violet
  "#ec4899", // pink
  "#14b8a6", // teal
  "#f97316", // orange
];

const ADJECTIVES = [
  "Swift", "Calm", "Bold", "Bright", "Quiet", "Nimble", "Lucky", "Brave",
  "Clever", "Cosmic", "Golden", "Rapid", "Sunny", "Wild", "Witty", "Zesty",
];

const ANIMALS = [
  "Otter", "Falcon", "Panda", "Lynx", "Heron", "Dolphin", "Tiger", "Raven",
  "Koala", "Puffin", "Gecko", "Badger", "Marmot", "Ibex", "Fennec", "Pika",
];

function randomId() {
  const bytes = new Uint8Array(8);
  (window.crypto || window.msCrypto).getRandomValues(bytes);
  let s = "";
  for (const b of bytes) s += b.toString(16).padStart(2, "0");
  return s;
}

function pick(list, n) {
  return list[n % list.length];
}

function initialsOf(name) {
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return (name[0] || "?").toUpperCase();
}

/**
 * Get (or lazily create) this tab's identity.
 * @returns {{ clientId: string, name: string, color: string, initials: string }}
 */
export function getIdentity() {
  if (typeof window === "undefined") {
    return { clientId: "unknown", name: "Guest", color: PEER_COLORS[0], initials: "G" };
  }
  if (!window.__lpIdentity) {
    const clientId = randomId();
    const n = parseInt(clientId.slice(0, 6), 16);
    let name = null;
    try {
      name = window.localStorage.getItem(NAME_KEY);
    } catch (e) {
      /* private mode */
    }
    if (!name) {
      name = `${pick(ADJECTIVES, n)} ${pick(ANIMALS, n >> 4)}`;
      try {
        window.localStorage.setItem(NAME_KEY, name);
      } catch (e) {
        /* ignore */
      }
    }
    window.__lpIdentity = {
      clientId,
      name,
      color: PEER_COLORS[n % PEER_COLORS.length],
      initials: initialsOf(name),
    };
  }
  return window.__lpIdentity;
}

export function setDisplayName(name) {
  const id = getIdentity();
  const clean = (name || "").trim().slice(0, 24);
  if (!clean) return id;
  id.name = clean;
  id.initials = initialsOf(clean);
  try {
    window.localStorage.setItem(NAME_KEY, clean);
  } catch (e) {
    /* ignore */
  }
  return id;
}

/** Stable color for a peer id (peers keep their color across reconnects). */
export function colorForPeer(clientId) {
  let n = 0;
  for (let i = 0; i < (clientId || "").length; i += 1) {
    n = (n * 31 + clientId.charCodeAt(i)) >>> 0;
  }
  return PEER_COLORS[n % PEER_COLORS.length];
}
