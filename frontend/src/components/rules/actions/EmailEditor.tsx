"use client";

import { TEMPLATE_VARIABLES, type EmailDraft } from "../types";
import { VarInserter, type VarSpec } from "./VarInserter";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

export interface EmailEditorProps {
  draft: EmailDraft;
  onChange: (next: EmailDraft) => void;
  availableVars: VarSpec[];
}

export function EmailEditor({ draft, onChange, availableVars }: EmailEditorProps) {
  const { user } = useAuth();
  const t = (key: string) => translate(user?.locale, key);
  const d = draft;
  const set = (patch: Partial<EmailDraft>) => onChange({ ...d, ...patch });
  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs text-muted-foreground block mb-1">{t("rules.email.recipient")}</label>
        <input
          type="email"
          value={d.to}
          onChange={(e) => set({ to: e.target.value })}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
          placeholder={t("rules.email.recipient_placeholder")}
        />
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">{t("rules.email.subject")}</label>
        <input
          type="text"
          value={d.subject}
          onChange={(e) => set({ subject: e.target.value })}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
          placeholder={t("rules.email.subject_placeholder")}
        />
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">{t("rules.email.body")}</label>
        <textarea
          value={d.body}
          onChange={(e) => set({ body: e.target.value })}
          rows={4}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm resize-y"
          placeholder={t("rules.email.body_placeholder")}
        />
      </div>
      <div className="flex flex-wrap gap-1 items-center">
        {TEMPLATE_VARIABLES.map((v) => (
          <button
            key={v.key}
            type="button"
            title={v.desc}
            onClick={() => set({ body: d.body + `{{${v.key}}}` })}
            className="px-1.5 py-0.5 text-[10px] rounded border border-border hover:bg-muted text-muted-foreground font-mono"
          >
            {`{{${v.key}}}`}
          </button>
        ))}
        <VarInserter
          vars={availableVars}
          onInsert={(tok) => set({ body: d.body + tok })}
        />
      </div>
      <div className="text-[10px] text-muted-foreground bg-muted/50 rounded px-2 py-1.5">
        {t("rules.email.smtp_hint")}
      </div>
    </div>
  );
}

export default EmailEditor;
