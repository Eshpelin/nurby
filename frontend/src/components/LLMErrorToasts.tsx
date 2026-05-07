"use client";

import { useEffect, useState } from "react";
import { useWSSubscribe } from "@/lib/ws";

interface ErrorToast {
  id: number;
  providerName: string;
  providerKind: string;
  op: string;
  status: number;
  message: string;
}

const HOLD_MS = 8000;
const MAX_VISIBLE = 4;

/**
 * Subscribes to llm_error WS events and surfaces a stack of toasts
 * in the bottom-right of the dashboard. Auto-dismiss after HOLD_MS.
 * Identical errors are deduped by (providerName, status) within the
 * dedup window so a 429 storm doesn't create 50 toasts.
 */
export function LLMErrorToasts() {
  const [toasts, setToasts] = useState<ErrorToast[]>([]);
  const [seq, setSeq] = useState(0);

  useWSSubscribe("llm_error", (msg) => {
    const providerName = String(msg.provider_name || "Unknown");
    const providerKind = String(msg.provider_kind || "?");
    const op = String(msg.op || "call");
    const status = Number(msg.status || 0);
    const message = String(msg.message || "request failed");
    setToasts((prev) => {
      // Dedup: drop if an identical toast is already on screen.
      if (
        prev.some(
          (t) =>
            t.providerName === providerName &&
            t.status === status &&
            t.op === op
        )
      )
        return prev;
      const id = seq + 1;
      setSeq(id);
      const next: ErrorToast = {
        id,
        providerName,
        providerKind,
        op,
        status,
        message,
      };
      const out = [...prev, next].slice(-MAX_VISIBLE);
      setTimeout(() => {
        setToasts((cur) => cur.filter((t) => t.id !== id));
      }, HOLD_MS);
      return out;
    });
  });

  useEffect(
    () => () => {
      // Toasts are stateful timers; React's StrictMode will mount us
      // twice in dev. The setTimeout cleanup above handles each
      // individual toast.
    },
    []
  );

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-16 right-4 z-50 flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="alert"
          className="pointer-events-auto rounded-lg border border-danger/50 bg-danger/10 backdrop-blur-md px-3 py-2 max-w-sm shadow-lg animate-[fadeIn_0.2s_ease-out]"
        >
          <div className="flex items-start gap-2 text-xs">
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-danger flex-shrink-0 mt-0.5"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <div className="min-w-0 flex-1">
              <div className="font-medium text-danger">
                {t.providerName} · {t.op === "vlm" ? "VLM call" : "LLM call"}
                {t.status === 429 && (
                  <span className="ml-1 text-[10px] uppercase tracking-wider text-warning">
                    rate limited
                  </span>
                )}
              </div>
              <div className="text-muted-foreground mt-0.5">
                {t.status > 0 ? `HTTP ${t.status}` : ""} {t.message}
              </div>
              {t.status === 429 && (
                <div className="text-[11px] text-muted-foreground/80 mt-1">
                  Provider throttled. Calls will retry with backoff. Check
                  the provider's rate limit or set a tighter token cap in
                  Settings.
                </div>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
