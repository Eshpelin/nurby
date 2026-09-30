// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, KeywordChipInput } from "./primitives";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

interface SmartTrackSectionProps {
  ptzProfileToken: string;
  setPtzProfileToken: Dispatch<SetStateAction<string>>;
  setSmartTrackDeadzone: Dispatch<SetStateAction<number>>;
  setSmartTrackEnabled: Dispatch<SetStateAction<boolean>>;
  setSmartTrackGain: Dispatch<SetStateAction<number>>;
  setSmartTrackHomePreset: Dispatch<SetStateAction<string>>;
  setSmartTrackIgnore: Dispatch<SetStateAction<string[]>>;
  setSmartTrackLostSeconds: Dispatch<SetStateAction<number>>;
  setSmartTrackMaxSpeed: Dispatch<SetStateAction<number>>;
  setSmartTrackMinConfidence: Dispatch<SetStateAction<number>>;
  setSmartTrackMoveBudget: Dispatch<SetStateAction<number>>;
  setSmartTrackPriority: Dispatch<SetStateAction<string[]>>;
  setSmartTrackTargets: Dispatch<SetStateAction<string[]>>;
  setSmartTrackZoom: Dispatch<SetStateAction<boolean>>;
  smartTrackDeadzone: number;
  smartTrackEnabled: boolean;
  smartTrackGain: number;
  smartTrackHomePreset: string;
  smartTrackIgnore: string[];
  smartTrackLostSeconds: number;
  smartTrackMaxSpeed: number;
  smartTrackMinConfidence: number;
  smartTrackMoveBudget: number;
  smartTrackPresets: { token: string; name: string }[];
  smartTrackPriority: string[];
  smartTrackTargets: string[];
  smartTrackZoom: boolean;
}

