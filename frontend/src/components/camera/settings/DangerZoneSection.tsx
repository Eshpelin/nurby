// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section } from "./primitives";
import { translate, type Locale } from "@/lib/i18n";

interface DangerZoneSectionProps {
  locale: Locale;
  deleteConfirm: boolean;
  handleDelete: () => void;
  setDeleteConfirm: Dispatch<SetStateAction<boolean>>;
}

export function DangerZoneSection({
  locale,
  deleteConfirm,
  handleDelete,
  setDeleteConfirm,
}: DangerZoneSectionProps) {
  const t = (key: string) => translate(locale, key);
  return (
        <Section title={t("camera.danger_zone.title")}>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-foreground">{t("camera.danger_zone.delete_camera")}</p>
              <p className="text-xs text-muted-foreground">
                {t("camera.danger_zone.description")}
              </p>
            </div>
            {!deleteConfirm ? (
              <button
                onClick={() => setDeleteConfirm(true)}
                className="px-3 py-1.5 text-sm rounded-md border border-danger/30 text-danger hover:bg-danger/10 transition-colors"
              >
                {t("common.delete")}
              </button>
            ) : (
              <div className="flex gap-2">
                <button
                  onClick={() => setDeleteConfirm(false)}
                  className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
                >
                  {t("common.cancel")}
                </button>
                <button
                  onClick={handleDelete}
                  className="px-3 py-1.5 text-sm rounded-md bg-danger text-white hover:opacity-90 transition-opacity"
                >
                  {t("camera.danger_zone.confirm_delete")}
                </button>
              </div>
            )}
          </div>
        </Section>
  );
}
