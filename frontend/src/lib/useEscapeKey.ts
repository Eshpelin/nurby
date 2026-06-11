"use client";

import { useEffect } from "react";

/**
 * Call `onEscape` when the user presses Escape, while `active`. Standard
 * dismiss affordance for modals and panels; pairs with a backdrop click.
 */
export function useEscapeKey(onEscape: () => void, active: boolean = true) {
  useEffect(() => {
    if (!active) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onEscape();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onEscape, active]);
}
