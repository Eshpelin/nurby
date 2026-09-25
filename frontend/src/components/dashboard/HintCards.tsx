"use client";

/**
 * The three nudge cards that sit under the dashboard: secure your account,
 * run the AI locally, try asking a question. Each one decides for itself
 * whether it has anything to say, and renders nothing when it does not.
 */


import { useState, useEffect } from "react";
import { useAuth } from "@/lib/auth";
import { SecureAccountModal } from "@/components/SecureAccountModal";
import { PROVIDERS_CHANGED_EVENT } from "@/lib/providers-changed";
  process.env.NEXT_PUBLIC_WEBRTC_URL || "http://localhost:8889";

// The secure-account nudge card was removed in #318: it floated over the
// Ask composer and duplicated the navbar's red "Secure account" button,
// which is the single durable surface for a provisional owner.

// Nudge to turn on local AI when no vision provider is configured. The
// product works without a VLM (detection, faces, rules), but scene
// captions and Ask need one. We keep the bundled Ollama opt-in so a plain
// `docker compose up` stays light, and surface the one command here so a
// first-time user gets AI "without doing much". Hidden once a provider is
// active or the user dismisses it.
export function LocalAIHintCard() {
  const { authFetch } = useAuth();
  const [show, setShow] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem("nurby-localai-hint-dismissed") === "1") return;
    } catch {
      return;
    }
    let cancelled = false;
    const loadProviders = async () => {
      try {
        const res = await authFetch("/api/providers");
        if (!res.ok) return;
        const list: { active?: boolean }[] = await res.json();
        // Only nudge when nothing is configured at all.
        if (!cancelled && Array.isArray(list) && !list.some((p) => p.active)) {
          setShow(true);
        }
      } catch {
        /* stay hidden on error */
      }
    };
    void loadProviders();
    const onChanged = () => {
      void loadProviders();
    };
    window.addEventListener(PROVIDERS_CHANGED_EVENT, onChanged);
    return () => {
      cancelled = true;
      window.removeEventListener(PROVIDERS_CHANGED_EVENT, onChanged);
    };
  }, [authFetch]);

  function dismiss() {
    try {
      localStorage.setItem("nurby-localai-hint-dismissed", "1");
    } catch {
      /* ignore */
    }
    setShow(false);
  }

  if (!show) return null;
  return (
    <div className="hidden md:block fixed bottom-16 left-4 z-40 w-80 rounded-lg border border-accent/30 bg-card-elevated shadow-xl p-3">
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <div className="text-xs font-semibold flex items-center gap-1.5">
          <span>🧠</span> Add AI descriptions
        </div>
        <button
          onClick={dismiss}
          aria-label="Dismiss"
          className="text-muted-foreground hover:text-foreground text-sm leading-none"
        >
          &times;
        </button>
      </div>
      <p className="text-[11px] text-muted-foreground leading-snug mb-2">
        Nurby already spots motion and faces. Want scene captions and Ask
        Nurby? Choose a provider in Settings. No provider is required for
        detection, recording, or alerts.
      </p>
      <p className="text-[10px] text-muted-foreground leading-snug">
        <a href="/settings" className="text-accent hover:underline">
          Open Settings → AI Providers
        </a>{" "}
        to add one, or skip it. Everything else keeps working.
      </p>
    </div>
  );
}

// Dismissible nudge toward the agent. The /ask page is the payoff but
// it is just a nav item; a first-time user won't know it exists. Shows
// once (per browser) with example questions that deep-link to a real
// answer via /ask?q=. Hidden after dismissal or first click.
export function AskHintCard() {
  const { authFetch } = useAuth();
  const [dismissed, setDismissed] = useState(true);
  // Null while unknown. With no active provider every example question
  // would just error, so the card offers setup instead (#318) — mirroring
  // the Ask page's own no-provider state.
  const [hasProvider, setHasProvider] = useState<boolean | null>(null);
  useEffect(() => {
    try {
      setDismissed(localStorage.getItem("nurby-ask-hint-dismissed") === "1");
    } catch {
      setDismissed(true);
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await authFetch("/api/providers");
        if (!cancelled && res.ok) {
          const list: { active?: boolean }[] = await res.json();
          setHasProvider(Array.isArray(list) && list.some((p) => p.active));
        }
      } catch {
        /* stay neutral */
      }
    })();
    return () => { cancelled = true; };
  }, [authFetch]);
  function close() {
    try {
      localStorage.setItem("nurby-ask-hint-dismissed", "1");
    } catch {
      /* ignore */
    }
    setDismissed(true);
  }
  if (dismissed) return null;
  const examples = [
    "What happened today?",
    "Was anyone at the door?",
    "Where's the dog right now?",
  ];
  const providerKnown = hasProvider !== null;
  return (
    <div className="hidden md:block fixed bottom-16 right-4 z-40 w-72 rounded-lg border border-accent/30 bg-card-elevated shadow-xl p-3">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="text-xs font-semibold flex items-center gap-1.5">
          <span>💬</span> Try asking Nurby
        </div>
        <button
          onClick={close}
          aria-label="Dismiss"
          className="text-muted-foreground hover:text-foreground text-sm leading-none"
        >
          &times;
        </button>
      </div>
      <p className="text-[11px] text-muted-foreground leading-tight mb-2">
        Ask in plain English. Nurby investigates your feed and answers with
        evidence.
      </p>
      {providerKnown && !hasProvider ? (
        <a
          href="/settings"
          className="block w-full text-left px-2.5 py-1.5 text-[11px] rounded-md border border-accent/40 text-accent hover:bg-accent/5 transition-colors"
        >
          Ask needs an AI model — set one up →
        </a>
      ) : (
        <div className="space-y-1.5">
          {examples.map((q) => (
            <a
              key={q}
              href={`/ask?q=${encodeURIComponent(q)}`}
              onClick={() => {
                try {
                  localStorage.setItem("nurby-ask-hint-dismissed", "1");
                } catch {
                  /* ignore */
                }
              }}
              className="block w-full text-left px-2.5 py-1.5 text-[11px] rounded-md border border-border bg-background hover:border-accent/50 hover:bg-accent/5 transition-colors"
            >
              {q}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
