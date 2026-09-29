// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow } from "./primitives";
import { translate, type Locale } from "@/lib/i18n";

interface RetentionSectionProps {
  locale: Locale;
  retentionDays: number;
  retentionGb: number;
  retentionMode: string;
  setRetentionDays: Dispatch<SetStateAction<number>>;
  setRetentionGb: Dispatch<SetStateAction<number>>;
  setRetentionMode: Dispatch<SetStateAction<string>>;
  /** Archive destination name when archiving is on (issue #270). Footage
   *  then moves there instead of being deleted. */
  archiveName?: string | null;
}

export function RetentionSection({
  locale,
  retentionDays,
  retentionGb,
  retentionMode,
  setRetentionDays,
  setRetentionGb,
  setRetentionMode,
  archiveName = null,
}: RetentionSectionProps) {
  const t = (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
  const leaves = archiveName ? t("camera.retention.move_to", { archive: archiveName }) : t("camera.retention.be_deleted");
  return (
        <Section
          title={t("camera.retention.title")}
          description={
            archiveName
              ? t("camera.retention.description_archive", { archive: archiveName })
              : t("camera.retention.description_delete")
          }
        >
          <FieldRow label={t("camera.retention.policy_label")}>
            <div className="flex gap-1.5">
              {([
                { value: "none", label: t("camera.retention.keep_forever") },
                { value: "time", label: t("camera.retention.by_age") },
                { value: "size", label: t("camera.retention.by_size") },
              ] as const).map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setRetentionMode(opt.value)}
                  className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${
                    retentionMode === opt.value
                      ? "border-accent bg-accent/10 text-accent-foreground"
                      : "border-border hover:border-muted-foreground text-muted-foreground"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </FieldRow>

          {retentionMode === "time" && (
            <FieldRow
              label={archiveName ? t("camera.retention.keep_machine_for") : t("camera.retention.keep_recordings_for")}
              hint={archiveName ? t("camera.retention.older_move", { archive: archiveName }) : t("camera.retention.older_delete")}
            >
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={1}
                  max={365}
                  step={1}
                  value={retentionDays}
                  onChange={(e) => setRetentionDays(Number(e.target.value))}
                  className="flex-1 accent-accent"
                />
                <span className="font-mono text-xs text-muted-foreground w-20 text-right">
                  {retentionDays < 30
                    ? `${retentionDays}d`
                    : retentionDays < 365
                      ? `${Math.floor(retentionDays / 30)}mo ${retentionDays % 30 ? `${retentionDays % 30}d` : ""}`.trim()
                      : `${Math.floor(retentionDays / 365)}y`}
                </span>
              </div>
              <div className="flex gap-2 mt-2">
                {[7, 14, 30, 90, 180, 365].map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setRetentionDays(d)}
                    className={`px-2 py-0.5 text-[11px] rounded border transition-colors ${
                      retentionDays === d
                        ? "border-accent text-accent-foreground"
                        : "border-border text-muted-foreground hover:border-muted-foreground"
                    }`}
                  >
                    {d < 30 ? `${d}d` : d < 365 ? `${d / 30}mo` : "1y"}
                  </button>
                ))}
              </div>
            </FieldRow>
          )}

          {retentionMode === "size" && (
            <FieldRow
              label={archiveName ? t("camera.retention.max_machine") : t("camera.retention.max_storage")}
              hint={archiveName ? t("camera.retention.oldest_move", { archive: archiveName }) : t("camera.retention.oldest_delete")}
            >
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={1}
                  max={500}
                  step={1}
                  value={retentionGb}
                  onChange={(e) => setRetentionGb(Number(e.target.value))}
                  className="flex-1 accent-accent"
                />
                <span className="font-mono text-xs text-muted-foreground w-16 text-right">
                  {retentionGb < 1000 ? `${retentionGb} GB` : `${(retentionGb / 1000).toFixed(1)} TB`}
                </span>
              </div>
              <div className="flex gap-2 mt-2">
                {[5, 10, 25, 50, 100, 250, 500].map((g) => (
                  <button
                    key={g}
                    type="button"
                    onClick={() => setRetentionGb(g)}
                    className={`px-2 py-0.5 text-[11px] rounded border transition-colors ${
                      retentionGb === g
                        ? "border-accent text-accent-foreground"
                        : "border-border text-muted-foreground hover:border-muted-foreground"
                    }`}
                  >
                    {g} GB
                  </button>
                ))}
              </div>
            </FieldRow>
          )}

          {retentionMode !== "none" && (
            <div
              className={`rounded-md px-3 py-2 ${
                archiveName ? "bg-muted/30 border border-border" : "bg-warning/5 border border-warning/20"
              }`}
            >
              <p className={`text-xs ${archiveName ? "text-muted-foreground" : "text-warning"}`}>
                {retentionMode === "time"
                  ? t("camera.retention.age_warning", { days: retentionDays, plural: retentionDays !== 1 ? "s" : "", action: archiveName ? leaves : t("camera.retention.auto_delete") })
                  : t("camera.retention.size_warning", { size: retentionGb, action: archiveName ? leaves : t("camera.retention.delete_make_space") })}
              </p>
            </div>
          )}

          {retentionMode === "none" && archiveName && (
            <p className="text-[11px] text-muted-foreground">
              {t("camera.retention.keep_all_help", { archive: archiveName })}
            </p>
          )}
        </Section>
  );
}
