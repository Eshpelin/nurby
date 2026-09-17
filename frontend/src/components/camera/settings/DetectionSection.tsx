// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, Toggle } from "./primitives";
import { DetectionModelSelect, LabelPicker } from "../ModelPickers";
import { DETECTION_MODEL_CATALOG } from "../detection-models";

interface DetectionSectionProps {
  detectClasses: string[] | null;
  detectFaces: boolean;
  detectObjects: boolean;
  detectPlates: boolean;
  detectionConsensusMin: number;
  detectionMerge: string;
  detectionModels: { model: string; confidence: number; enabled: boolean; label_filter: string[] }[];
  modelClasses: string[];
  modelClassesLoading: boolean;
  objectConfidence: number;
  platelessReid: boolean | null;
  sceneMode: string;
  setDetectClasses: Dispatch<SetStateAction<string[] | null>>;
  setDetectFaces: Dispatch<SetStateAction<boolean>>;
  setDetectObjects: Dispatch<SetStateAction<boolean>>;
  setDetectPlates: Dispatch<SetStateAction<boolean>>;
  setDetectionConsensusMin: Dispatch<SetStateAction<number>>;
  setDetectionMerge: Dispatch<SetStateAction<string>>;
  setDetectionModels: Dispatch<SetStateAction<{ model: string; confidence: number; enabled: boolean; label_filter: string[] }[]>>;
  setObjectConfidence: Dispatch<SetStateAction<number>>;
  setPlatelessReid: Dispatch<SetStateAction<boolean | null>>;
  setSceneMode: Dispatch<SetStateAction<string>>;
}

