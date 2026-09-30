"use client";

// Builder UI for temporal sequence rules (docs/sequence-rules-design.md).
// The base trigger above is step 0; this section adds the ordered "and then"
// steps, how they correlate to a subject, and what fires on completion
// (the rule's main action chain) vs on timeout (the absence alert).

import { ActionsSection } from "./ActionsSection";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";
import {
  defaultSeqStep,
  describeSeqStep,
  SEQ_CORRELATE_OPTIONS,
  SEQ_KINDS_NO_LABEL,
  type ActionDraft,
  type Camera,
  type DeviceOption,
  type Person,
  type ProviderOption,
  type SeqCheckKind,
  type SeqStepDraft,
  type TelegramChannelOption,
} from "./types";

export interface SequenceSectionProps {
  enabled: boolean;
  setEnabled: (v: boolean) => void;
  correlateBy: string;
  setCorrelateBy: (v: string) => void;
  onRefire: "ignore" | "restart";
  setOnRefire: (v: "ignore" | "restart") => void;
  maxActive: string;
  setMaxActive: (v: string) => void;
  steps: SeqStepDraft[];
  setSteps: (updater: SeqStepDraft[] | ((p: SeqStepDraft[]) => SeqStepDraft[])) => void;
  timeoutActions: ActionDraft[];
  setTimeoutActions: (updater: ActionDraft[] | ((p: ActionDraft[]) => ActionDraft[])) => void;
  telegramChannels: TelegramChannelOption[];
  telegramChannelsLoading: boolean;
  devices: DeviceOption[];
  persons: Person[];
  providers: ProviderOption[];
  cameras: Camera[];
}

const SELECT_CLS =
  "px-2 py-1.5 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent";
const INPUT_CLS =
  "px-2 py-1.5 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent";

