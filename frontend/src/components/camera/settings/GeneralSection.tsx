// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, inputClass } from "./primitives";

interface GeneralSectionProps {
  locationLabel: string;
  name: string;
  setLocationLabel: Dispatch<SetStateAction<string>>;
  setName: Dispatch<SetStateAction<string>>;
}

export function GeneralSection({
  locationLabel,
  name,
  setLocationLabel,
  setName,
}: GeneralSectionProps) {
  return (
        <Section title="General" description="Basic camera identification and location">
          <FieldRow label="Name">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={inputClass}
            />
          </FieldRow>

          <FieldRow label="Location Label" hint="Where this camera is">
            <input
              type="text"
              value={locationLabel}
              onChange={(e) => setLocationLabel(e.target.value)}
              placeholder="e.g. Front porch"
              className={inputClass}
            />
          </FieldRow>
        </Section>
  );
}
