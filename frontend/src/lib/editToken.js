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
};

// Accept ?edit=<token> in the URL, persist it, and strip it from the address bar
// (share-able edit links). Returns the stored token for the slug.
export const consumeEditTokenFromUrl = (slug) => {
  try {
    const params = new URLSearchParams(window.location.search);
    const t = params.get("edit");
    if (t) {
      editTokenStore.save(slug, t);
      params.delete("edit");
      const qs = params.toString();
      window.history.replaceState({}, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
    }
  } catch (e) {
    /* ignore */
  }
  return editTokenStore.get(slug);
};