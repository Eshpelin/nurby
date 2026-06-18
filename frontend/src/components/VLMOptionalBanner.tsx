"use client";

// A single, calm, dismissible notice that an AI provider is optional.
// Shown only when no provider is configured. Detection, recording, and
// alerts all work without one, so this never blocks anything and never
// nags: once dismissed it stays dismissed (localStorage), and it never
// uses alarming red/pulsing styling.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useVlmOptional } from "@/lib/useVlmOptional";

const DISMISS_KEY = "nurby:vlm-optional-dismissed";

export function VLMOptionalBanner() {
  const { configured, loading } = useVlmOptional();
  const [dismissed, setDismissed] = useState(true);

  // Read the persisted dismissal on mount. Start dismissed so the banner
  // never flashes in before we know the user already closed it.
  useEffect(() => {
    let wasDismissed = false;
    try {
      wasDismissed = localStorage.getItem(DISMISS_KEY) === "1";
    } catch {
      wasDismissed = false;
    }
    // One-shot sync of a persisted value after mount; localStorage is
    // client-only, so this must run post-hydration rather than in a lazy
    // initializer (which would mismatch SSR).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDismissed(wasDismissed);
  }, []);

  const dismiss = () => {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* ignore: a private-mode write failure should not break dismissal */
    }
  };

  // Nothing to show while loading, when a provider exists, or once closed.
  if (loading || configured || dismissed) return null;

  return (
    <div className="mb-3 flex items-start gap-3 rounded-lg border border-accent/30 bg-accent/5 px-4 py-3">
      <svg
        className="h-4 w-4 text-accent mt-0.5 flex-shrink-0"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="10" />
        <path d="M12 16v-4" />
        <path d="M12 8h.01" />
      </svg>
      <div className="flex-1 text-sm">
        <span className="font-medium">AI provider optional.</span>{" "}
        <span className="text-muted-foreground">
          Detection, recording, and alerts work without it. Add a provider to
          enable scene descriptions and Ask Nurby.
        </span>{" "}
        <Link
          href="/settings"
          className="inline-flex items-center gap-1 text-accent hover:underline whitespace-nowrap"
        >
          <svg
            className="h-3.5 w-3.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
          Settings
        </Link>
      </div>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        className="text-muted-foreground hover:text-foreground text-lg leading-none flex-shrink-0"
      >
        ×
      </button>
    </div>
  );
}
