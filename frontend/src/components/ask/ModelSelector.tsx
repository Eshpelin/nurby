"use client";

// Model selector chip. Reads the household's configured Providers from
// /api/agent/providers (Wave 2A) and presents them grouped by provider
// kind. Persists the user's pick to localStorage so the next chat
// session starts on the same model.

import { useEffect, useRef, useState } from "react";
import type { ProviderModel } from "./types";

interface ModelSelectorProps {
  value: ProviderModel | null;
  onChange: (m: ProviderModel) => void;
  providers: ProviderModel[];
  loading?: boolean;
}

function groupByKind(list: ProviderModel[]): Record<string, ProviderModel[]> {
  const out: Record<string, ProviderModel[]> = {};
  for (const p of list) {
    (out[p.kind] ||= []).push(p);
  }
  return out;
}

const KIND_LABEL: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Gemini",
  ollama: "Ollama (local)",
};

export default function ModelSelector({
  value,
  onChange,
  providers,
  loading,
}: ModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const grouped = groupByKind(providers);
  const kinds = Object.keys(grouped).sort();

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={loading}
        aria-label="Pick AI model"
        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md border border-border bg-background hover:bg-muted disabled:opacity-50 transition-colors"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2l1.9 5.8H20l-4.9 3.6L17 17l-5-3.6L7 17l1.9-5.6L4 7.8h6.1L12 2z" />
        </svg>
        {loading ? (
          <span className="inline-block w-24 h-3 bg-muted rounded animate-pulse" />
        ) : value ? (
          <span className="font-mono">
            {value.kind} / {value.name}
          </span>
        ) : (
          <span className="text-amber-400">pick a model</span>
        )}
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" /></svg>
      </button>

      {open && (
        <div className="absolute bottom-full mb-2 left-0 z-50 w-80 max-h-[420px] overflow-auto rounded-lg border border-border bg-card shadow-xl">
          {providers.length === 0 ? (
            <div className="p-3 text-xs text-muted-foreground">
              No providers configured. Add one in Settings → Providers.
            </div>
          ) : (
            kinds.map((kind) => (
              <div key={kind} className="border-b border-border last:border-b-0">
                <div className="px-3 py-1.5 text-[10px] uppercase tracking-wide text-muted-foreground bg-background/50">
                  {KIND_LABEL[kind] || kind}
                </div>
                {grouped[kind].map((m) => {
                  const active = value?.provider_id === m.provider_id && value?.id === m.id;
                  return (
                    <button
                      key={`${m.provider_id}:${m.id}`}
                      type="button"
                      onClick={() => { onChange(m); setOpen(false); }}
                      className={`w-full flex items-start justify-between gap-2 px-3 py-2 text-left text-xs hover:bg-muted ${active ? "bg-muted" : ""}`}
                    >
                      <div className="min-w-0">
                        <div className="font-medium flex items-center gap-1.5">
                          <span className="truncate">{m.name}</span>
                          {m.recommended && (
                            <span className="text-[9px] px-1 py-px rounded bg-accent/20 text-accent border border-accent/30">
                              recommended
                            </span>
                          )}
                          {m.supports_tools === false && (
                            <span className="text-[9px] px-1 py-px rounded bg-amber-500/15 text-amber-400 border border-amber-500/30">
                              no tools
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] text-muted-foreground font-mono truncate">
                          {m.provider_name}
                        </div>
                        {m.supports_tools === false && (
                          <div className="text-[10px] text-amber-400/90 mt-0.5 leading-tight">
                            This local model can&apos;t call tools, so Ask Nurby won&apos;t work with it.
                            {m.suggested_tool_model
                              ? ` Pull ${m.suggested_tool_model} (Settings → Local AI) for the agent.`
                              : ""}
                          </div>
                        )}
                      </div>
                      {(m.cost_per_1k_in !== undefined || m.cost_per_1k_out !== undefined) && (
                        <div className="text-[10px] text-muted-foreground font-mono whitespace-nowrap">
                          {m.cost_per_1k_in?.toFixed?.(3) ?? "?"}¢/k in
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
