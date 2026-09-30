"use client";

import { StyledSelect } from "./StyledSelect";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

export function ModelClassPicker({
  value,
  onChange,
  activeModels,
  classes,
  loading,
  anyLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  activeModels: string[];
  classes: string[];
  loading: boolean;
  anyLabel: string;
}) {
  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const needsModel = activeModels.length === 0;
  const options = [
    { value: "", label: anyLabel },
    ...classes.map((l) => ({ value: l, label: l })),
  ];

  return (
    <div className="space-y-2">
      {activeModels.length > 0 && (
        <div className="flex flex-wrap gap-1">
          <span className="text-[10px] text-muted-foreground self-center">{t("rules.model_picker.labels_from")}</span>
          {activeModels.map((m) => (
            <span key={m} className="px-1.5 py-0.5 text-[10px] font-mono rounded border border-border bg-muted/30 text-muted-foreground">
              {m}
            </span>
          ))}
        </div>
      )}
      {needsModel ? (
        <div className="rounded-md border border-dashed border-amber-500/40 bg-amber-500/5 p-2.5 text-[11px] text-amber-300">
          {t("rules.model_picker.no_model_prefix")} <Link href="/" className="underline hover:text-amber-200">{t("rules.model_picker.dashboard")}</Link> {t("rules.model_picker.no_model_suffix")}
        </div>
      ) : loading ? (
        <p className="text-[11px] text-muted-foreground">{t("rules.model_picker.loading")}</p>
      ) : classes.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">
          {t("rules.model_picker.no_classes")}
        </p>
      ) : (
        <StyledSelect value={value} options={options} onChange={onChange} />
      )}
    </div>
  );
}
