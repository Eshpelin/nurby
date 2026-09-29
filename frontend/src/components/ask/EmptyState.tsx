"use client";

import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

// Shown when ChatHistory is empty AND nothing is in flight. Four
// persona cards prefill + submit the composer so a first-time user
// experiences the loop in one click.

interface EmptyStateProps {
  onPersonaClick: (q: string) => void;
}

const PERSONAS: Array<{ emoji: string; text: string }> = [
  { emoji: "📦", text: "Did a package arrive at the front door today?" },
  { emoji: "👶", text: "Was the baby crying in the last hour?" },
  { emoji: "🐕", text: "Where's the dog right now?" },
  { emoji: "🚪", text: "Anyone at the door after midnight last night?" },
];

export default function EmptyState({ onPersonaClick }: EmptyStateProps) {
  const { user } = useAuth();
  const t = (key: string) => translate(user?.locale, key);
  return (
    <div className="max-w-2xl mx-auto px-6 py-12 space-y-8">
      <div className="text-center space-y-2">
        <div className="text-3xl">✨</div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("ask.title")}</h1>
        <p className="text-sm text-muted-foreground leading-relaxed">
          {t("ask.empty_description")}
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {PERSONAS.map((p) => (
          <button
            key={p.text}
            type="button"
            onClick={() => onPersonaClick(p.text)}
            aria-label={`${t("ask.try_example")} ${p.text}`}
            className="text-left p-4 rounded-lg border border-border bg-card hover:bg-muted/60 transition-colors"
          >
            <div className="text-xl mb-2">{p.emoji}</div>
            <div className="text-sm">{p.text}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
