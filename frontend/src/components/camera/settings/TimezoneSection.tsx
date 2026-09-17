// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, inputClass } from "./primitives";
import { timezoneOptions } from "@/lib/timezones";

interface TimezoneSectionProps {
  cameraTimezone: string;
  setCameraTimezone: Dispatch<SetStateAction<string>>;
}

export function TimezoneSection({
  cameraTimezone,
  setCameraTimezone,
}: TimezoneSectionProps) {
  return (
        <Section
          title="Timezone"
          advanced
          description="Used to render timestamps in this camera's local time. Anchors per-camera scheduling too."
        >
          <FieldRow label="Timezone">
            <select
              value={cameraTimezone}
              onChange={(e) => setCameraTimezone(e.target.value)}
              className={inputClass}
            >
              <option value="">(use system default)</option>
              {timezoneOptions().map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
            <p className="text-[11px] text-muted-foreground mt-1">
              Pick the timezone where this camera is physically located.
              Leave blank to follow the household-wide system timezone
              from Settings.
            </p>
          </FieldRow>
        </Section>
  );
}
