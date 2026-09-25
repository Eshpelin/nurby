// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, Toggle } from "./primitives";
import { formatInterval } from "./format";

interface IncidentTrackingSectionProps {
  incidentIdleSeconds: number;
  incidentTrackingEnabled: boolean;
  setIncidentIdleSeconds: Dispatch<SetStateAction<number>>;
  setIncidentTrackingEnabled: Dispatch<SetStateAction<boolean>>;
}

export function IncidentTrackingSection({
  incidentIdleSeconds,
  incidentTrackingEnabled,
  setIncidentIdleSeconds,
  setIncidentTrackingEnabled,
}: IncidentTrackingSectionProps) {
  return (
        <Section
          title="Incident tracking"
          advanced
          description="Group repeated observations of the same person or object on this camera into one persistent rolling card with a stable id, live updates, and a final summary on close."
        >
          <FieldRow label="Tracking">
            <Toggle
              checked={incidentTrackingEnabled}
              onChange={setIncidentTrackingEnabled}
              label={incidentTrackingEnabled ? "On" : "Off"}
            />
          </FieldRow>

          {incidentTrackingEnabled && (
            <FieldRow label="Idle window" hint="Seconds without a matching detection before the incident closes and gets summarized.">
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={60}
                  max={3600}
                  step={30}
                  value={incidentIdleSeconds}
                  onChange={(e) => setIncidentIdleSeconds(Number(e.target.value))}
                  className="flex-1 accent-accent"
                />
                <span className="font-mono text-xs text-muted-foreground w-20 text-right">
                  {formatInterval(incidentIdleSeconds)}
                </span>
              </div>
            </FieldRow>
          )}
        </Section>
  );
}
