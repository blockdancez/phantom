"use client";

import { useEffect } from "react";

// Exposes a small `window.__TEST__` object so Playwright / Chrome DevTools
// scripts can synchronously ask the app "is the first paint done" and
// "what route are we on" without hard-coding test-specific selectors into
// the production code. Production bundles set NEXT_PUBLIC_ENABLE_TEST_HOOKS
// to "false" to opt out.

declare global {
  interface Window {
    __TEST__?: {
      ready: boolean;
      route: string;
      user: null;
      store: Record<string, unknown>;
    };
  }
}

export function TestHarness() {
  useEffect(() => {
    if (process.env.NEXT_PUBLIC_ENABLE_TEST_HOOKS === "false") {
      return;
    }
    window.__TEST__ = {
      ready: true,
      route: window.location.pathname,
      user: null,
      store: {},
    };
    return () => {
      if (window.__TEST__) {
        window.__TEST__.ready = false;
      }
    };
  }, []);
  return null;
}
