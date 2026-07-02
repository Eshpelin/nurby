"use client";

// "Describe your alert" → POST /api/rules/generate → prefilled builder.
// The model output is never saved directly; it lands in the builder for
// review and goes through the normal validated create path.

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import type { Rule } from "./types";

export function DescribeRuleBox({ onGenerated }: { onGenerated: (rule: Rule) => void }) {
  const { authFetch } = useAuth();
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  const generate = async () => {
    if (!prompt.trim() || busy) return;
    setBusy(true);
    setError(null);
    setWarnings([]);
    try {
      const res = await authFetch("/api/rules/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt.trim() }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = j.detail;
        setError(
          typeof detail === "string"
            ? detail
            : detail?.message || "Could not generate a rule from that description.",
        );
        return;
      }
      if (j.warnings?.length) setWarnings(j.warnings);
      const rule: Rule = {
        id: "",
        created_at: new Date().toISOString(),
        ...j.rule,
      };
      onGenerated(rule);
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-accent/40 bg-gradient-to-br from-accent/10 to-transparent p-4 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-base leading-none">✨</span>
        <span className="text-sm font-semibold">Describe your alert</span>
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              generate();
            }
          }}
          placeholder='e.g. "email me if someone loiters by the garage after 10pm"'
          className="flex-1 px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
          disabled={busy}
        />
        <button
          type="button"
          onClick={generate}
          disabled={busy || !prompt.trim()}
          className="px-3 py-2 text-xs rounded-md bg-accent text-accent-foreground font-medium hover:opacity-90 disabled:opacity-50 flex-shrink-0"
        >
          {busy ? "Thinking." : "Build it"}
        </button>
      </div>
      <p className="text-[11px] text-muted-foreground">
        The AI drafts the rule; you review and tweak it in the builder before saving.
      </p>
      {error && <p className="text-xs text-red-400">{error}</p>}
      {warnings.map((w, i) => (
        <p key={i} className="text-[11px] text-amber-400">⚠ {w}</p>
      ))}
    </div>
  );
}
