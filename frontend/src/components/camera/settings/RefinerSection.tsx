// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, KeywordChipInput, inputClass } from "./primitives";
import { LabelPicker } from "../ModelPickers";
import type { Provider } from "./types";

interface RefinerSectionProps {
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
  return (
        <Section
          title="Refiner (cascade)"
          advanced
          description="Re-describes individual frames with a stronger second model the moment a trigger matches (a person appears, a keyword lands). Different from the AI Summarizer below, which periodically condenses many observations into a recap. The refiner upgrades single moments; the summarizer narrates stretches of time."
        >
          <FieldRow label="Refiner Model" hint="Off when blank. Needs a second provider entry, different from AI Analysis.">
            <select
              value={vlmRefinerProviderId || ""}
              onChange={(e) => setVlmRefinerProviderId(e.target.value || null)}
              className={inputClass}
            >
              <option value="">Off</option>
              {providers.map((p) => (
                <option key={p.id} value={p.id} disabled={p.id === vlmProviderId}>
                  {p.name}
                  {p.default_model ? ` · ${p.default_model}` : ""}
                  {p.id === vlmProviderId ? " (primary — pick a different one)" : ""}
                </option>
              ))}
            </select>
            {providers.filter((p) => p.id !== vlmProviderId).length === 0 && (
              <p className="text-[11px] text-muted-foreground mt-1.5">
                Only one AI provider is configured, so there is nothing to
                cascade to. Add a second provider under Settings → AI
                Providers — for example another Ollama entry pointing at a
                larger model (gemma3:27b) — and it will appear here.
              </p>
            )}
            {vlmRefinerProviderId && vlmRefinerProviderId === vlmProviderId && (
              <p className="text-[11px] text-warning mt-1">
                Refiner must differ from the primary provider. Cascade
                disabled until you pick another model.
              </p>
            )}
          </FieldRow>

          {vlmRefinerProviderId && (
            <>
              <FieldRow label="Escalate when YOLO sees" hint="Detection labels that fire the refiner. Pet-cams, wildlife, vehicles all welcome.">
                <LabelPicker
                  selected={vlmRefinerTriggerObjects}
                  available={modelClasses}
                  loading={modelClassesLoading}
                  onChange={setVlmRefinerTriggerObjects}
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
                {vlmRefinerTriggerObjects.length === 0 && vlmRefinerKeywords.length === 0 && (
                  <p className="text-[11px] text-warning mt-1.5">
                    No triggers set. Refiner will fire on every frame.
                    Add labels or keywords to gate it.
                  </p>
                )}
              </FieldRow>

              <FieldRow label="Escalate when primary mentions" hint="Comma or Enter to add. Case-insensitive substring match against the cheap model's text output.">
                <KeywordChipInput
                  values={vlmRefinerKeywords}
                  onChange={setVlmRefinerKeywords}
                  placeholder="package, delivery, stranger..."
                />
              </FieldRow>

              <FieldRow label="Refiner Max Output" hint="Per-camera output cap for the refiner. Empty defers to its provider cap.">
                <input
                  type="number"
                  min={50}
                  value={vlmRefinerMaxTokens}
                  onChange={(e) => setVlmRefinerMaxTokens(e.target.value)}
                  className={inputClass}
                  placeholder="defer to provider"
                />
              </FieldRow>

              <FieldRow label="Refiner Max Input" hint="Per-camera prompt size cap for the refiner. Empty defers to its provider cap.">
                <input
                  type="number"
                  min={64}
                  value={vlmRefinerMaxInputTokens}
                  onChange={(e) => setVlmRefinerMaxInputTokens(e.target.value)}
                  className={inputClass}
                  placeholder="defer to provider"
                />
              </FieldRow>
            </>
          )}
        </Section>
  );
}
