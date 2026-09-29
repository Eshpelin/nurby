// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, inputClass } from "./primitives";
import { translate, type Locale } from "@/lib/i18n";

interface GeneralSectionProps {
  locale: Locale;
  locationLabel: string;
  name: string;
  setLocationLabel: Dispatch<SetStateAction<string>>;
  setName: Dispatch<SetStateAction<string>>;
}

export function GeneralSection({
  locale,
  locationLabel,
  name,
  setLocationLabel,
  setName,
}: GeneralSectionProps) {
  const t = (key: string) => translate(locale, key);
  return (
        <Section title={t("camera.general.title")} description={t("camera.general.description")}>
          <FieldRow label={t("camera.general.name")}>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputClass}
            />
          </FieldRow>

          <FieldRow label={t("camera.general.location_label")} hint={t("camera.general.location_hint")}>
            <input
              type="text"
              value={locationLabel}
              onChange={(e) => setLocationLabel(e.target.value)}
              placeholder={t("camera.general.location_placeholder")}
              className={inputClass}
            />
          </FieldRow>
        </Section>
  );
}
