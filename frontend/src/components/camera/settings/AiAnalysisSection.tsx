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

interface AiAnalysisSectionProps {
  locale: Locale;
  activeProvider: Provider | undefined;
  detectionModels: { model: string; confidence: number; enabled: boolean; label_filter: string[] }[];
  modelClasses: string[];
  modelClassesLoading: boolean;
  providers: Provider[];
  selectedProvider: Provider | null | undefined;
  setDetectionModels: Dispatch<SetStateAction<{ model: string; confidence: number; enabled: boolean; label_filter: string[] }[]>>;
  setShowDefaultVlmPrompt: Dispatch<SetStateAction<boolean>>;
  setVlmInterval: Dispatch<SetStateAction<number>>;
  setVlmMaxInputTokens: Dispatch<SetStateAction<string>>;
  setVlmMaxTokens: Dispatch<SetStateAction<number>>;
  setVlmPrompt: Dispatch<SetStateAction<string>>;
  setVlmProviderId: Dispatch<SetStateAction<string | null>>;
  setVlmTrigger: Dispatch<SetStateAction<string>>;
  setVlmTriggerObjects: Dispatch<SetStateAction<string[]>>;
  showDefaultVlmPrompt: boolean;
  vlmInterval: number;
  vlmMaxInputTokens: string;
  vlmMaxTokens: number;
  vlmPrompt: string;
  vlmProviderId: string | null;
  vlmTrigger: string;
  vlmTriggerObjects: string[];
}

