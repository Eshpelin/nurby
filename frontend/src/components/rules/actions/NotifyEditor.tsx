"use client";

import { type NotifyDraft } from "../types";
import { StyledSelect } from "../StyledSelect";
import { VarInserter, type VarSpec } from "./VarInserter";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

export interface NotifyEditorProps {
  draft: NotifyDraft;
  onChange: (next: NotifyDraft) => void;
  availableVars: VarSpec[];
}

export function NotifyEditor({ draft, onChange, availableVars }: NotifyEditorProps) {
  const { user } = useAuth();
  const t = (key: string) => translate(user?.locale, key);
  const d = draft;
  const set = (patch: Partial<NotifyDraft>) => onChange({ ...d, ...patch });
  return (
    <>
      <input
        type="text"
        value={d.message}
        onChange={(e) => set({ message: e.target.value })}
        className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
        placeholder={t("rules.notify.placeholder")}
      />
      <StyledSelect
        value={d.severity}
        options={[
          { value: "info", label: t("rules.notify.info") },
          { value: "warning", label: t("rules.notify.warning") },
          { value: "critical", label: t("rules.notify.critical") },
        ]}
        onChange={(v) => set({ severity: v })}
      />
      <div className="flex items-center gap-2">
        <VarInserter
          vars={availableVars}
          onInsert={(tok) => set({ message: d.message + tok })}
        />
      </div>
    </>
  );
}

export default NotifyEditor;
