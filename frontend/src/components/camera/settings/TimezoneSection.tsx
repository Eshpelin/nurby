// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, inputClass } from "./primitives";
import { timezoneOptions } from "@/lib/timezones";
import { translate, type Locale } from "@/lib/i18n";

interface TimezoneSectionProps {
  locale: Locale;
  cameraTimezone: string;
  setCameraTimezone: Dispatch<SetStateAction<string>>;
}

export function TimezoneSection({
  locale,
  cameraTimezone,
  setCameraTimezone,
}: TimezoneSectionProps) {
  const t = (key: string) => translate(locale, key);
  return (
        <Section
          title={t("camera.timezone.title")}
          advanced
          description={t("camera.timezone.description")}
        >
          <FieldRow label={t("camera.timezone.label")}>
            <select
              value={cameraTimezone}
              onChange={(e) => setCameraTimezone(e.target.value)}
              className={inputClass}
            >
              <option value="">{t("camera.timezone.system_default")}</option>
              {timezoneOptions().map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
            <p className="text-[11px] text-muted-foreground mt-1">
              {t("camera.timezone.help")}
            </p>
          </FieldRow>
        </Section>
  );
}
