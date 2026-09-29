"use client";

// First-use modal that nudges the user to pick a model. Not blocking
// for subsequent visits. Dismisses on Continue or Escape.

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";
import type { ProviderModel } from "./types";

interface OnboardingModalProps {
  open: boolean;
  providers: ProviderModel[];
  onPick: (m: ProviderModel) => void;
  onClose: () => void;
}

export default function OnboardingModal({ open, providers, onPick, onClose }: OnboardingModalProps) {
  const { user } = useAuth();
  const t = (key: string) => translate(user?.locale, key);
  const [picked, setPicked] = useState<ProviderModel | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[110] bg-black/70 flex items-center justify-center p-6">
      <div className="bg-card border border-border rounded-lg max-w-md w-full p-5 space-y-4">
        <div>
          <h2 className="text-lg font-semibold">{t("ask.pick_model_title")}</h2>
          <p className="text-xs text-muted-foreground mt-1">
            {t("ask.pick_model_body")}
          </p>
        </div>
        <div className="max-h-72 overflow-auto space-y-1 border border-border rounded">
          {providers.length === 0 ? (
            <div className="p-3 text-xs text-muted-foreground">
              {t("ask.no_providers_setup")}
            </div>
          ) : (
            providers.map((m) => {
              const active = picked?.provider_id === m.provider_id && picked?.id === m.id;
              return (
                <button
                  key={`${m.provider_id}:${m.id}`}
                  type="button"
                  onClick={() => setPicked(m)}
                  className={`w-full text-left px-3 py-2 text-xs hover:bg-muted ${active ? "bg-muted" : ""}`}
                >
                  <div className="font-medium flex items-center gap-1.5">
                    {m.name}
                    {m.recommended && (
                      <span className="text-[9px] px-1 py-px rounded bg-accent/20 text-accent border border-accent/30">
                        {t("ask.recommended")}
                      </span>
                    )}
                  </div>
                  <div className="text-[10px] font-mono text-muted-foreground">
                    {m.kind} · {m.provider_name}
                  </div>
                </button>
              );
            })
          )}
        </div>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted"
            aria-label={t("ask.skip_onboarding")}
          >
            {t("ask.skip")}
          </button>
          <button
            type="button"
            onClick={() => picked && onPick(picked)}
            disabled={!picked}
            className="px-3 py-1.5 text-xs rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50"
            aria-label={t("ask.continue_with_model")}
          >
            {t("ask.continue")}
          </button>
        </div>
      </div>
    </div>
  );
}
