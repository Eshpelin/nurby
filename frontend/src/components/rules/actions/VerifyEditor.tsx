"use client";

import { type ProviderOption, type VerifyDraft } from "../types";
import { StyledSelect } from "../StyledSelect";

export interface VerifyEditorProps {
  draft: VerifyDraft;
  onChange: (next: VerifyDraft) => void;
  providers: ProviderOption[];
}

export function VerifyEditor({ draft, onChange, providers }: VerifyEditorProps) {
  const d = draft;
  const set = (patch: Partial<VerifyDraft>) => onChange({ ...d, ...patch });
  return (
    <div className="space-y-3">
      <div className="text-[11px] text-muted-foreground bg-muted/50 rounded px-2 py-1.5">
        Before the rest of this rule&apos;s actions run, ask an AI to confirm the
        trigger is real. If it can&apos;t confirm, the rule stops.
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">
          Confirmation question
        </label>
        <textarea
          value={d.question}
          onChange={(e) => set({ question: e.target.value })}
          rows={3}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm resize-y"
          placeholder="Is there actually a person at the door, not a shadow or reflection?"
        />
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">
          Minimum confidence. {d.minConfidence.toFixed(2)}
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
          The AI must answer yes with at least this confidence to pass.
        </div>
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">
          If the AI cannot confirm
        </label>
        <StyledSelect
          value={d.onFail}
          options={[
            { value: "stop", label: "Stop the rule" },
            { value: "continue", label: "Continue anyway" },
          ]}
          onChange={(v) => set({ onFail: v as VerifyDraft["onFail"] })}
        />
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">
          AI provider (optional)
        </label>
        <StyledSelect
          value={d.providerId || ""}
          options={[
            { value: "", label: "Default (the camera's VLM)" },
            ...providers.map((p) => ({ value: p.id, label: `${p.name} (${p.kind})` })),
          ]}
          onChange={(v) => set({ providerId: v })}
        />
        <div className="text-[10px] text-muted-foreground">
          Which model answers this check. Leave default unless you want a
          specific one (e.g. a sharper cloud model for a critical confirmation).
        </div>
      </div>
    </div>
  );
}

export default VerifyEditor;
