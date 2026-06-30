"use client";

// Builder UI for temporal sequence rules (docs/sequence-rules-design.md).
// The base trigger above is step 0; this section adds the ordered "and then"
// steps, how they correlate to a subject, and what fires on completion
// (the rule's main action chain) vs on timeout (the absence alert).

import { ActionsSection } from "./ActionsSection";
import {
  defaultSeqStep,
  describeSeqStep,
  SEQ_CORRELATE_OPTIONS,
  type ActionDraft,
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
}

const SELECT_CLS =
  "px-2 py-1.5 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent";
const INPUT_CLS =
  "px-2 py-1.5 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent";

export function SequenceSection(props: SequenceSectionProps) {
  const {
    enabled, setEnabled, correlateBy, setCorrelateBy, onRefire, setOnRefire,
    maxActive, setMaxActive, steps, setSteps, timeoutActions, setTimeoutActions,
    telegramChannels, telegramChannelsLoading,
  } = props;

  const patchStep = (i: number, patch: Partial<SeqStepDraft>) =>
    setSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  const removeStep = (i: number) => setSteps((prev) => prev.filter((_, idx) => idx !== i));
  const addStep = () => setSteps((prev) => [...prev, defaultSeqStep("object")]);

  const correlateHint = SEQ_CORRELATE_OPTIONS.find((o) => o.value === correlateBy)?.hint || "";
  const summary =
    steps.length > 0
      ? "Then " + steps.map(describeSeqStep).join(", then ") + "."
      : "Add at least one step.";

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
          <span className="text-xs font-medium text-foreground">Make this a multi-step sequence</span>
          <span className="block text-[11px] text-muted-foreground mt-0.5">
            The trigger above starts a timeline. Add the steps that must follow, each within a time
            window. Fire on completion, or fire when a step is missed (the absence alert).
          </span>
        </span>
      </label>

      {enabled && (
        <div className="px-3 pb-3 pt-1 space-y-4 border-t border-border">
          {/* Correlation */}
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1">
              Track the same…
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
            <div className="text-xs font-medium text-muted-foreground mb-1">Then… (in order)</div>
            <div className="space-y-2">
              {steps.map((s, i) => (
                <div key={i} className="border border-border rounded-md p-2 space-y-2 bg-muted/20">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-muted-foreground shrink-0 w-10">Step {i + 1}</span>
                    <select
                      value={s.kind}
                      onChange={(e) => patchStep(i, { kind: e.target.value as SeqCheckKind })}
                      className={SELECT_CLS}
                    >
                      <option value="object">Object detected</option>
                      <option value="locate">FindAnything (locate)</option>
                    </select>
                    <button
                      type="button"
                      onClick={() => removeStep(i)}
                      disabled={steps.length <= 1}
                      className="ml-auto text-[11px] text-muted-foreground hover:text-red-400 disabled:opacity-30"
                    >
                      Remove
                    </button>
                  </div>

                  <input
                    type="text"
                    value={s.label}
                    onChange={(e) => patchStep(i, { label: e.target.value })}
                    placeholder={s.kind === "locate" ? 'e.g. "a key in the key box"' : "e.g. package"}
                    className={`${INPUT_CLS} w-full`}
                  />

                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[11px] text-muted-foreground">within</span>
                    <input
                      type="number"
                      min={1}
                      value={s.withinSeconds}
                      onChange={(e) => patchStep(i, { withinSeconds: e.target.value })}
                      className={`${INPUT_CLS} w-20`}
                    />
                    <span className="text-[11px] text-muted-foreground">seconds · confirm</span>
                    <input
                      type="number"
                      min={1}
                      value={s.confirmFrames}
                      onChange={(e) => patchStep(i, { confirmFrames: e.target.value })}
                      title="Require this many agreeing frames within the window before the step counts. >1 cuts noise."
                      className={`${INPUT_CLS} w-16`}
                    />
                    <span className="text-[11px] text-muted-foreground">frame(s)</span>
                  </div>

                  <label className="flex items-center gap-2 text-[11px] text-muted-foreground cursor-pointer">
                    <input
                      type="checkbox"
                      className="accent-green-500"
                      checked={s.negate}
                      onChange={(e) => patchStep(i, { negate: e.target.checked })}
                    />
                    Match when this is ABSENT — order two steps for a transition (not there → there)
                  </label>

                  {s.kind === "locate" && (
                    <div className="space-y-2 border-t border-border pt-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-[11px] text-muted-foreground">only run when present:</span>
                        <input
                          type="text"
                          value={s.preGateLabel}
                          onChange={(e) => patchStep(i, { preGateLabel: e.target.value })}
                          placeholder="e.g. person (optional)"
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
                        Require a YOLO detection in the same spot — leave off for things YOLO can&apos;t see (a chicken, a key)
                      </label>
                      <div className="text-[11px] text-amber-400/90">
                        FindAnything runs a GPU vision model. The pre-gate above keeps it cheap by
                        grounding only when worthwhile.
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
              + Add step
            </button>
          </div>

          {/* Control */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1">
                If it re-triggers
              </label>
              <select
                value={onRefire}
                onChange={(e) => setOnRefire(e.target.value as "ignore" | "restart")}
                className={`${SELECT_CLS} w-full`}
              >
                <option value="ignore">Ignore (keep the timeline going)</option>
                <option value="restart">Restart from step 1</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground block mb-1">
                Max concurrent
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
            <div className="text-xs font-medium text-foreground mb-1">If a step is missed in time</div>
            <div className="text-[11px] text-muted-foreground mb-2">
              The absence alert. Runs when the timeline doesn&apos;t complete. Reference the start with{" "}
              <code className="text-foreground">{"{{vars.trigger.camera_name}}"}</code>. Leave empty to
              just record the timeout.
            </div>
            <ActionsSection
              telegramChannels={telegramChannels}
              telegramChannelsLoading={telegramChannelsLoading}
              formActions={timeoutActions}
              setFormActions={setTimeoutActions}
              cardErrors={{}}
            />
          </div>

          <div className="text-[11px] text-muted-foreground bg-muted/30 rounded px-2 py-1.5">
            {summary} On completion, the actions below run. {timeoutActions.length > 0
              ? "If a step is missed, the absence actions above run."
              : "If a step is missed, nothing fires (add absence actions above to alert)."}
          </div>
        </div>
      )}
    </div>
  );
}

export default SequenceSection;
