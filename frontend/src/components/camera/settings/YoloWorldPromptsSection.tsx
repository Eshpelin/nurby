// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, KeywordChipInput } from "./primitives";

interface YoloWorldPromptsSectionProps {
  setYoloWorldPrompts: Dispatch<SetStateAction<string[]>>;
  yoloWorldPrompts: string[];
}

export function YoloWorldPromptsSection({
  setYoloWorldPrompts,
  yoloWorldPrompts,
}: YoloWorldPromptsSectionProps) {
  return (
          <Section
            title="Open-vocabulary prompts"
          advanced
            description="When a YOLO-World model is in this camera's detection list, these phrases drive what it detects. Plain English. Add anything you want flagged."
          >
            <FieldRow label="Class names to detect">
              <KeywordChipInput
                values={yoloWorldPrompts}
                onChange={setYoloWorldPrompts}
                placeholder="person, package, delivery driver, raccoon, ..."
              />
              <p className="text-[11px] text-muted-foreground mt-1.5">
                Each phrase becomes a detection class. Combine with the
                existing Detection Models picker to pair YOLO-World
                with a faster general-purpose model.
              </p>
            </FieldRow>
          </Section>
  );
}
