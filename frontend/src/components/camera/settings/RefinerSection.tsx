// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, KeywordChipInput, inputClass } from "./primitives";
import { LabelPicker } from "../ModelPickers";
import type { Provider } from "./types";
import { translate, type Locale } from "@/lib/i18n";

interface RefinerSectionProps {
  locale: Locale;
  detectionModels: { model: string; confidence: number; enabled: boolean; label_filter: string[] }[];
  modelClasses: string[];
  modelClassesLoading: boolean;
  providers: Provider[];
  setDetectionModels: Dispatch<SetStateAction<{ model: string; confidence: number; enabled: boolean; label_filter: string[] }[]>>;
  setVlmRefinerKeywords: Dispatch<SetStateAction<string[]>>;
  setVlmRefinerMaxInputTokens: Dispatch<SetStateAction<string>>;
  setVlmRefinerMaxTokens: Dispatch<SetStateAction<string>>;
  setVlmRefinerProviderId: Dispatch<SetStateAction<string | null>>;
  setVlmRefinerTriggerObjects: Dispatch<SetStateAction<string[]>>;
  vlmProviderId: string | null;
  vlmRefinerKeywords: string[];
  vlmRefinerMaxInputTokens: string;
  vlmRefinerMaxTokens: string;
  vlmRefinerProviderId: string | null;
  vlmRefinerTriggerObjects: string[];
}

export function RefinerSection({
  locale,
  detectionModels,
  modelClasses,
  modelClassesLoading,
  providers,
  setDetectionModels,
  setVlmRefinerKeywords,
  setVlmRefinerMaxInputTokens,
  setVlmRefinerMaxTokens,
  setVlmRefinerProviderId,
  setVlmRefinerTriggerObjects,
  vlmProviderId,
  vlmRefinerKeywords,
  vlmRefinerMaxInputTokens,
  vlmRefinerMaxTokens,
  vlmRefinerProviderId,
  vlmRefinerTriggerObjects,
}: RefinerSectionProps) {
  const t = (key: string) => translate(locale, key);
  return (
        <Section
          title={t("camera.refiner.title")}
          advanced
          description={t("camera.refiner.description")}
        >
          <FieldRow label={t("camera.refiner.model")} hint={t("camera.refiner.model_hint")}>
            <select
              value={vlmRefinerProviderId || ""}
              onChange={(e) => setVlmRefinerProviderId(e.target.value || null)}
              className={inputClass}
            >
              <option value="">{t("camera.refiner.off")}</option>
              {providers.map((p) => (
                <option key={p.id} value={p.id} disabled={p.id === vlmProviderId}>
                  {p.name}
                  {p.default_model ? ` · ${p.default_model}` : ""}
                  {p.id === vlmProviderId ? ` (${t("camera.refiner.primary_note")})` : ""}
                </option>
              ))}
            </select>
            {providers.filter((p) => p.id !== vlmProviderId).length === 0 && (
              <p className="text-[11px] text-muted-foreground mt-1.5">
                {t("camera.refiner.no_second_provider")}
              </p>
            )}
            {vlmRefinerProviderId && vlmRefinerProviderId === vlmProviderId && (
              <p className="text-[11px] text-warning mt-1">
                {t("camera.refiner.same_provider_warning")}
              </p>
            )}
          </FieldRow>

          {vlmRefinerProviderId && (
            <>
              <FieldRow label={t("camera.refiner.trigger_objects")} hint={t("camera.refiner.trigger_objects_hint")}>
                <LabelPicker
                  selected={vlmRefinerTriggerObjects}
                  available={modelClasses}
                  loading={modelClassesLoading}
                  onChange={setVlmRefinerTriggerObjects}
                  placeholder={t("camera.refiner.label_placeholder")}
                  activeModels={detectionModels.map((m) => m.model)}
                  onAddModel={(model) => {
                    if (detectionModels.some((m) => m.model === model)) return;
                    setDetectionModels([
                      ...detectionModels,
                      { model, confidence: 0.35, enabled: true, label_filter: [] },
                    ]);
                  }}
                />
                {vlmRefinerTriggerObjects.length === 0 && vlmRefinerKeywords.length === 0 && (
                  <p className="text-[11px] text-warning mt-1.5">
                    {t("camera.refiner.no_triggers")}
                  </p>
                )}
              </FieldRow>

              <FieldRow label={t("camera.refiner.trigger_keywords")} hint={t("camera.refiner.trigger_keywords_hint")}>
                <KeywordChipInput
                  values={vlmRefinerKeywords}
                  onChange={setVlmRefinerKeywords}
                  placeholder={t("camera.refiner.keywords_placeholder")}
                />
              </FieldRow>

              <FieldRow label={t("camera.refiner.max_output")} hint={t("camera.refiner.max_output_hint")}>
                <input
                  type="number"
                  min={50}
                  value={vlmRefinerMaxTokens}
                  onChange={(e) => setVlmRefinerMaxTokens(e.target.value)}
                  className={inputClass}
                  placeholder={t("camera.refiner.defer_to_provider")}
                />
              </FieldRow>

              <FieldRow label={t("camera.refiner.max_input")} hint={t("camera.refiner.max_input_hint")}>
                <input
                  type="number"
                  min={64}
                  value={vlmRefinerMaxInputTokens}
                  onChange={(e) => setVlmRefinerMaxInputTokens(e.target.value)}
                  className={inputClass}
                  placeholder={t("camera.refiner.defer_to_provider")}
                />
              </FieldRow>
            </>
          )}
        </Section>
  );
}