export function SmartTrackSection({
  ptzProfileToken,
  setPtzProfileToken,
  setSmartTrackDeadzone,
  setSmartTrackEnabled,
  setSmartTrackGain,
  setSmartTrackHomePreset,
  setSmartTrackIgnore,
  setSmartTrackLostSeconds,
  setSmartTrackMaxSpeed,
  setSmartTrackMinConfidence,
  setSmartTrackMoveBudget,
  setSmartTrackPriority,
  setSmartTrackTargets,
  setSmartTrackZoom,
  smartTrackDeadzone,
  smartTrackEnabled,
  smartTrackGain,
  smartTrackHomePreset,
  smartTrackIgnore,
  smartTrackLostSeconds,
  smartTrackMaxSpeed,
  smartTrackMinConfidence,
  smartTrackMoveBudget,
  smartTrackPresets,
  smartTrackPriority,
  smartTrackTargets,
  smartTrackZoom,
}: SmartTrackSectionProps) {
  const { user } = useAuth();
  const t = (key: string) => translate(user?.locale, key);
  return (
          <Section
            title={t("camera_settings.smart_track.title")}
          advanced
            description={t("camera_settings.smart_track.description")}
          >
            <FieldRow label={t("camera_settings.smart_track.enabled")} hint={t("camera_settings.smart_track.enabled_hint")}>
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={smartTrackEnabled}
                  onChange={(e) => setSmartTrackEnabled(e.target.checked)}
                  className="accent-accent"
                />
                <span className="text-sm">{smartTrackEnabled ? t("camera_settings.smart_track.following") : t("camera_settings.smart_track.off")}</span>
              </label>
            </FieldRow>

            {smartTrackEnabled && (
              <>
                <FieldRow label={t("camera_settings.smart_track.targets")} hint={t("camera_settings.smart_track.targets_hint")}>
                  <KeywordChipInput
                    values={smartTrackTargets}
                    onChange={setSmartTrackTargets}
                    placeholder={t("camera_settings.smart_track.targets_placeholder")}
                  />
                </FieldRow>

                <FieldRow label={t("camera_settings.smart_track.ignore")} hint={t("camera_settings.smart_track.ignore_hint")}>
                  <KeywordChipInput
                    values={smartTrackIgnore}
                    onChange={setSmartTrackIgnore}
                    placeholder={t("camera_settings.smart_track.ignore_placeholder")}
                  />
                </FieldRow>

                <FieldRow label={t("camera_settings.smart_track.priority")} hint={t("camera_settings.smart_track.priority_hint")}>
                  <KeywordChipInput
                    values={smartTrackPriority}
                    onChange={setSmartTrackPriority}
                    placeholder={t("camera_settings.smart_track.targets_placeholder")}
                  />
                </FieldRow>

                <FieldRow label={t("camera_settings.smart_track.home")} hint={t("camera_settings.smart_track.home_hint")}>
                  <select
                    value={smartTrackHomePreset}
                    onChange={(e) => setSmartTrackHomePreset(e.target.value)}
                    className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm"
                  >
                    <option value="">{t("camera_settings.smart_track.no_home")}</option>
                    {smartTrackPresets.map((p) => (
                      <option key={p.token} value={p.token}>{p.name} ({p.token})</option>
                    ))}
                  </select>
                </FieldRow>

                <FieldRow label={t("camera_settings.smart_track.lost_window")} hint={t("camera_settings.smart_track.lost_window_hint")}>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={1}
                      max={30}
                      step={1}
                      value={smartTrackLostSeconds}
                      onChange={(e) => setSmartTrackLostSeconds(Number(e.target.value))}
                      className="flex-1 accent-accent"
                    />
                    <span className="font-mono text-xs text-muted-foreground w-12 text-right">
                      {smartTrackLostSeconds}s
                    </span>
                  </div>
                </FieldRow>

                <FieldRow label={t("camera_settings.smart_track.auto_zoom")} hint={t("camera_settings.smart_track.auto_zoom_hint")}>
                  <label className="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={smartTrackZoom}
                      onChange={(e) => setSmartTrackZoom(e.target.checked)}
                      className="accent-accent"
                    />
                    <span className="text-sm">{smartTrackZoom ? t("camera_settings.smart_track.zoom_on") : t("camera_settings.smart_track.zoom_fixed")}</span>
                  </label>
                </FieldRow>

                <FieldRow label={t("camera_settings.smart_track.deadzone")} hint={t("camera_settings.smart_track.deadzone_hint")}>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={0.05}
                      max={0.4}
                      step={0.01}
                      value={smartTrackDeadzone}
                      onChange={(e) => setSmartTrackDeadzone(Number(e.target.value))}
                      className="flex-1 accent-accent"
                    />
                    <span className="font-mono text-xs text-muted-foreground w-12 text-right">
                      {smartTrackDeadzone.toFixed(2)}
                    </span>
                  </div>
                </FieldRow>

                <FieldRow label={t("camera_settings.smart_track.max_speed")} hint={t("camera_settings.smart_track.max_speed_hint")}>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={0.1}
                      max={1.0}
                      step={0.05}
                      value={smartTrackMaxSpeed}
                      onChange={(e) => setSmartTrackMaxSpeed(Number(e.target.value))}
                      className="flex-1 accent-accent"
                    />
                    <span className="font-mono text-xs text-muted-foreground w-12 text-right">
                      {smartTrackMaxSpeed.toFixed(2)}
                    </span>
                  </div>
                </FieldRow>

                <FieldRow label={t("camera_settings.smart_track.gain")} hint={t("camera_settings.smart_track.gain_hint")}>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={0.5}
                      max={3.0}
                      step={0.1}
                      value={smartTrackGain}
                      onChange={(e) => setSmartTrackGain(Number(e.target.value))}
                      className="flex-1 accent-accent"
                    />
                    <span className="font-mono text-xs text-muted-foreground w-12 text-right">
                      {smartTrackGain.toFixed(1)}
                    </span>
                  </div>
                </FieldRow>

                <FieldRow label={t("camera_settings.smart_track.min_confidence")} hint={t("camera_settings.smart_track.min_confidence_hint")}>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={0.2}
                      max={0.9}
                      step={0.05}
                      value={smartTrackMinConfidence}
                      onChange={(e) => setSmartTrackMinConfidence(Number(e.target.value))}
                      className="flex-1 accent-accent"
                    />
                    <span className="font-mono text-xs text-muted-foreground w-12 text-right">
                      {smartTrackMinConfidence.toFixed(2)}
                    </span>
                  </div>
                </FieldRow>

                <FieldRow label={t("camera_settings.smart_track.move_budget")} hint={t("camera_settings.smart_track.move_budget_hint")}>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={5}
                      max={120}
                      step={5}
                      value={smartTrackMoveBudget}
                      onChange={(e) => setSmartTrackMoveBudget(Number(e.target.value))}
                      className="flex-1 accent-accent"
                    />
                    <span className="font-mono text-xs text-muted-foreground w-20 text-right">
                      {smartTrackMoveBudget}{t("camera_settings.smart_track.per_minute")}
                    </span>
                  </div>
                </FieldRow>

                <FieldRow label={t("camera_settings.smart_track.profile_token")} hint={t("camera_settings.smart_track.profile_token_hint")}>
                  <input
                    type="text"
                    value={ptzProfileToken}
                    onChange={(e) => setPtzProfileToken(e.target.value)}
                    placeholder={t("camera_settings.smart_track.profile_placeholder")}
                    className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm font-mono"
                  />
                </FieldRow>
              </>
            )}
          </Section>
  );
}
