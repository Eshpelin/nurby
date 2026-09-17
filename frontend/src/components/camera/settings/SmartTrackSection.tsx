// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, KeywordChipInput } from "./primitives";

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
  return (
          <Section
            title="Smart Track"
          advanced
            description="Auto-follow detections with the camera's PTZ motor. Requires ONVIF pan/tilt support. The camera will keep the target near frame center and return to the home preset after the target leaves for a few seconds."
          >
            <FieldRow label="Enabled" hint="Master switch. Off means manual PTZ only.">
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={smartTrackEnabled}
                  onChange={(e) => setSmartTrackEnabled(e.target.checked)}
                  className="accent-accent"
                />
                <span className="text-sm">{smartTrackEnabled ? "Following" : "Off"}</span>
              </label>
            </FieldRow>

            {smartTrackEnabled && (
              <>
                <FieldRow label="Follow these labels" hint="Detections matching any of these labels are eligible targets. Empty means follow anything not in the ignore list.">
                  <KeywordChipInput
                    values={smartTrackTargets}
                    onChange={setSmartTrackTargets}
                    placeholder="person, cat, ..."
                  />
                </FieldRow>

                <FieldRow label="Never follow" hint="Hard deny. The camera will not chase these. Useful if you have a resident dog.">
                  <KeywordChipInput
                    values={smartTrackIgnore}
                    onChange={setSmartTrackIgnore}
                    placeholder="dog, ..."
                  />
                </FieldRow>

                <FieldRow label="Priority order" hint="When multiple targets are visible, the camera picks the first label in this list. Falls back to bbox area then confidence.">
                  <KeywordChipInput
                    values={smartTrackPriority}
                    onChange={setSmartTrackPriority}
                    placeholder="person, cat, ..."
                  />
                </FieldRow>

                <FieldRow label="Home preset" hint="ONVIF preset to return to when no target has been seen for the lost window. Set presets on the camera itself, then pick one here.">
                  <select
                    value={smartTrackHomePreset}
                    onChange={(e) => setSmartTrackHomePreset(e.target.value)}
                    className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm"
                  >
                    <option value="">No home (just stop)</option>
                    {smartTrackPresets.map((p) => (
                      <option key={p.token} value={p.token}>{p.name} ({p.token})</option>
                    ))}
                  </select>
                </FieldRow>

                <FieldRow label="Lost window" hint="Seconds without a target before returning home.">
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

                <FieldRow label="Auto-zoom" hint="When target is small, zoom in. When target fills the frame, zoom out. Off by default since over-zoom can lose the target on fast motion.">
                  <label className="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={smartTrackZoom}
                      onChange={(e) => setSmartTrackZoom(e.target.checked)}
                      className="accent-accent"
                    />
                    <span className="text-sm">{smartTrackZoom ? "Auto zoom on" : "Fixed zoom"}</span>
                  </label>
                </FieldRow>

                <FieldRow label="Deadzone" hint="Tolerance around frame center where no move is issued. Higher = less twitchy, lower = tighter centering.">
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

                <FieldRow label="Max speed" hint="Cap on ONVIF pan/tilt velocity. 1.0 is the camera's hardware max. Lower values produce smoother but slower follow.">
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

                <FieldRow label="Gain" hint="Proportional gain on the bbox error. Higher = snappier, lower = smoother. 1.5 is a good default for most ONVIF cams.">
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

                <FieldRow label="Min confidence" hint="Detections below this confidence are ignored as follow targets.">
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

                <FieldRow label="Move budget" hint="Hard cap on ContinuousMove commands per minute. Protects against mechanical wear on the gimbal motor.">
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
                      {smartTrackMoveBudget}/min
                    </span>
                  </div>
                </FieldRow>

                <FieldRow label="ONVIF profile token" hint="Most cameras use Profile_1. Change only if your camera uses a different media profile.">
                  <input
                    type="text"
                    value={ptzProfileToken}
                    onChange={(e) => setPtzProfileToken(e.target.value)}
                    placeholder="Profile_1"
                    className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm font-mono"
                  />
                </FieldRow>
              </>
            )}
          </Section>
  );
}