export function SequenceSection(props: SequenceSectionProps) {
  const {
    enabled, setEnabled, correlateBy, setCorrelateBy, onRefire, setOnRefire,
    maxActive, setMaxActive, steps, setSteps, timeoutActions, setTimeoutActions,
    telegramChannels, telegramChannelsLoading, devices, persons, providers, cameras,
  } = props;
  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);

  // Named areas drawn on any camera (Settings → Zones), for zone/loiter steps.
  const areaNames = [
    ...new Set(
      cameras.flatMap((c) =>
        ((c as { motion_zones?: { type?: string; name?: string }[] }).motion_zones || [])
          .filter((z) => z.type === "zone" || z.type === "loiter")
          .map((z) => z.name || "")
          .filter(Boolean),
      ),
    ),
  ];

  const patchStep = (i: number, patch: Partial<SeqStepDraft>) =>
    setSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  const removeStep = (i: number) => setSteps((prev) => prev.filter((_, idx) => idx !== i));
  const addStep = () => setSteps((prev) => [...prev, defaultSeqStep("object")]);

  const correlateHint = SEQ_CORRELATE_OPTIONS.find((o) => o.value === correlateBy)?.hint || "";
  const summary =
    steps.length > 0
      ? t("sequence.summary_then", { steps: steps.map(describeSeqStep).join(`, ${t("sequence.then_separator")} `) })
      : t("sequence.add_step_required");

  return (
    <div className="border border-border rounded-md">
      <label className="flex items-start gap-2 px-3 py-2.5 cursor-pointer">
        <input
          type="checkbox"
          className="mt-0.5 accent-green-500"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        <span className="min-w-0">
          <span className="text-xs font-medium text-foreground">{t("sequence.enable")}</span>
          <span className="block text-[11px] text-muted-foreground mt-0.5">
            {t("sequence.enable_help")}
          </span>
        </span>
      </label>

      {enabled && (
        <div className="px-3 pb-3 pt-1 space-y-4 border-t border-border">
          {/* Correlation */}
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1">
              {t("sequence.track_same")}
            </label>
            <select
              value={correlateBy}
              onChange={(e) => setCorrelateBy(e.target.value)}
              className={`${SELECT_CLS} w-full`}
            >
              {SEQ_CORRELATE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            {correlateHint && (
              <div className="text-[11px] text-muted-foreground mt-1">{correlateHint}</div>
            )}
          </div>

          {/* Steps */}
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-1">{t("sequence.then_order")}</div>
            <div className="space-y-2">
              {steps.map((s, i) => (
                <div key={i} className="border border-border rounded-md p-2 space-y-2 bg-muted/20">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-muted-foreground shrink-0 w-10">{t("sequence.step", { number: i + 1 })}</span>
                    <select
                      value={s.kind}
                      onChange={(e) => patchStep(i, { kind: e.target.value as SeqCheckKind })}
                      className={SELECT_CLS}
                    >
                      <option value="object">{t("sequence.kind_object")}</option>
                      <option value="locate">{t("sequence.kind_locate")}</option>
                      <option value="verify">{t("sequence.kind_verify")}</option>
                      <option value="motion">{t("sequence.kind_motion")}</option>
                      <option value="face">{t("sequence.kind_face")}</option>
                      <option value="known_face">{t("sequence.kind_known_face")}</option>
                      <option value="audio">{t("sequence.kind_audio")}</option>
                      <option value="zone">{t("sequence.kind_zone")}</option>
                      <option value="loiter">{t("sequence.kind_loiter")}</option>
                    </select>
                    <button
                      type="button"
                      onClick={() => removeStep(i)}
                      disabled={steps.length <= 1}
                      className="ml-auto text-[11px] text-muted-foreground hover:text-red-400 disabled:opacity-30"
                    >
                      {t("sequence.remove")}
                    </button>
                  </div>

                  {!SEQ_KINDS_NO_LABEL.includes(s.kind) && (
                    <input
                      type="text"
                      value={s.label}
                      onChange={(e) => patchStep(i, { label: e.target.value })}
                      placeholder={
                        s.kind === "locate"
                          ? t("sequence.placeholder_locate")
                            : s.kind === "verify"
                            ? t("sequence.placeholder_verify")
                            : s.kind === "audio"
                              ? t("sequence.placeholder_audio")
                              : s.kind === "zone"
                                ? t("sequence.placeholder_zone")
                                : t("sequence.placeholder_object")
                      }
                      className={`${INPUT_CLS} w-full`}
                    />
                  )}

                  {(s.kind === "zone" || s.kind === "loiter") && (
                    <div className="flex items-center gap-2 flex-wrap">
                      {areaNames.length === 0 ? (
                        <span className="text-[11px] text-amber-400/90">
                          {t("sequence.no_areas")}
                        </span>
                      ) : (
                        <select
                          value={s.zoneName}
                          onChange={(e) => patchStep(i, { zoneName: e.target.value })}
                          className={SELECT_CLS}
                        >
                          <option value="">{t("sequence.pick_area")}</option>
                          {areaNames.map((name) => (
                            <option key={name} value={name}>{name}</option>
                          ))}
                        </select>
                      )}
                      {s.kind === "loiter" && (
                        <>
                          <span className="text-[11px] text-muted-foreground">{t("sequence.for")}</span>
                          <input
                            type="number"
                            min={1}
                            value={s.dwellSeconds}
                            onChange={(e) => patchStep(i, { dwellSeconds: e.target.value })}
                            className={`${INPUT_CLS} w-20`}
                          />
                          <span className="text-[11px] text-muted-foreground">{t("sequence.seconds")}</span>
                        </>
                      )}
                    </div>
                  )}

                  {s.kind === "known_face" && (
                    <select
                      value={s.personId}
                      onChange={(e) => patchStep(i, { personId: e.target.value })}
                      className={`${SELECT_CLS} w-full`}
                    >
                      <option value="">{t("sequence.anyone_known")}</option>
                      {persons.map((p) => (
                        <option key={p.id} value={p.id}>{p.display_name}</option>
                      ))}
                    </select>
                  )}

                  {s.kind === "verify" && (
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[11px] text-muted-foreground">{t("sequence.min_confidence")}</span>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.05}
                        value={s.minConfidence}
                        onChange={(e) => patchStep(i, { minConfidence: e.target.value })}
                        title={t("sequence.confidence_help")}
                        className={`${INPUT_CLS} w-20`}
                      />
                      <select
                        value={s.providerId}
                        onChange={(e) => patchStep(i, { providerId: e.target.value })}
                        title={t("sequence.model_help")}
                        className={SELECT_CLS}
                      >
                        <option value="">{t("sequence.default_model")}</option>
                        {providers.map((p) => (
                          <option key={p.id} value={p.id}>{p.name} ({p.kind})</option>
                        ))}
                      </select>
                    </div>
                  )}

                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[11px] text-muted-foreground">{t("sequence.within")}</span>
                    <input
                      type="number"
                      min={1}
                      value={s.withinSeconds}
                      onChange={(e) => patchStep(i, { withinSeconds: e.target.value })}
                      className={`${INPUT_CLS} w-20`}
                    />
                    <span className="text-[11px] text-muted-foreground">{t("sequence.seconds_confirm")}</span>
                    <input
                      type="number"
                      min={1}
                      value={s.confirmFrames}
                      onChange={(e) => patchStep(i, { confirmFrames: e.target.value })}
                      title={t("sequence.frames_help")}
                      className={`${INPUT_CLS} w-16`}
                    />
                    <span className="text-[11px] text-muted-foreground">{t("sequence.frames")}</span>
                  </div>

                  <label className="flex items-center gap-2 text-[11px] text-muted-foreground cursor-pointer">
                    <input
                      type="checkbox"
                      className="accent-green-500"
                      checked={s.negate}
                      onChange={(e) => patchStep(i, { negate: e.target.checked })}
                    />
                    {t("sequence.negate")}
                  </label>

                  {s.kind === "locate" && (
                    <div className="space-y-2 border-t border-border pt-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-[11px] text-muted-foreground">{t("sequence.only_when_present")}</span>
                        <input
                          type="text"
                          value={s.preGateLabel}
                          onChange={(e) => patchStep(i, { preGateLabel: e.target.value })}
                          placeholder={t("sequence.pregate_placeholder")}
                          className={`${INPUT_CLS} flex-1 min-w-[8rem]`}
                        />
                      </div>
                      <label className="flex items-center gap-2 text-[11px] text-muted-foreground cursor-pointer">
                        <input
                          type="checkbox"
                          className="accent-green-500"
                          checked={s.requireCorroboration}
                          onChange={(e) => patchStep(i, { requireCorroboration: e.target.checked })}
                        />
                        {t("sequence.corroboration")}
                      </label>
                      <div className="text-[11px] text-amber-400/90">
                        {t("sequence.findanything_help")}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={addStep}
              className="mt-2 text-xs px-2 py-1 rounded border border-border hover:bg-muted transition-colors"
            >
              {t("sequence.add_step")}
            </button>
          </div>

          {/* Control */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1">
                {t("sequence.retrigger")}
              </label>
              <select
                value={onRefire}
                onChange={(e) => setOnRefire(e.target.value as "ignore" | "restart")}
                className={`${SELECT_CLS} w-full`}
              >
                <option value="ignore">{t("sequence.ignore_retrigger")}</option>
                <option value="restart">{t("sequence.restart_retrigger")}</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1">
                {t("sequence.max_concurrent")}
              </label>
              <input
                type="number"
                min={1}
                value={maxActive}
                onChange={(e) => setMaxActive(e.target.value)}
                className={`${INPUT_CLS} w-full`}
              />
            </div>
          </div>

          {/* on_timeout chain */}
          <div className="border-t border-border pt-3">
            <div className="text-xs font-medium text-foreground mb-1">{t("sequence.timeout_title")}</div>
            <div className="text-[11px] text-muted-foreground mb-2">
              {t("sequence.timeout_help")} {" "}
              <code className="text-foreground">{"{{vars.trigger.camera_name}}"}</code>. Leave empty to
              {t("sequence.timeout_empty")}
            </div>
            <ActionsSection
              telegramChannels={telegramChannels}
              telegramChannelsLoading={telegramChannelsLoading}
              devices={devices}
              providers={providers}
              cameras={cameras}
              formActions={timeoutActions}
              setFormActions={setTimeoutActions}
              cardErrors={{}}
            />
          </div>

          <div className="text-[11px] text-muted-foreground bg-muted/30 rounded px-2 py-1.5">
            {summary} {t("sequence.completion_prefix")} {timeoutActions.length > 0
              ? t("sequence.timeout_actions_run")
              : t("sequence.timeout_nothing")}
          </div>
        </div>
      )}
    </div>
  );
}

export default SequenceSection;
