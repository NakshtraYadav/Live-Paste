/**
 * Edit-token store — the secret that lets a link be edited.
 *
 * The token is saved in localStorage per slug so the creator (and anyone who
 * opens an `?edit=<token>` share link) stays in edit mode across visits.
 */
export const editTokenStore = {
  save: (slug, token) => {
    try {
      localStorage.setItem(`lp_edit_${slug}`, token);
    } catch (e) {
      /* private mode */
    }
  },
  get: (slug) => {
    try {
      return localStorage.getItem(`lp_edit_${slug}`) || "";
    } catch (e) {
      return "";
    }
  },
  clear: (slug) => {
    try {
      localStorage.removeItem(`lp_edit_${slug}`);
    } catch (e) {
      /* ignore */
    }
  },
};

// Short-lived-in-practice capability for a server-granted editor device. It
// is derived by the server from the owner's secret and must accompany REST
// file writes; a public clientId alone is never an authorization credential.
export const editorCapabilityStore = {
  save: (slug, capability) => {
    try {
      if (capability) localStorage.setItem(`lp_editor_cap_${slug}`, capability);
      else localStorage.removeItem(`lp_editor_cap_${slug}`);
    } catch (e) {
      /* private mode */
    }
  },
  get: (slug) => {
    try {
      return localStorage.getItem(`lp_editor_cap_${slug}`) || "";
    } catch (e) {
      return "";
    }
  },
};// Accept #edit=<token> from the URL fragment, persist it, and strip it from
// the address bar. Fragments are not sent in HTTP requests or proxy logs.
// The legacy ?edit=<token> form remains readable for old shared links and is
// removed immediately when encountered.
export const consumeEditTokenFromUrl = (slug) => {
  try {
    const params = new URLSearchParams(window.location.search);
    const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : "";
    const hashParams = new URLSearchParams(hash);
    const t = hashParams.get("edit") || params.get("edit");
    if (t) {
      editTokenStore.save(slug, t);
      params.delete("edit");
      window.history.replaceState(
        {},
        "",
        `${window.location.pathname}${params.toString() ? `?${params}` : ""}`,
      );
    }
  } catch (e) {
    /* ignore */
  }
  return editTokenStore.get(slug);
};