export function AiAnalysisSection({
  locale,
  activeProvider,
  detectionModels,
  modelClasses,
  modelClassesLoading,
  providers,
  selectedProvider,
  setDetectionModels,
  setShowDefaultVlmPrompt,
  setVlmInterval,
  setVlmMaxInputTokens,
  setVlmMaxTokens,
  setVlmPrompt,
  setVlmProviderId,
  setVlmTrigger,
  setVlmTriggerObjects,
  showDefaultVlmPrompt,
  vlmInterval,
  vlmMaxInputTokens,
  vlmMaxTokens,
  vlmPrompt,
  vlmProviderId,
  vlmTrigger,
  vlmTriggerObjects,
}: AiAnalysisSectionProps) {
  const t = (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
  return (
        <Section
          title={t("camera.ai.title")}
          advanced
          description={t("camera.ai.description")}
        >
          <FieldRow label={t("camera.ai.model")} hint={t("camera.ai.model_hint")}>
            <select
              value={vlmProviderId || ""}
              onChange={(e) => setVlmProviderId(e.target.value || null)}
              className={inputClass}
            >
              <option value="">
                {t("camera.ai.system_default")}{activeProvider ? ` (${activeProvider.name})` : ""}
              </option>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.default_model ? ` · ${p.default_model}` : ""}
                </option>
              ))}
            </select>
            {selectedProvider && (
              <p className="text-[11px] text-muted-foreground mt-1">
                {selectedProvider.kind} · {selectedProvider.base_url}
              </p>
            )}
          </FieldRow>

          <FieldRow label={t("camera.ai.frequency")} hint={t("camera.ai.frequency_hint")}>
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={0}
                max={300}
                step={5}
                value={vlmInterval}
                onChange={(e) => setVlmInterval(Number(e.target.value))}
                className="flex-1 accent-accent"
              />
              <span className="font-mono text-xs text-muted-foreground w-28 text-right">
                {formatInterval(vlmInterval)}
              </span>
            </div>
            <p className="text-[11px] text-muted-foreground mt-1">
              {vlmInterval === 0
                ? t("camera.ai.frequency_unlimited")
                : t("camera.ai.frequency_wait", { interval: formatInterval(vlmInterval) })}
            </p>
          </FieldRow>

          <FieldRow label={t("camera.ai.trigger_condition")} hint={t("camera.ai.trigger_condition_hint")}>
            <div className="flex gap-1.5 mb-2">
              {([
                { value: "always" },
                { value: "on_object" },
              ] as const).map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setVlmTrigger(opt.value)}
                  className={`px-2.5 py-1.5 text-xs rounded-md border transition-colors ${
                    vlmTrigger === opt.value
                      ? "border-accent bg-accent/10 text-accent-foreground"
                      : "border-border hover:border-muted-foreground text-muted-foreground"
                  }`}
                >
                  {t(`camera.ai.trigger.${opt.value}`)}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">
              {vlmTrigger === "always"
                ? t("camera.ai.trigger_always_help")
                : vlmTriggerObjects.length > 0
                  ? t("camera.ai.trigger_objects_help", { objects: vlmTriggerObjects.join(", ") })
                  : t("camera.ai.trigger_any_help")}
            </p>
          </FieldRow>

          {vlmTrigger === "on_object" && (
            <FieldRow label={t("camera.ai.trigger_objects")} hint={t("camera.ai.trigger_objects_hint")}>
              <LabelPicker
                selected={vlmTriggerObjects}
                available={modelClasses}
                loading={modelClassesLoading}
                onChange={setVlmTriggerObjects}
                placeholder={t("camera.ai.label_placeholder")}
                activeModels={detectionModels.map((m) => m.model)}
                onAddModel={(model) => {
                  if (detectionModels.some((m) => m.model === model)) return;
                  setDetectionModels([
                    ...detectionModels,
                    { model, confidence: 0.35, enabled: true, label_filter: [] },
                  ]);
                }}
              />
              {vlmTriggerObjects.length === 0 && (
                <p className="text-[11px] text-muted-foreground mt-1.5">
                  {t("camera.ai.no_trigger_objects")}
                </p>
              )}
            </FieldRow>
          )}

          <FieldRow label={t("camera.ai.max_output_tokens")} hint={t("camera.ai.max_output_tokens_hint")}>
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={50}
                max={1000}
                step={50}
                value={vlmMaxTokens}
                onChange={(e) => setVlmMaxTokens(Number(e.target.value))}
                className="flex-1 accent-accent"
              />
              <span className="font-mono text-xs text-muted-foreground w-16 text-right">
                {vlmMaxTokens}
              </span>
            </div>
          </FieldRow>

          <FieldRow label={t("camera.ai.max_input_tokens")} hint={t("camera.ai.max_input_tokens_hint")}>
            <input
              type="number"
              min={64}
              value={vlmMaxInputTokens}
              onChange={(e) => setVlmMaxInputTokens(e.target.value)}
              className={inputClass}
              placeholder={t("camera.ai.defer_to_provider")}
            />
          </FieldRow>

          <FieldRow
            label={t("camera.ai.custom_prompt")}
            hint={t("camera.ai.custom_prompt_hint")}
          >
            <textarea
              value={vlmPrompt}
              onChange={(e) => setVlmPrompt(e.target.value)}
              placeholder={t("camera.ai.default_prompt")}
              rows={4}
              className={`${inputClass} resize-y`}
            />
            <div className="flex items-center gap-3 mt-1">
              <button
                type="button"
                onClick={() => setShowDefaultVlmPrompt((v) => !v)}
                className="text-[11px] text-muted-foreground hover:text-accent transition-colors"
              >
                {showDefaultVlmPrompt ? t("camera.ai.hide_default") : t("camera.ai.show_default")}
              </button>
              {vlmPrompt.trim() && (
                <button
                  type="button"
                  onClick={() => setVlmPrompt("")}
                  className="text-[11px] text-muted-foreground hover:text-danger transition-colors"
                >
                  {t("camera.ai.reset")}
                </button>
              )}
            </div>
            {showDefaultVlmPrompt && (
              <div className="mt-1.5 rounded-md border border-border bg-muted/40 p-2.5">
                <p className="text-[11px] text-muted-foreground mb-1">
                  {t("camera.ai.effective_default")}
                </p>
                <p className="text-xs text-foreground/80 leading-relaxed">
                  {t("camera.ai.default_prompt")}
                </p>
              </div>
            )}
          </FieldRow>
        </Section>
  );
}
