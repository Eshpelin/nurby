// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, inputClass } from "./primitives";
import { DEFAULT_VLM_PROMPT } from "./constants";
import { formatInterval } from "./format";
import { LabelPicker } from "../ModelPickers";
import type { Provider } from "./types";

interface AiAnalysisSectionProps {
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
  return (
        <Section
          title="AI Analysis"
          advanced
          description="Configure which model analyzes this camera and how"
        >
          <FieldRow label="AI model" hint="Leave on System Default to use global setting">
            <select
              value={vlmProviderId || ""}
              onChange={(e) => setVlmProviderId(e.target.value || null)}
              className={inputClass}
            >
              <option value="">
                System Default{activeProvider ? ` (${activeProvider.name})` : ""}
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

          <FieldRow label="Analysis Frequency" hint="Rate limit. Minimum gap between consecutive VLM calls">
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
                ? "Analyze every motion keyframe. More API calls"
                : `Wait at least ${formatInterval(vlmInterval)} between VLM calls`}
            </p>
          </FieldRow>

          <FieldRow label="Trigger Condition" hint="Gate. What qualifies a frame for VLM analysis in the first place">
            <div className="flex gap-1.5 mb-2">
              {([
                { value: "always", label: "Always", desc: "Time-based, using frequency above" },
                { value: "on_object", label: "On Detection", desc: "Only when specific objects are detected" },
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
                  {opt.label}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">
              {vlmTrigger === "always"
                ? "VLM runs on every keyframe (respecting frequency limit above)"
                : vlmTriggerObjects.length > 0
                  ? `VLM only runs when ${vlmTriggerObjects.join(", ")} detected by object detection`
                  : "VLM only runs when any object is detected"}
            </p>
          </FieldRow>

          {vlmTrigger === "on_object" && (
            <FieldRow label="Trigger Objects" hint="Labels come from the detection model. Type to search or add a custom label.">
              <LabelPicker
                selected={vlmTriggerObjects}
                available={modelClasses}
                loading={modelClassesLoading}
                onChange={setVlmTriggerObjects}
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
              {vlmTriggerObjects.length === 0 && (
                <p className="text-[11px] text-muted-foreground mt-1.5">
                  No objects selected. VLM will trigger on any detection.
                </p>
              )}
            </FieldRow>
          )}

          <FieldRow label="Max Output Tokens" hint="Per-camera output cap. The provider's cap (set in Settings) further tightens this.">
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

          <FieldRow label="Max Input Tokens" hint="Per-camera prompt size cap. Empty defers to the provider's input cap.">
            <input
              type="number"
              min={64}
              value={vlmMaxInputTokens}
              onChange={(e) => setVlmMaxInputTokens(e.target.value)}
              className={inputClass}
              placeholder="defer to provider"
            />
          </FieldRow>

          <FieldRow
            label="Custom Prompt"
            hint="System prompt sent to the VLM for every frame on this camera. It steers what the model focuses on and how it phrases descriptions. Leave blank to use the built-in default."
          >
            <textarea
              value={vlmPrompt}
              onChange={(e) => setVlmPrompt(e.target.value)}
              placeholder={DEFAULT_VLM_PROMPT}
              rows={4}
              className={`${inputClass} resize-y`}
            />
            <div className="flex items-center gap-3 mt-1">
              <button
                type="button"
                onClick={() => setShowDefaultVlmPrompt((v) => !v)}
                className="text-[11px] text-muted-foreground hover:text-accent transition-colors"
              >
                {showDefaultVlmPrompt ? "Hide default prompt" : "Show default prompt"}
              </button>
              {vlmPrompt.trim() && (
                <button
                  type="button"
                  onClick={() => setVlmPrompt("")}
                  className="text-[11px] text-muted-foreground hover:text-danger transition-colors"
                >
                  Reset to default
                </button>
              )}
            </div>
            {showDefaultVlmPrompt && (
              <div className="mt-1.5 rounded-md border border-border bg-muted/40 p-2.5">
                <p className="text-[11px] text-muted-foreground mb-1">
                  Effective default when this field is blank:
                </p>
                <p className="text-xs text-foreground/80 leading-relaxed">
                  {DEFAULT_VLM_PROMPT}
                </p>
              </div>
            )}
          </FieldRow>
        </Section>
  );
}
