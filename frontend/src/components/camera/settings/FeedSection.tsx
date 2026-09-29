// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, inputClass } from "./primitives";
import { STREAM_TYPES } from "./constants";
import { LabelPicker } from "../ModelPickers";
import { translate, type Locale } from "@/lib/i18n";

interface FeedSectionProps {
  locale: Locale;
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
  locale,
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
  const t = (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
  const streamTypeLabel = (value: string) => t(`camera.feed.stream_type.${value}`);
  const recordingModeLabel = (value: string) => t(`camera.feed.recording_mode.${value}`);
  return (
        <Section title={t("camera.feed.title")}
          advanced description={t("camera.feed.description")}>
          <FieldRow label={t("camera.feed.type")}>
            <select
              value={streamType}
              onChange={(e) => setStreamType(e.target.value)}
              className={inputClass}
            >
              {Object.entries(STREAM_TYPES).map(([val, label]) => (
                <option key={val} value={val}>
                  {streamTypeLabel(val) || label}
                </option>
              ))}
            </select>
          </FieldRow>

          <FieldRow
            label={streamType === "usb" ? t("camera.feed.device") : t("camera.feed.stream_url")}
            hint={streamType === "usb" ? t("camera.feed.device_hint") : undefined}
          >
            <input
              type="text"
              value={streamUrl}
              onChange={(e) => setStreamUrl(e.target.value)}
              className={`${inputClass} font-mono text-xs`}
            />
          </FieldRow>

          {streamType === "http_snapshot" && (
            <FieldRow label={t("camera.feed.poll_interval")} hint={t("camera.feed.poll_interval_hint")}>
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
                  {t("camera.feed.seconds", { seconds: snapshotInterval })}
                </span>
              </div>
            </FieldRow>
          )}

          <FieldRow label={t("camera.feed.recording_mode")} hint={t("camera.feed.recording_mode_hint")}>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {([
                { value: "off" },
                { value: "always" },
                { value: "on_motion" },
                { value: "on_object" },
                { value: "clip" },
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
                  {recordingModeLabel(opt.value)}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">
              {t(`camera.feed.recording_help.${recordingMode}`)}
            </p>
          </FieldRow>

          {recordingMode === "on_object" && (
            <FieldRow label={t("camera.feed.record_when_detected")} hint={t("camera.feed.record_when_detected_hint")}>
              <LabelPicker
                selected={recordingTriggerObjects}
                available={modelClasses}
                loading={modelClassesLoading}
                onChange={setRecordingTriggerObjects}
                placeholder={t("camera.feed.label_placeholder")}
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
                  {t("camera.feed.no_objects")}
                </p>
              )}
            </FieldRow>
          )}

          {["clip", "on_motion", "on_object"].includes(recordingMode) && (
            <>
              <FieldRow label={t("camera.feed.pre_buffer")} hint={t("camera.feed.pre_buffer_hint")}>
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
                  {t("camera.feed.seconds", { seconds: recordingClipPre })}
                  </span>
                </div>
              </FieldRow>

              <FieldRow label={t("camera.feed.post_buffer")} hint={t("camera.feed.post_buffer_hint")}>
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
                  {t("camera.feed.seconds", { seconds: recordingClipPost })}
                  </span>
                </div>
              </FieldRow>
            </>
          )}

          <FieldRow label={t("camera.feed.motion_sensitivity")} hint={t("camera.feed.motion_sensitivity_hint")}>
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