export function DetectionSection({
  detectClasses,
  detectFaces,
  detectObjects,
  detectPlates,
  detectionConsensusMin,
  detectionMerge,
  detectionModels,
  modelClasses,
  modelClassesLoading,
  objectConfidence,
  platelessReid,
  sceneMode,
  setDetectClasses,
  setDetectFaces,
  setDetectObjects,
  setDetectPlates,
  setDetectionConsensusMin,
  setDetectionMerge,
  setDetectionModels,
  setObjectConfidence,
  setPlatelessReid,
  setSceneMode,
}: DetectionSectionProps) {
  return (
        <Section
          title="Detection"
          description="Object and face detection models for this camera"
        >
          <FieldRow label="Scene Mode" hint="Controls how unknown faces are handled">
            <div className="space-y-2">
              <div className="flex gap-2">
                {(["indoor", "outdoor"] as const).map((mode) => (
                  <button key={mode} onClick={() => setSceneMode(mode)}
                    className={`flex-1 px-3 py-2 text-xs rounded-lg transition-colors ${sceneMode === mode ? "bg-accent/15 text-accent-foreground font-medium border border-accent/30" : "text-muted-foreground border border-border hover:text-foreground hover:bg-muted/50"}`}>
                    {mode === "indoor" ? "Indoor" : "Outdoor"}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                {sceneMode === "outdoor"
                  ? "Outdoor mode will still recognize people you have already named, but will not try to identify unknown faces. This prevents your People page from filling up with strangers walking by."
                  : "Indoor mode will track all faces and suggest unknown people for you to name."}
              </p>
            </div>
          </FieldRow>

          <FieldRow label="Group unplated vehicles" hint="Re-identify vehicles with no readable plate by appearance">
            <div className="space-y-2">
              <div className="flex gap-2">
                {([["auto", null], ["on", true], ["off", false]] as const).map(([key, val]) => {
                  const active = platelessReid === val;
                  return (
                    <button key={key} onClick={() => setPlatelessReid(val)}
                      className={`flex-1 px-3 py-2 text-xs rounded-lg transition-colors capitalize ${active ? "bg-accent/15 text-accent-foreground font-medium border border-accent/30" : "text-muted-foreground border border-border hover:text-foreground hover:bg-muted/50"}`}>
                      {key}
                    </button>
                  );
                })}
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                {platelessReid === null
                  ? `Auto. ${sceneMode === "outdoor" ? "off for this outdoor camera, since a busy street would create many one-off vehicles." : "on for this camera."} Override with On or Off.`
                  : platelessReid
                    ? "On. unplated vehicles seen repeatedly here are grouped into one provisional identity by appearance."
                    : "Off. unplated vehicles are still detected and timelined, but not grouped into identities."}
              </p>
            </div>
          </FieldRow>

          <FieldRow label="Object Detection" hint="Enable YOLO-based object recognition">
            <Toggle
              checked={detectObjects}
              onChange={setDetectObjects}
              label={detectObjects ? "Enabled" : "Disabled"}
            />
          </FieldRow>

          {detectObjects && (
            <>
              {/* Per-camera object-class override */}
              <FieldRow label="Objects on this camera" hint="Override the global 'objects to detect' list, just for this camera.">
                <div className="space-y-2">
                  <Toggle
                    checked={detectClasses !== null}
                    onChange={(v) => setDetectClasses(v ? [] : null)}
                    label={detectClasses !== null ? "Custom for this camera" : "Using global default"}
                  />
                  {detectClasses !== null && (
                    <LabelPicker
                      selected={detectClasses}
                      available={modelClasses}
                      loading={modelClassesLoading}
                      onChange={setDetectClasses}
                      placeholder="Pick classes (leave empty to detect everything here)"
                      activeModels={detectionModels.map((m) => m.model)}
                    />
                  )}
                </div>
              </FieldRow>

              {/* License plate reading (basic, on by default) */}
              <FieldRow label="License Plates" hint="Read plates on detected vehicles.">
                <Toggle
                  checked={detectPlates}
                  onChange={setDetectPlates}
                  label={detectPlates ? "Enabled" : "Disabled"}
                />
              </FieldRow>

              {/* Model list */}
              <FieldRow label="Detection Models" hint="Run multiple models for better accuracy">
                <div className="space-y-2">
                  {detectionModels.map((m, i) => (
                    <div key={i} className="flex items-center gap-2 p-2.5 rounded-md border border-border bg-background">
                      <Toggle
                        checked={m.enabled}
                        onChange={(v) => {
                          const updated = [...detectionModels];
                          updated[i] = { ...m, enabled: v };
                          setDetectionModels(updated);
                        }}
                      />
                      <DetectionModelSelect
                        value={m.model}
                        onChange={(v) => {
                          const updated = [...detectionModels];
                          updated[i] = { ...m, model: v };
                          setDetectionModels(updated);
                        }}
                      />
                      <div className="flex items-center gap-1.5 min-w-[140px]">
                        <input
                          type="range"
                          min={0.05}
                          max={0.95}
                          step={0.05}
                          value={m.confidence}
                          onChange={(e) => {
                            const updated = [...detectionModels];
                            updated[i] = { ...m, confidence: Number(e.target.value) };
                            setDetectionModels(updated);
                          }}
                          className="flex-1 accent-accent"
                        />
                        <span className="font-mono text-[11px] text-muted-foreground w-8 text-right">
                          {(m.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setDetectionModels(detectionModels.filter((_, j) => j !== i));
                        }}
                        className="text-muted-foreground hover:text-danger transition-colors text-sm px-1"
                        title="Remove model"
                      >
                        ×
                      </button>
                    </div>
                  ))}

                  <button
                    type="button"
                    onClick={() => {
                      const used = new Set(detectionModels.map((x) => x.model));
                      const next = DETECTION_MODEL_CATALOG.find((m) => !used.has(m.value))?.value || "yolov8n.pt";
                      setDetectionModels([
                        ...detectionModels,
                        { model: next, confidence: 0.35, enabled: true, label_filter: [] },
                      ]);
                    }}
                    className="w-full py-2 text-xs text-muted-foreground hover:text-foreground border border-dashed border-border rounded-md hover:border-accent transition-colors"
                  >
                    + Add detection model
                  </button>

                  {detectionModels.length === 0 && (
                    <p className="text-[11px] text-muted-foreground">
                      No models configured. Single YOLO model with {(objectConfidence * 100).toFixed(0)}% confidence used as fallback.
                    </p>
                  )}
                </div>
              </FieldRow>

              {/* Fallback confidence (shown when no models configured) */}
              {detectionModels.length === 0 && (
                <FieldRow label="Confidence Threshold" hint="Min confidence for default YOLO model">
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={0.05}
                      max={0.95}
                      step={0.05}
                      value={objectConfidence}
                      onChange={(e) => setObjectConfidence(Number(e.target.value))}
                      className="flex-1 accent-accent"
                    />
                    <span className="font-mono text-xs text-muted-foreground w-12 text-right">
                      {(objectConfidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </FieldRow>
              )}

              {/* Merge strategy (only when multiple models) */}
              {detectionModels.length > 1 && (
                <>
                  <FieldRow label="Merge Strategy" hint="How to combine results from multiple models">
                    <div className="flex gap-1.5">
                      {([
                        { value: "any", label: "Any Model", desc: "Union of all detections" },
                        { value: "consensus", label: "Consensus", desc: "Multiple models must agree" },
                        { value: "best", label: "Best Score", desc: "Highest confidence per object" },
                      ] as const).map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setDetectionMerge(opt.value)}
                          className={`px-2.5 py-1.5 text-xs rounded-md border transition-colors ${
                            detectionMerge === opt.value
                              ? "border-accent bg-accent/10 text-accent-foreground"
                              : "border-border hover:border-muted-foreground text-muted-foreground"
                          }`}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-1.5">
                      {detectionMerge === "any"
                        ? "Keep all detections from all models. Overlapping boxes get de-duplicated."
                        : detectionMerge === "consensus"
                          ? `Only keep objects detected by at least ${detectionConsensusMin} model${detectionConsensusMin !== 1 ? "s" : ""}.`
                          : "For each detected object region, keep only the highest confidence result."}
                    </p>
                  </FieldRow>

                  {detectionMerge === "consensus" && (
                    <FieldRow label="Min Agreement" hint="Number of models that must detect the same object">
                      <div className="flex items-center gap-3">
                        <input
                          type="range"
                          min={2}
                          max={Math.max(2, detectionModels.filter((m) => m.enabled).length)}
                          step={1}
                          value={detectionConsensusMin}
                          onChange={(e) => setDetectionConsensusMin(Number(e.target.value))}
                          className="flex-1 accent-accent"
                        />
                        <span className="font-mono text-xs text-muted-foreground w-12 text-right">
                          {detectionConsensusMin} / {detectionModels.filter((m) => m.enabled).length}
                        </span>
                      </div>
                    </FieldRow>
                  )}
                </>
              )}
            </>
          )}

          <FieldRow label="Face Detection" hint="Detect and match known people">
            <Toggle
              checked={detectFaces}
              onChange={setDetectFaces}
              label={detectFaces ? "Enabled" : "Disabled"}
            />
          </FieldRow>
        </Section>
  );
}
