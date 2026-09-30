"use client";

import { type ProviderOption, type VerifyDraft } from "../types";
import { StyledSelect } from "../StyledSelect";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

export interface VerifyEditorProps {
  draft: VerifyDraft;
  onChange: (next: VerifyDraft) => void;
  providers: ProviderOption[];
}

export function VerifyEditor({ draft, onChange, providers }: VerifyEditorProps) {
  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const d = draft;
  const set = (patch: Partial<VerifyDraft>) => onChange({ ...d, ...patch });
  return (
    <div className="space-y-3">
      <div className="text-[11px] text-muted-foreground bg-muted/50 rounded px-2 py-1.5">
        {t("rules.verify.help")}
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">
          {t("rules.verify.question")}
        </label>
        <textarea
          value={d.question}
          onChange={(e) => set({ question: e.target.value })}
          rows={3}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm resize-y"
          placeholder={t("rules.verify.question_placeholder")}
        />
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">
          {t("rules.verify.minimum_confidence", { value: d.minConfidence.toFixed(2) })}
        </label>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={d.minConfidence}
          onChange={(e) => set({ minConfidence: parseFloat(e.target.value) })}
          className="w-full accent-green-500"
        />
        <div className="text-[10px] text-muted-foreground">
          {t("rules.verify.confidence_help")}
        </div>
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">
          {t("rules.verify.on_fail")}
        </label>
        <StyledSelect
          value={d.onFail}
          options={[
            { value: "stop", label: t("rules.verify.stop") },
            { value: "continue", label: t("rules.verify.continue") },
          ]}
          onChange={(v) => set({ onFail: v as VerifyDraft["onFail"] })}
        />
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">
          {t("rules.verify.provider")}
        </label>
        <StyledSelect
          value={d.providerId || ""}
          options={[
            { value: "", label: t("rules.verify.default_provider") },
            ...providers.map((p) => ({ value: p.id, label: `${p.name} (${p.kind})` })),
          ]}
          onChange={(v) => set({ providerId: v })}
        />
        <div className="text-[10px] text-muted-foreground">
          {t("rules.verify.provider_help")}
        </div>
      </div>
    </div>
  );
}

export default VerifyEditor;
