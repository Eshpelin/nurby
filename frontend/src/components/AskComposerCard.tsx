"use client";

// Compact "Ask Nurby" composer for the dashboard. Routes to /ask?q=…,
// which auto-sends the question, so chat stops being a hidden nav tab.

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMentions } from "@/components/mentions/useMentions";
import { MentionDropdown } from "@/components/mentions/MentionDropdown";

const CHIPS = [
  { label: "📦 Set up a package alert", q: "Create an alert that tells me when a package arrives at the front door" },
  { label: "🕵️ What happened today?", q: "What happened today?" },
  { label: "🩺 Is everything working?", q: "Run a health check and tell me if anything is broken" },
];

export function AskComposerCard() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const mention = useMentions(inputRef, q, setQ);

  const go = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    // Mentions ride the handoff to /ask, which auto-sends ?q= questions.
    const mentions = mention.activeMentions(trimmed);
    const m = mentions.length ? `&m=${encodeURIComponent(JSON.stringify(mentions))}` : "";
    router.push(`/ask?q=${encodeURIComponent(trimmed)}${m}`);
  };

  return (
    <div className="rounded-lg border border-border bg-card p-3 mb-4">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <MentionDropdown
            open={mention.open}
            items={mention.items}
            highlight={mention.highlight}
            onSelect={mention.select}
            placement="below"
          />
          <input
            ref={inputRef}
            type="text"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              requestAnimationFrame(mention.refresh);
            }}
            onClick={mention.refresh}
            onBlur={() => setTimeout(mention.close, 100)}
            onKeyDown={(e) => {
              if (mention.onKeyDown(e)) return;
              if (e.key === "Enter") {
                e.preventDefault();
                go(q);
              }
            }}
            placeholder='Ask Nurby anything. Type @ to tag a person, camera or device.'
            className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
          />
        </div>
        <button
          type="button"
          onClick={() => go(q)}
          disabled={!q.trim()}
          className="px-3 py-2 text-xs rounded-md bg-accent text-accent-foreground font-medium hover:opacity-90 disabled:opacity-50 flex-shrink-0"
        >
          Ask
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5 mt-2">
        {CHIPS.map((c) => (
          <button
            key={c.label}
            type="button"
            onClick={() => go(c.q)}
            className="px-2 py-1 text-[11px] rounded-full border border-border hover:border-accent text-muted-foreground hover:text-foreground transition-colors"
          >
            {c.label}
          </button>
        ))}
      </div>
    </div>
  );
}
