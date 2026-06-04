"use client";

// Bottom composer row. Autogrowing textarea + a chip row with the
// model selector, daily cost meter, send and cancel buttons. The
// textarea submits on Enter (Shift+Enter inserts newline) and disables
// the send button until a model is picked + text is non-empty.

import { useEffect, useRef } from "react";
import type { ProviderModel, UsageToday } from "./types";
import ModelSelector from "./ModelSelector";
import CostMeter from "./CostMeter";

interface ChatComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onCancel: () => void;
  inFlight: boolean;
  model: ProviderModel | null;
  onModelChange: (m: ProviderModel) => void;
  providers: ProviderModel[];
  providersLoading: boolean;
  onDeployToolModel?: (model: string) => Promise<void>;
  deploying?: boolean;
  usage: UsageToday | null;
  usageLoading: boolean;
  focusKey?: number;
}

export default function ChatComposer({
  value,
  onChange,
  onSend,
  onCancel,
  inFlight,
  model,
  onModelChange,
  providers,
  providersLoading,
  onDeployToolModel,
  deploying,
  usage,
  usageLoading,
  focusKey = 0,
}: ChatComposerProps) {
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  // Autogrow the textarea up to ~6 lines.
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, [value]);

  useEffect(() => {
    taRef.current?.focus();
  }, [focusKey]);

  const canSend = value.trim().length > 0 && !!model && !inFlight;

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) onSend();
    }
  };

  return (
    <div className="border-t border-border bg-background/95 backdrop-blur sticky bottom-0">
      <div className="max-w-3xl mx-auto px-4 py-3 space-y-2">
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKey}
          rows={1}
          placeholder="Ask Nurby anything about your cameras."
          aria-label="Ask Nurby a question"
          className="w-full resize-none px-3 py-2.5 text-sm rounded-md bg-card border border-border focus:outline-none focus:border-accent placeholder:text-muted-foreground"
        />
        <div className="flex items-center gap-2 flex-wrap">
          <ModelSelector
            value={model}
            onChange={onModelChange}
            providers={providers}
            loading={providersLoading}
            onDeployToolModel={onDeployToolModel}
            deploying={deploying}
          />
          <CostMeter usage={usage} loading={usageLoading} />
          <div className="ml-auto flex items-center gap-2">
            {inFlight && (
              <button
                type="button"
                onClick={onCancel}
                aria-label="Cancel current run"
                className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted"
              >
                Cancel
              </button>
            )}
            <button
              type="button"
              onClick={onSend}
              disabled={!canSend}
              aria-label="Send question"
              className="px-3 py-1.5 text-xs rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
            >
              {inFlight ? (
                <>
                  <span className="inline-block w-3 h-3 rounded-full border-2 border-background/40 border-t-background animate-spin" />
                  Sending.
                </>
              ) : (
                "Send"
              )}
            </button>
          </div>
        </div>
        {!model && !providersLoading && (
          <div className="text-[10px] text-amber-400">
            Pick a model to send. Open the chip on the left.
          </div>
        )}
      </div>
    </div>
  );
}
