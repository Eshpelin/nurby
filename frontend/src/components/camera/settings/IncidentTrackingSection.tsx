// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, Toggle } from "./primitives";
import { formatInterval } from "./format";
import { translate, type Locale } from "@/lib/i18n";

interface IncidentTrackingSectionProps {
  locale: Locale;
  incidentIdleSeconds: number;
  incidentTrackingEnabled: boolean;
  setIncidentIdleSeconds: Dispatch<SetStateAction<number>>;
  setIncidentTrackingEnabled: Dispatch<SetStateAction<boolean>>;
}

export function IncidentTrackingSection({
  locale,
  incidentIdleSeconds,
  incidentTrackingEnabled,
  setIncidentIdleSeconds,
  setIncidentTrackingEnabled,
}: IncidentTrackingSectionProps) {
  const t = (key: string) => translate(locale, key);
  return (
        <Section
          title={t("camera.incident_tracking.title")}
          advanced
          description={t("camera.incident_tracking.description")}
        >
          <FieldRow label={t("camera.incident_tracking.tracking_label")}>
            <Toggle
              checked={incidentTrackingEnabled}
              onChange={setIncidentTrackingEnabled}
              label={incidentTrackingEnabled ? t("common.on") : t("common.off")}
            />
          </FieldRow>

          {incidentTrackingEnabled && (
            <FieldRow label={t("camera.incident_tracking.idle_label")} hint={t("camera.incident_tracking.idle_hint")}>
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
