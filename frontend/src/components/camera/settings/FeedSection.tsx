// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, inputClass } from "./primitives";
import { STREAM_TYPES } from "./constants";
import { LabelPicker } from "../ModelPickers";

interface FeedSectionProps {
  detectionModels: { model: string; confidence: number; enabled: boolean; label_filter: string[] }[];
  modelClasses: string[];
  modelClassesLoading: boolean;
  motionSensitivity: number;
  recordingClipPost: number;
  recordingClipPre: number;
  recordingMode: string;
  recordingTriggerObjects: string[];
  setDetectionModels: Dispatch<SetStateAction<{ model: string; confidence: number; enabled: boolean; label_filter: string[] }[]>>;
  setMotionSensitivity: Dispatch<SetStateAction<number>>;
  setRecordingClipPost: Dispatch<SetStateAction<number>>;
  setRecordingClipPre: Dispatch<SetStateAction<number>>;
  setRecordingEnabled: Dispatch<SetStateAction<boolean>>;
  setRecordingMode: Dispatch<SetStateAction<string>>;
  setRecordingTriggerObjects: Dispatch<SetStateAction<string[]>>;
  setSnapshotInterval: Dispatch<SetStateAction<number>>;
  setStreamType: Dispatch<SetStateAction<string>>;
  setStreamUrl: Dispatch<SetStateAction<string>>;
  snapshotInterval: number;
  streamType: string;
  streamUrl: string;
}

export function FeedSection({
  detectionModels,
  modelClasses,
  modelClassesLoading,
  motionSensitivity,
  recordingClipPost,
  recordingClipPre,
  recordingMode,
  recordingTriggerObjects,
  setDetectionModels,
  setMotionSensitivity,
  setRecordingClipPost,
  setRecordingClipPre,
  setRecordingEnabled,
  setRecordingMode,
  setRecordingTriggerObjects,
  setSnapshotInterval,
  setStreamType,
  setStreamUrl,
  snapshotInterval,
  streamType,
  streamUrl,
}: FeedSectionProps) {
  return (
        <Section title="Feed"
          advanced description="Stream source and connection settings">
          <FieldRow label="Feed Type">
            <select
              value={streamType}
              onChange={(e) => setStreamType(e.target.value)}
              className={inputClass}
            >
              {Object.entries(STREAM_TYPES).map(([val, label]) => (
                <option key={val} value={val}>
                  {label}
                </option>
              ))}
            </select>
          </FieldRow>

          <FieldRow
            label={streamType === "usb" ? "Device" : "Stream URL"}
            hint={streamType === "usb" ? "Device index (0, 1) or path" : undefined}
          >
            <input
              type="text"
              value={streamUrl}
              onChange={(e) => setStreamUrl(e.target.value)}
              className={`${inputClass} font-mono text-xs`}
            />
          </FieldRow>

          {streamType === "http_snapshot" && (
            <FieldRow label="Poll Interval" hint="Seconds between snapshot fetches">
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={0.5}
                  max={30}
                  step={0.5}
                  value={snapshotInterval}
                  onChange={(e) => setSnapshotInterval(Number(e.target.value))}
                  className="flex-1 accent-accent"
                />
                <span className="font-mono text-xs text-muted-foreground w-12 text-right">
                  {snapshotInterval}s
                </span>
              </div>
            </FieldRow>
          )}

          <FieldRow label="Recording Mode" hint="When to save video to disk">
            <div className="flex flex-wrap gap-1.5 mb-2">
              {([
                { value: "off", label: "Off" },
                { value: "always", label: "Always" },
                { value: "on_motion", label: "On Motion" },
                { value: "on_object", label: "On Detection" },
                { value: "clip", label: "Clips" },
              ] as const).map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => {
                    setRecordingMode(opt.value);
                    setRecordingEnabled(opt.value !== "off");
                  }}
                  className={`px-2.5 py-1.5 text-xs rounded-md border transition-colors ${
                    recordingMode === opt.value
                      ? "border-accent bg-accent/10 text-accent-foreground"
                      : "border-border hover:border-muted-foreground text-muted-foreground"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">
              {recordingMode === "off"
                ? "No video saved to disk. Live view and AI analysis still work."
                : recordingMode === "always"
                  ? "Record continuously in 5-minute segments. Uses the most storage."
                  : recordingMode === "on_motion"
                    ? "Start recording when motion is detected. Stop after motion ends."
                    : recordingMode === "on_object"
                      ? "Record only when specific objects are detected by the AI pipeline."
                      : "Save bounded clips around AI observations with pre and post buffers. Best for rare, labelled triggers. Use Continuous if triggers fire constantly."}
            </p>
          </FieldRow>

          {recordingMode === "on_object" && (
            <FieldRow label="Record When Detected" hint="Which objects trigger recording. Labels come from the detection model.">
              <LabelPicker
                selected={recordingTriggerObjects}
                available={modelClasses}
                loading={modelClassesLoading}
                onChange={setRecordingTriggerObjects}
                placeholder="Search labels or press Enter for custom"
                activeModels={detectionModels.map((m) => m.model)}
                onAddModel={(model) => {
                  if (detectionModels.some((m) => m.model === model)) return;
                  setDetectionModels([
                    ...detectionModels,
                    { model, confidence: 0.35, enabled: true, label_filter: [] },
                  ]);
                }}
              />
              {recordingTriggerObjects.length === 0 && (
                <p className="text-[11px] text-muted-foreground mt-1.5">
                  No objects selected. Recording triggers on any detection.
                </p>
              )}
            </FieldRow>
          )}

          {["clip", "on_motion", "on_object"].includes(recordingMode) && (
            <>
              <FieldRow label="Pre-buffer" hint="Seconds of footage to keep before the trigger event">
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={1}
                    max={30}
                    step={1}
                    value={recordingClipPre}
                    onChange={(e) => setRecordingClipPre(Number(e.target.value))}
                    className="flex-1 accent-accent"
                  />
                  <span className="font-mono text-xs text-muted-foreground w-12 text-right">
                    {recordingClipPre}s
                  </span>
                </div>
              </FieldRow>

              <FieldRow label="Post-buffer" hint="Seconds to keep recording after the trigger event">
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={1}
                    max={60}
                    step={1}
                    value={recordingClipPost}
                    onChange={(e) => setRecordingClipPost(Number(e.target.value))}
                    className="flex-1 accent-accent"
                  />
                  <span className="font-mono text-xs text-muted-foreground w-12 text-right">
                    {recordingClipPost}s
                  </span>
                </div>
              </FieldRow>
            </>
          )}

          <FieldRow label="Motion Sensitivity" hint="Higher = more sensitive">
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={motionSensitivity}
                onChange={(e) => setMotionSensitivity(Number(e.target.value))}
                className="flex-1 accent-accent"
              />
              <span className="font-mono text-xs text-muted-foreground w-12 text-right">
                {(motionSensitivity * 100).toFixed(0)}%
              </span>
            </div>
          </FieldRow>
        </Section>
  );
}
