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

// Top-right nudge for a provisional owner. Nurby drops a first-run user
// straight into a working feed without forcing signup, so the trade is.
// you're already watching footage, but the account has no password yet.
// This box celebrates the footage and points at securing the account.
// It opens the same claim modal as the navbar's red button.
export function SecureAccountNudge({ hasFootage }: { hasFootage: boolean }) {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  if (!user?.is_provisional || dismissed) return null;
  return (
    <>
      <div className="fixed top-[4.5rem] right-4 z-40 w-80 rounded-lg border border-red-500/40 bg-card-elevated shadow-xl p-3">
        <div className="flex items-start justify-between gap-2 mb-1.5">
          <div className="text-xs font-semibold flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 pulse-dot" />
            {hasFootage ? "Your footage is live" : "One step left"}
          </div>
          <button
            onClick={() => setDismissed(true)}
            aria-label="Dismiss"
            className="text-muted-foreground hover:text-foreground text-sm leading-none"
          >
            &times;
          </button>
        </div>
        <p className="text-[11px] text-muted-foreground leading-snug mb-2.5">
          {hasFootage
            ? "Nurby is already watching, but you haven't set a password. Anyone who reaches this page is an admin. Lock it down."
            : "You haven't set a password yet, so anyone who reaches this page is an admin. Lock it down."}
        </p>
        <button
          onClick={() => setOpen(true)}
          className="w-full px-3 py-1.5 text-xs font-medium rounded-md bg-red-600 hover:bg-red-500 text-white transition-colors"
        >
          Secure your account
        </button>
      </div>
      {open && <SecureAccountModal onClose={() => setOpen(false)} />}
    </>
  );
}

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
    <div className="hidden md:block fixed bottom-4 left-4 z-40 w-80 rounded-lg border border-accent/30 bg-card-elevated shadow-xl p-3">
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
  const [dismissed, setDismissed] = useState(true);
  useEffect(() => {
    try {
      setDismissed(localStorage.getItem("nurby-ask-hint-dismissed") === "1");
    } catch {
      setDismissed(true);
    }
  }, []);
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
  return (
    <div className="hidden md:block fixed bottom-4 right-4 z-40 w-72 rounded-lg border border-accent/30 bg-card-elevated shadow-xl p-3">
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
    </div>
  );
}
