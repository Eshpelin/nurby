// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, KeywordChipInput } from "./primitives";
import { translate, type Locale } from "@/lib/i18n";

interface YoloWorldPromptsSectionProps {
  locale: Locale;
  setYoloWorldPrompts: Dispatch<SetStateAction<string[]>>;
  yoloWorldPrompts: string[];
}

export function YoloWorldPromptsSection({
  locale,
  setYoloWorldPrompts,
  yoloWorldPrompts,
}: YoloWorldPromptsSectionProps) {
  const t = (key: string) => translate(locale, key);
  return (
          <Section
            title={t("camera.yolo_world.title")}
          advanced
            description={t("camera.yolo_world.description")}
          >
            <FieldRow label={t("camera.yolo_world.class_names")}>
              <KeywordChipInput
                values={yoloWorldPrompts}
                onChange={setYoloWorldPrompts}
                placeholder={t("camera.yolo_world.placeholder")}
              />
              <p className="text-[11px] text-muted-foreground mt-1.5">
                {t("camera.yolo_world.help")}
              </p>
            </FieldRow>
          </Section>
  );
}
