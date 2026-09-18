import "@testing-library/jest-dom";

// jsdom lacks matchMedia (used by theme hooks / Radix components)
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}

// jsdom lacks ResizeObserver (used by some Radix primitives)
if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// jsdom lacks scrollTo
if (!window.scrollTo) {
  window.scrollTo = () => {};
}
