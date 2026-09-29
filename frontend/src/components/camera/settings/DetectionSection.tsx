// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, Toggle } from "./primitives";
import { DetectionModelSelect, LabelPicker } from "../ModelPickers";
import { DETECTION_MODEL_CATALOG } from "../detection-models";
import { translate, type Locale } from "@/lib/i18n";

interface DetectionSectionProps {
  locale: Locale;
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
  locale,
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
  const t = (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
  return (
        <Section
          title={t("camera.detection.title")}
          description={t("camera.detection.description")}
        >
          <FieldRow label={t("camera.detection.scene_mode")} hint={t("camera.detection.scene_mode_hint")}>
            <div className="space-y-2">
              <div className="flex gap-2">
                {(["indoor", "outdoor"] as const).map((mode) => (
                  <button key={mode} onClick={() => setSceneMode(mode)}
                    className={`flex-1 px-3 py-2 text-xs rounded-lg transition-colors ${sceneMode === mode ? "bg-accent/15 text-accent-foreground font-medium border border-accent/30" : "text-muted-foreground border border-border hover:text-foreground hover:bg-muted/50"}`}>
                    {t(`camera.detection.scene.${mode}`)}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                {t(`camera.detection.scene_help.${sceneMode}`)}
              </p>
            </div>
          </FieldRow>

          <FieldRow label={t("camera.detection.plateless")} hint={t("camera.detection.plateless_hint")}>
            <div className="space-y-2">
              <div className="flex gap-2">
                {([["auto", null], ["on", true], ["off", false]] as const).map(([key, val]) => {
                  const active = platelessReid === val;
                  return (
                    <button key={key} onClick={() => setPlatelessReid(val)}
                      className={`flex-1 px-3 py-2 text-xs rounded-lg transition-colors capitalize ${active ? "bg-accent/15 text-accent-foreground font-medium border border-accent/30" : "text-muted-foreground border border-border hover:text-foreground hover:bg-muted/50"}`}>
                      {t(`camera.detection.plateless.${key}`)}
                    </button>
                  );
                })}
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                {platelessReid === null
                  ? t(`camera.detection.plateless_auto.${sceneMode}`)
                  : platelessReid
                    ? t("camera.detection.plateless_on_help")
                    : t("camera.detection.plateless_off_help")}
              </p>
            </div>
          </FieldRow>

          <FieldRow label={t("camera.detection.objects")} hint={t("camera.detection.objects_hint")}>
            <Toggle
              checked={detectObjects}
              onChange={setDetectObjects}
              label={detectObjects ? t("common.enabled") : t("common.disabled")}
            />
          </FieldRow>

          {detectObjects && (
            <>
              {/* Per-camera object-class override */}
              <FieldRow label={t("camera.detection.camera_objects")} hint={t("camera.detection.camera_objects_hint")}>
                <div className="space-y-2">
                  <Toggle
                    checked={detectClasses !== null}
                    onChange={(v) => setDetectClasses(v ? [] : null)}
                    label={detectClasses !== null ? t("camera.detection.custom_camera") : t("camera.detection.global_default")}
                  />
                  {detectClasses !== null && (
                    <LabelPicker
                      selected={detectClasses}
                      available={modelClasses}
                      loading={modelClassesLoading}
                      onChange={setDetectClasses}
                      placeholder={t("camera.detection.classes_placeholder")}
                      activeModels={detectionModels.map((m) => m.model)}
                    />
                  )}
                </div>
              </FieldRow>

              {/* License plate reading (basic, on by default) */}
              <FieldRow label={t("camera.detection.plates")} hint={t("camera.detection.plates_hint")}>
                <Toggle
                  checked={detectPlates}
                  onChange={setDetectPlates}
                  label={detectPlates ? t("common.enabled") : t("common.disabled")}
                />
              </FieldRow>

              {/* Model list */}
              <FieldRow label={t("camera.detection.models")} hint={t("camera.detection.models_hint")}>
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
                        title={t("camera.detection.remove_model")}
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
                    {t("camera.detection.add_model")}
                  </button>

                  {detectionModels.length === 0 && (
                    <p className="text-[11px] text-muted-foreground">
                      {t("camera.detection.no_models", { confidence: (objectConfidence * 100).toFixed(0) })}
                    </p>
                  )}
                </div>
              </FieldRow>

              {/* Fallback confidence (shown when no models configured) */}
              {detectionModels.length === 0 && (
                <FieldRow label={t("camera.detection.confidence")} hint={t("camera.detection.confidence_hint")}>
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
                  <FieldRow label={t("camera.detection.merge")} hint={t("camera.detection.merge_hint")}>
                    <div className="flex gap-1.5">
                      {([
                        { value: "any" },
                        { value: "consensus" },
                        { value: "best" },
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
                          {t(`camera.detection.merge.${opt.value}`)}
                        </button>
                      ))}
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-1.5">
                      {detectionMerge === "any"
                        ? t("camera.detection.merge_any_help")
                        : detectionMerge === "consensus"
                          ? t("camera.detection.merge_consensus_help", { count: detectionConsensusMin })
                          : t("camera.detection.merge_best_help")}
                    </p>
                  </FieldRow>

                  {detectionMerge === "consensus" && (
                    <FieldRow label={t("camera.detection.min_agreement")} hint={t("camera.detection.min_agreement_hint")}>
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

          <FieldRow label={t("camera.detection.faces")} hint={t("camera.detection.faces_hint")}>
            <Toggle
              checked={detectFaces}
              onChange={setDetectFaces}
              label={detectFaces ? t("common.enabled") : t("common.disabled")}
            />
          </FieldRow>
        </Section>
  );
}
