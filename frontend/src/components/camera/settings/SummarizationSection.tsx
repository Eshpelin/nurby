// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, inputClass } from "./primitives";
import { formatInterval } from "./format";
import { LabelPicker } from "../ModelPickers";
import type { Provider } from "./types";
import { translate, type Locale } from "@/lib/i18n";

interface SummarizationSectionProps {
  locale: Locale;
  activeProvider: Provider | undefined;
  detectionModels: { model: string; confidence: number; enabled: boolean; label_filter: string[] }[];
  modelClasses: string[];
  modelClassesLoading: boolean;
  providers: Provider[];
  setDetectionModels: Dispatch<SetStateAction<{ model: string; confidence: number; enabled: boolean; label_filter: string[] }[]>>;
  setSummaryEventMinDurationSeconds: Dispatch<SetStateAction<number>>;
  setSummaryEventQuietSeconds: Dispatch<SetStateAction<number>>;
  setSummaryEventTriggerObjects: Dispatch<SetStateAction<string[]>>;
  setSummaryMaxTokens: Dispatch<SetStateAction<number>>;
  setSummaryMode: Dispatch<SetStateAction<string>>;
  setSummaryPeriodSeconds: Dispatch<SetStateAction<number>>;
  setSummaryProviderId: Dispatch<SetStateAction<string | null>>;
  summaryEventMinDurationSeconds: number;
  summaryEventQuietSeconds: number;
  summaryEventTriggerObjects: string[];
  summaryMaxTokens: number;
  summaryMode: string;
  summaryPeriodSeconds: number;
  summaryProviderId: string | null;
  vlmProviderId: string | null;
}

export function SummarizationSection({
  locale,
  activeProvider,
  detectionModels,
  modelClasses,
  modelClassesLoading,
  providers,
  setDetectionModels,
  setSummaryEventMinDurationSeconds,
  setSummaryEventQuietSeconds,
  setSummaryEventTriggerObjects,
  setSummaryMaxTokens,
  setSummaryMode,
  setSummaryPeriodSeconds,
  setSummaryProviderId,
  summaryEventMinDurationSeconds,
  summaryEventQuietSeconds,
  summaryEventTriggerObjects,
  summaryMaxTokens,
  summaryMode,
  summaryPeriodSeconds,
  summaryProviderId,
  vlmProviderId,
}: SummarizationSectionProps) {
  const t = (key: string) => translate(locale, key);
  return (
        <Section
          title={t("camera.summarization.title")}
          advanced
          description={t("camera.summarization.description")}
        >
          <FieldRow label={t("camera.summarization.mode")} hint={t("camera.summarization.mode_hint")}>
            <div className="flex gap-1.5">
              {(["off", "periodic", "event", "both"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setSummaryMode(m)}
                  className={`px-2.5 py-1.5 text-xs rounded-md border transition-colors ${
                    summaryMode === m
                      ? "border-accent bg-accent/10 text-accent-foreground"
                      : "border-border hover:border-muted-foreground text-muted-foreground"
                  }`}
                >
                  {t(`camera.summarization.mode.${m}`)}
                </button>
              ))}
            </div>
          </FieldRow>

          {summaryMode !== "off" && (
            <>
              <FieldRow label={t("camera.summarization.model")} hint={t("camera.summarization.model_hint")}>
                <select
                  value={summaryProviderId || ""}
                  onChange={(e) => setSummaryProviderId(e.target.value || null)}
                  className={inputClass}
                >
                  <option value="">
                    {t("camera.summarization.use_ai_provider")}{vlmProviderId ? "" : activeProvider ? ` (${activeProvider.name})` : ""}
                  </option>
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                      {p.default_model ? ` · ${p.default_model}` : ""}
                    </option>
                  ))}
                </select>
              </FieldRow>

              <FieldRow label={t("camera.summarization.max_tokens")} hint={t("camera.summarization.max_tokens_hint")}>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={100}
                    max={1500}
                    step={50}
                    value={summaryMaxTokens}
                    onChange={(e) => setSummaryMaxTokens(Number(e.target.value))}
                    className="flex-1 accent-accent"
                  />
                  <span className="font-mono text-xs text-muted-foreground w-20 text-right">
                    {summaryMaxTokens} {t("camera.summarization.tokens_short")}
                  </span>
                </div>
              </FieldRow>
            </>
          )}

          {(summaryMode === "periodic" || summaryMode === "both") && (
            <FieldRow label={t("camera.summarization.period")} hint={t("camera.summarization.period_hint")}>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={300}
                  max={14400}
                  step={300}
                  value={summaryPeriodSeconds}
                  onChange={(e) => setSummaryPeriodSeconds(Number(e.target.value))}
                  className="flex-1 accent-accent"
                />
                <span className="font-mono text-xs text-muted-foreground w-20 text-right">
                  {formatInterval(summaryPeriodSeconds)}
                </span>
              </div>
            </FieldRow>
          )}

          {(summaryMode === "event" || summaryMode === "both") && (
            <>
              <FieldRow label={t("camera.summarization.trigger_objects")} hint={t("camera.summarization.trigger_objects_hint")}>
                <LabelPicker
                  selected={summaryEventTriggerObjects}
                  available={modelClasses}
                  loading={modelClassesLoading}
                  onChange={setSummaryEventTriggerObjects}
                  placeholder={t("camera.summarization.label_placeholder")}
                  activeModels={detectionModels.map((m) => m.model)}
                  onAddModel={(model) => {
                    if (detectionModels.some((m) => m.model === model)) return;
                    setDetectionModels([
                      ...detectionModels,
                      { model, confidence: 0.35, enabled: true, label_filter: [] },
                    ]);
                  }}
                />
                {summaryEventTriggerObjects.length === 0 && (
                  <p className="text-[11px] text-warning mt-1.5">
                    {t("camera.summarization.no_labels")}
                  </p>
                )}
              </FieldRow>

              <FieldRow label={t("camera.summarization.quiet_window")} hint={t("camera.summarization.quiet_window_hint")}>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={10}
                    max={600}
                    step={5}
                    value={summaryEventQuietSeconds}
                    onChange={(e) => setSummaryEventQuietSeconds(Number(e.target.value))}
                    className="flex-1 accent-accent"
                  />
                  <span className="font-mono text-xs text-muted-foreground w-20 text-right">
                    {formatInterval(summaryEventQuietSeconds)}
                  </span>
                </div>
              </FieldRow>

              <FieldRow label={t("camera.summarization.minimum_duration")} hint={t("camera.summarization.minimum_duration_hint")}>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={1}
                    max={120}
                    step={1}
                    value={summaryEventMinDurationSeconds}
                    onChange={(e) => setSummaryEventMinDurationSeconds(Number(e.target.value))}
                    className="flex-1 accent-accent"
                  />
                  <span className="font-mono text-xs text-muted-foreground w-20 text-right">
                    {formatInterval(summaryEventMinDurationSeconds)}
                  </span>
                </div>
              </FieldRow>
            </>
          )}
        </Section>
  );
}
