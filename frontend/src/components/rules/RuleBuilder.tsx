"use client";

import { useEffect, useMemo, useReducer, useState, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import {
  composeSummary,
  describeActions,
  describeSchedule,
  describeTrigger,
  resolveCameraNames,
  draftToDict,
  defaultDraftForType,
  seqStepToDict,
  validateActionChainRefs,
  validateActionDraft,
  validateSeqStep,
  type Camera,
  type DeviceOption,
  type Person,
  type Rule,
  type TelegramChannelOption,
} from "./types";
import {
  INITIAL_RULE_FORM_STATE,
  ruleFormReducer,
  type RuleFormState,
} from "./ruleFormReducer";
import { SummaryCard } from "./SummaryCard";
import { SequenceSection } from "./SequenceSection";
import { TriggerSection } from "./TriggerSection";
import { ConditionsSection } from "./ConditionsSection";
import { ActionsSection } from "./ActionsSection";
import TestPanel from "./TestPanel";

export interface RuleBuilderProps {
  editRule: Rule | null;
  // Non-persisted hydration source (persona templates + Duplicate).
  // Treated as a NEW rule (POST on save).
  prefillRule?: Rule | null;
  cameras: Camera[];
  persons: Person[];
  devices: DeviceOption[];
  telegramChannels: TelegramChannelOption[];
  telegramChannelsLoading: boolean;
  onSaved: () => void;
  onCancel: () => void;
}

const COOLDOWN_PRESETS: { value: string; label: string }[] = [
  { value: "0", label: "Every event" },
  { value: "300", label: "Once / 5 min" },
  { value: "3600", label: "Once / hour" },
  { value: "86400", label: "Once / day" },
];

const CHATTY_TRIGGERS = new Set(["motion", "object_detected", "audio_event"]);

// Collapsible section with an always-visible one-line summary so a
// filled section can fold away and reclaim vertical space.
function CollapsibleSection({
  title,
  summary,
  defaultOpen,
  children,
}: {
  title: string;
  summary: string;
  defaultOpen: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-border rounded-md">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-muted/40 rounded-md"
      >
        <div className="min-w-0">
          <div className="text-xs font-medium text-foreground">{title}</div>
          {!open && (
            <div className="text-[11px] text-muted-foreground truncate mt-0.5">
              {summary || "Not set"}
            </div>
          )}
        </div>
        <span className="text-muted-foreground text-xs shrink-0">{open ? "▾" : "▸"}</span>
      </button>
      {open && <div className="px-3 pb-3 pt-1">{children}</div>}
    </div>
  );
}

export function RuleBuilder({
  editRule,
  prefillRule,
  cameras,
  persons,
  devices,
  telegramChannels,
  telegramChannelsLoading,
  onSaved,
  onCancel,
}: RuleBuilderProps) {
  const { authFetch } = useAuth();
  const [state, dispatch] = useReducer(ruleFormReducer, INITIAL_RULE_FORM_STATE);
  const [modelClasses, setModelClasses] = useState<string[]>([]);
  const [modelClassesLoading, setModelClassesLoading] = useState(false);
  const [cooldownCustom, setCooldownCustom] = useState(false);
  const [systemTz, setSystemTz] = useState<string>("");
  const [systemTzIsFallback, setSystemTzIsFallback] = useState(false);
  const [cardErrors, setCardErrors] = useState<Record<number, string>>({});

  const activeModels = useMemo(() => {
    const scoped =
      state.formCondCameras.length > 0
        ? cameras.filter((c) => state.formCondCameras.includes(c.id))
        : cameras;
    const set = new Set<string>();
    for (const c of scoped) {
      for (const m of c.detection_models || []) {
        if (m?.model && m.enabled !== false) set.add(m.model);
      }
    }
    return Array.from(set).sort();
  }, [cameras, state.formCondCameras]);

  useEffect(() => {
    if (activeModels.length === 0) {
      setModelClasses([]);
      return;
    }
    let cancelled = false;
    setModelClassesLoading(true);
    const params = activeModels.map((m) => `model=${encodeURIComponent(m)}`).join("&");
    authFetch(`/api/detection-models/classes?${params}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data?.classes) setModelClasses(data.classes);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setModelClassesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeModels, authFetch]);

  // Hydrate once on mount from edit or prefill.
  useEffect(() => {
    if (editRule) dispatch({ type: "hydrate", rule: editRule });
    else if (prefillRule) dispatch({ type: "hydrate", rule: prefillRule });
    else dispatch({ type: "reset" });
    setCooldownCustom(false);
    setCardErrors({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;
    const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    authFetch("/api/system/settings")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return;
        const tz = data?.system_timezone;
        if (typeof tz === "string" && tz) {
          setSystemTz(tz);
          setSystemTzIsFallback(false);
        } else {
          setSystemTz(browserTz);
          setSystemTzIsFallback(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSystemTz(browserTz);
          setSystemTzIsFallback(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  const triggerPattern = useMemo(() => {
    const s = state;
    const p: Record<string, unknown> = { type: s.formTriggerType };
    if (s.formTriggerType === "object_detected" && s.formTriggerLabel) p.label = s.formTriggerLabel;
    if (s.formTriggerType === "object_detected" && parseInt(s.formTriggerMinFrames) > 1) p.min_frames = parseInt(s.formTriggerMinFrames);
    if (s.formTriggerType === "object_detected" && s.formTriggerObjectState !== "any") p.object_state = s.formTriggerObjectState;
    if (s.formTriggerType === "object_detected" && s.formTriggerZones.length > 0) p.zones = s.formTriggerZones;
    if (s.formTriggerType === "vehicle_detected" && s.formTriggerLabel.trim()) p.plate = s.formTriggerLabel.trim();
    if (s.formTriggerType === "face_recognized" && s.formTriggerPersonId) p.person_id = s.formTriggerPersonId;
    if (s.formTriggerType === "motion") p.min_score = 0.08;
    if (s.formTriggerType === "audio_event") {
      p.label = s.formTriggerAudioLabel;
      p.min_score = parseFloat(s.formTriggerAudioMinScore) || 0.3;
    }
    if (s.formTriggerType === "loitering") {
      if (s.formTriggerGeomCamId) p.camera_id = s.formTriggerGeomCamId;
      if (s.formTriggerGeomPoints.length >= 3) p.points = s.formTriggerGeomPoints;
      p.threshold_seconds = parseInt(s.formTriggerLoiterSeconds) || 30;
      if (s.formTriggerObjectClass) p.label = s.formTriggerObjectClass;
    }
    if (s.formTriggerType === "line_cross") {
      if (s.formTriggerGeomCamId) p.camera_id = s.formTriggerGeomCamId;
      if (s.formTriggerGeomPoints.length === 2) p.points = s.formTriggerGeomPoints;
      if (s.formTriggerLineDirection !== "any") p.direction = s.formTriggerLineDirection;
      if (s.formTriggerObjectClass) p.label = s.formTriggerObjectClass;
    }
    if (s.formTriggerType === "camera_offline" || s.formTriggerType === "camera_online" || s.formTriggerType === "incident_started" || s.formTriggerType === "incident_ended") {
      if (s.formTriggerGeomCamId) p.camera_id = s.formTriggerGeomCamId;
    }
    return p;
  }, [state]);

  const scheduleSummary = useMemo(
    () =>
      state.formScheduleMode === "custom"
        ? describeSchedule(
            state.formCondDays.length > 0 ? state.formCondDays : undefined,
            state.formCondTimeAfter || undefined,
            state.formCondTimeBefore || undefined,
          )
        : "",
    [state.formScheduleMode, state.formCondDays, state.formCondTimeAfter, state.formCondTimeBefore],
  );

  const conditionsSummary = useMemo(() => {
    const parts: string[] = [];
    const cams = resolveCameraNames(state.formCondCameras, cameras);
    parts.push(cams ? `On ${cams}` : "On any camera");
    if (scheduleSummary) parts.push(scheduleSummary);
    if (state.formCondConfidence !== "any") parts.push(`${state.formCondConfidence} confidence`);
    return parts.join(", ");
  }, [state.formCondCameras, state.formCondConfidence, scheduleSummary, cameras]);

  const formSummary = useMemo(() => {
    const actionDicts = state.formActions.map(draftToDict);
    return composeSummary(
      describeTrigger(triggerPattern),
      resolveCameraNames(state.formCondCameras, cameras),
      scheduleSummary,
      describeActions(actionDicts.length === 1 ? actionDicts[0] : actionDicts),
      parseInt(state.formCooldown) || 0,
    );
  }, [state.formActions, state.formCondCameras, state.formCooldown, triggerPattern, scheduleSummary, cameras]);

  const buildPayload = () => {
    const s = state;
    const trigger_pattern: Record<string, unknown> = { type: s.formTriggerType };
    if (s.formTriggerType === "object_detected" && s.formTriggerLabel) trigger_pattern.label = s.formTriggerLabel;
    if (s.formTriggerType === "object_detected" && parseInt(s.formTriggerMinFrames) > 1) trigger_pattern.min_frames = parseInt(s.formTriggerMinFrames);
    if (s.formTriggerType === "object_detected" && s.formTriggerObjectState !== "any") trigger_pattern.object_state = s.formTriggerObjectState;
    if (s.formTriggerType === "object_detected" && s.formTriggerZones.length > 0) trigger_pattern.zones = s.formTriggerZones;
    if (s.formTriggerType === "vehicle_detected" && s.formTriggerLabel.trim()) trigger_pattern.plate = s.formTriggerLabel.trim();
    if (s.formTriggerType === "face_recognized" && s.formTriggerPersonId) trigger_pattern.person_id = s.formTriggerPersonId;
    if (s.formTriggerType === "motion") {
      const sensitivityMap: Record<string, number> = { very_high: 0.01, high: 0.03, medium: 0.08, low: 0.2 };
      trigger_pattern.min_score = sensitivityMap[s.formTriggerSensitivity] ?? 0.08;
    }
    if (s.formTriggerType === "audio_event") {
      trigger_pattern.label = s.formTriggerAudioLabel;
      trigger_pattern.min_score = parseFloat(s.formTriggerAudioMinScore) || 0.3;
    }
    if (s.formTriggerType === "clap_pattern") trigger_pattern.count = parseInt(s.formTriggerClapCount) || 2;
    if (s.formTriggerType === "speech_phrase") {
      trigger_pattern.phrases = s.formTriggerPhrases;
      trigger_pattern.match = s.formTriggerPhraseMatch;
    }
    if (s.formTriggerType === "loitering") {
      if (s.formTriggerGeomCamId) trigger_pattern.camera_id = s.formTriggerGeomCamId;
      if (s.formTriggerGeomPoints.length >= 3) trigger_pattern.points = s.formTriggerGeomPoints;
      trigger_pattern.threshold_seconds = parseInt(s.formTriggerLoiterSeconds) || 30;
      if (s.formTriggerObjectClass) trigger_pattern.label = s.formTriggerObjectClass;
    }
    if (s.formTriggerType === "line_cross") {
      if (s.formTriggerGeomCamId) trigger_pattern.camera_id = s.formTriggerGeomCamId;
      if (s.formTriggerGeomPoints.length === 2) trigger_pattern.points = s.formTriggerGeomPoints;
      if (s.formTriggerLineDirection !== "any") trigger_pattern.direction = s.formTriggerLineDirection;
      if (s.formTriggerObjectClass) trigger_pattern.label = s.formTriggerObjectClass;
    }
    if (s.formTriggerType === "camera_offline" || s.formTriggerType === "camera_online" || s.formTriggerType === "incident_started" || s.formTriggerType === "incident_ended") {
      if (s.formTriggerGeomCamId) trigger_pattern.camera_id = s.formTriggerGeomCamId;
    }
    if (s.formTriggerType === "plate_list") {
      trigger_pattern.mode = s.formTriggerPlateMode;
      trigger_pattern.plates = s.formTriggerPlateList
        .split(/[\n,]/)
        .map((p) => p.trim())
        .filter(Boolean);
      if (s.formTriggerPlateMode === "whitelist") {
        trigger_pattern.require_plate = s.formTriggerRequirePlate;
      }
    }
    if (s.formTriggerType === "parking_violation") {
      trigger_pattern.spot_zone = s.formTriggerSpotZone.trim();
      trigger_pattern.reserved_plates = s.formTriggerReservedPlates
        .split(/[\n,]/)
        .map((p) => p.trim())
        .filter(Boolean);
      trigger_pattern.require_stationary = s.formTriggerRequireStationary;
    }
    if (s.formTriggerType === "wrong_way") {
      if (s.formTriggerGeomCamId) trigger_pattern.camera_id = s.formTriggerGeomCamId;
      if (s.formTriggerGeomPoints.length === 2) trigger_pattern.points = s.formTriggerGeomPoints;
      trigger_pattern.allowed_direction = s.formTriggerAllowedDirection;
      if (s.formTriggerObjectClass) trigger_pattern.label = s.formTriggerObjectClass;
    }
    if (s.formFireOncePerVisit) trigger_pattern.fire_once_per = "visit";
    if (s.formTriggerType === "speed_over") {
      if (s.formTriggerGeomCamId) trigger_pattern.camera_id = s.formTriggerGeomCamId;
      if (s.formTriggerGeomPoints.length === 2) trigger_pattern.line_a = s.formTriggerGeomPoints;
      if (s.formTriggerGeomPointsB.length === 2) trigger_pattern.line_b = s.formTriggerGeomPointsB;
      trigger_pattern.distance_m = parseFloat(s.formTriggerDistanceM) || 10;
      trigger_pattern.min_speed_kmh = parseFloat(s.formTriggerMinSpeedKmh) || 30;
      if (s.formTriggerObjectClass) trigger_pattern.label = s.formTriggerObjectClass;
    }
    if (s.formTriggerType === "red_light_cross") {
      if (s.formTriggerGeomCamId) trigger_pattern.camera_id = s.formTriggerGeomCamId;
      if (s.formTriggerGeomPoints.length === 2) trigger_pattern.points = s.formTriggerGeomPoints;
      if (s.formTriggerLineDirection !== "any") trigger_pattern.direction = s.formTriggerLineDirection;
      // A signal zone (detected colour) takes precedence; otherwise fall
      // back to the manual red time window.
      if (s.formTriggerSignalZone.trim()) {
        trigger_pattern.signal_zone = s.formTriggerSignalZone.trim();
      } else {
        if (s.formTriggerRedAfter) trigger_pattern.red_after = s.formTriggerRedAfter;
        if (s.formTriggerRedBefore) trigger_pattern.red_before = s.formTriggerRedBefore;
      }
      if (s.formTriggerObjectClass) trigger_pattern.label = s.formTriggerObjectClass;
    }
    if (s.formTriggerType === "crosswalk_violation") {
      trigger_pattern.crosswalk_zone = s.formTriggerCrosswalkZone.trim();
      if (s.formTriggerObjectClass) trigger_pattern.vehicle_label = s.formTriggerObjectClass;
    }
    if (s.formTriggerType === "lane_occupancy") {
      trigger_pattern.lane_zone = s.formTriggerLaneZone.trim();
      trigger_pattern.min_vehicles = parseInt(s.formTriggerMinVehicles) || 3;
      trigger_pattern.require_stationary = s.formTriggerRequireStationary;
      const sustain = parseInt(s.formTriggerSustainSeconds) || 0;
      if (sustain > 0) trigger_pattern.sustain_seconds = sustain;
      if (s.formTriggerObjectClass) trigger_pattern.label = s.formTriggerObjectClass;
    }

    const conditions: Record<string, unknown> = {};
    if (s.formCondCameras.length > 0) conditions.camera_ids = s.formCondCameras;
    if (s.formScheduleMode === "custom") {
      if (s.formCondTimeAfter) conditions.time_after = s.formCondTimeAfter;
      if (s.formCondTimeBefore) conditions.time_before = s.formCondTimeBefore;
      if (s.formCondDays.length > 0) conditions.days = s.formCondDays;
    }
    if (s.formCondConfidence !== "any") {
      const confMap: Record<string, number> = { low: 0.2, medium: 0.4, high: 0.6, very_high: 0.8 };
      conditions.min_confidence = confMap[s.formCondConfidence] ?? 0.4;
    }

    // Temporal sequence: the base trigger becomes step 0, and the sequence
    // block carries the ordered steps + correlation + the on_timeout chain.
    // The rule's main action chain (below) is on_complete.
    if (s.formSequenceEnabled && s.formSequenceSteps.length > 0) {
      const sequence: Record<string, unknown> = {
        correlate_by: s.formSequenceCorrelateBy,
        on_refire: s.formSequenceOnRefire,
        max_active: parseInt(s.formSequenceMaxActive) || 20,
        steps: s.formSequenceSteps.map(seqStepToDict),
      };
      if (s.formSequenceTimeoutActions.length > 0) {
        sequence.on_timeout = s.formSequenceTimeoutActions.map(draftToDict);
      }
      // The camera scope, if any, also bounds the sequence.
      if (s.formCondCameras.length > 0) sequence.cameras = s.formCondCameras;
      trigger_pattern.sequence = sequence;
    }

    const actionDicts = s.formActions.map(draftToDict);
    return {
      name: s.formName.trim(),
      enabled: s.formEnabled,
      trigger_pattern,
      conditions: Object.keys(conditions).length > 0 ? conditions : null,
      actions: actionDicts.length === 1 ? actionDicts[0] : actionDicts,
      cooldown_seconds: parseInt(s.formCooldown) || 300,
      severity: s.formSeverity === "detection" ? "detection" : "alert",
    };
  };

  const setError = (msg: string) => dispatch({ type: "setError", value: msg });

  const handleSubmit = async () => {
    const s = state;
    if (!s.formName.trim()) {
      setError("Name is required");
      return;
    }

    // Sequence rules: validate steps, and allow an empty on_complete chain as
    // long as the on_timeout (absence) chain has actions.
    if (s.formSequenceEnabled) {
      if (s.formSequenceSteps.length === 0) {
        setError("Add at least one sequence step");
        return;
      }
      for (let i = 0; i < s.formSequenceSteps.length; i++) {
        const e = validateSeqStep(s.formSequenceSteps[i]);
        if (e) {
          setError(`Sequence step ${i + 1}: ${e}`);
          return;
        }
      }
      if (s.formActions.length === 0 && s.formSequenceTimeoutActions.length === 0) {
        setError("Add an action for completion or for timeout");
        return;
      }
      // Per-card validation for both chains. Chain-ref checks are skipped here
      // because on_complete/on_timeout may reference {{vars.trigger.*}} /
      // {{vars.steps.*}}, which the server validates.
      for (const d of [...s.formActions, ...s.formSequenceTimeoutActions]) {
        const e = validateActionDraft(d);
        if (e) {
          setError(`Action: ${e}`);
          return;
        }
      }
      setCardErrors({});
    } else {
      if (s.formActions.length === 0) {
        setError("At least one action is required");
        return;
      }

      const errs: Record<number, string> = {};
      s.formActions.forEach((d, i) => {
        const e = validateActionDraft(d);
        if (e) errs[i] = e;
      });
      const chainErr = validateActionChainRefs(s.formActions);
      if (chainErr && !errs[chainErr.index]) errs[chainErr.index] = chainErr.message;
      if (Object.keys(errs).length > 0) {
        setCardErrors(errs);
        const first = Math.min(...Object.keys(errs).map(Number));
        setError(`Action ${first + 1}: ${errs[first]}`);
        if (typeof document !== "undefined") {
          requestAnimationFrame(() => {
            document.getElementById(`rule-action-${first}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
          });
        }
        return;
      }
      setCardErrors({});
    }

    dispatch({ type: "setSubmitting", value: true });
    setError("");
    const body = buildPayload();
    try {
      const res = editRule
        ? await authFetch(`/api/rules/${editRule.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          })
        : await authFetch("/api/rules", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
      if (!res.ok) {
        setError("Failed to save rule");
        return;
      }
      onSaved();
    } catch {
      setError("Network error");
    } finally {
      dispatch({ type: "setSubmitting", value: false });
    }
  };

  const cooldownNum = parseInt(state.formCooldown) || 0;
  const matchedPreset = COOLDOWN_PRESETS.find((p) => parseInt(p.value) === cooldownNum);
  const showCustomInput = cooldownCustom || !matchedPreset;
  const showChattyWarning = cooldownNum === 0 && CHATTY_TRIGGERS.has(state.formTriggerType);

  const setterFor =
    <K extends keyof RuleFormState>(field: K) =>
    (value: RuleFormState[K]) =>
      dispatch({ type: "setField", field, value });

  const updaterFor =
    <K extends keyof RuleFormState>(field: K) =>
    (updater: RuleFormState[K] | ((prev: RuleFormState[K]) => RuleFormState[K])) => {
      const next =
        typeof updater === "function"
          ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (updater as any)(state[field])
          : updater;
      dispatch({ type: "setField", field, value: next });
    };

  const saveLabel = state.submitting ? "Saving." : editRule ? "Save changes" : "Create rule";

  return (
    <div className="px-6 py-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between gap-4 mb-6">
        <div>
          <button
            type="button"
            onClick={onCancel}
            className="text-xs text-muted-foreground hover:text-foreground mb-1"
          >
            ← Back to rules
          </button>
          <h1 className="text-2xl font-semibold tracking-tight">
            {editRule ? "Edit rule" : "Create rule"}
          </h1>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Left. Definition */}
        <div className="lg:col-span-3 space-y-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1">Rule name</label>
            <input
              type="text"
              value={state.formName}
              onChange={(e) => dispatch({ type: "setField", field: "formName", value: e.target.value })}
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
              placeholder="e.g. Person at front door"
              autoFocus
            />
          </div>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={state.formEnabled}
              onChange={(e) => dispatch({ type: "setField", field: "formEnabled", value: e.target.checked })}
              className="accent-green-500"
            />
            <span className="text-sm">Enabled</span>
          </label>

          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Tier</span>
            {([
              { v: "alert", l: "Alert", hint: "Front page + notifications. The push-worthy tier." },
              { v: "detection", l: "Detection", hint: "Recorded and reviewable, but stays behind the Detections tab." },
            ] as const).map((t) => (
              <button
                key={t.v}
                type="button"
                title={t.hint}
                onClick={() => dispatch({ type: "setField", field: "formSeverity", value: t.v })}
                className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
                  state.formSeverity === t.v
                    ? t.v === "alert"
                      ? "border-red-500 bg-red-500/10 text-red-400"
                      : "border-border bg-muted/40 text-foreground"
                    : "border-border text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.l}
              </button>
            ))}
          </div>

          <CollapsibleSection
            title="Trigger"
            summary={describeTrigger(triggerPattern)}
            defaultOpen={!editRule}
          >
            <TriggerSection
              cameras={cameras}
              persons={persons}
              activeModels={activeModels}
              modelClasses={modelClasses}
              modelClassesLoading={modelClassesLoading}
              formTriggerType={state.formTriggerType}
              setFormTriggerType={(v) => {
                // "FindAnything" is a shortcut, not a real trigger type: the
                // engine can't run a GPU grounding call inside the live trigger
                // loop (see locate action). Selecting it sets a cheap motion
                // pre-gate and prepends a Visual-condition (locate) action the
                // user then fills in, so they get a "starter" feel safely.
                if (v === "findanything") {
                  dispatch({ type: "setTriggerType", value: "motion" });
                  dispatch({
                    type: "setFormActions",
                    value: [
                      defaultDraftForType("locate"),
                      ...state.formActions.filter((a) => a.type !== "locate"),
                    ],
                  });
                  return;
                }
                dispatch({ type: "setTriggerType", value: v });
              }}
              formTriggerLabel={state.formTriggerLabel}
              setFormTriggerLabel={setterFor("formTriggerLabel")}
              formTriggerMinFrames={state.formTriggerMinFrames}
              setFormTriggerMinFrames={setterFor("formTriggerMinFrames")}
              formTriggerObjectState={state.formTriggerObjectState}
              setFormTriggerObjectState={setterFor("formTriggerObjectState")}
              formTriggerZones={state.formTriggerZones}
              setFormTriggerZones={setterFor("formTriggerZones")}
              formTriggerPersonId={state.formTriggerPersonId}
              setFormTriggerPersonId={setterFor("formTriggerPersonId")}
              formTriggerSensitivity={state.formTriggerSensitivity}
              setFormTriggerSensitivity={setterFor("formTriggerSensitivity")}
              formTriggerAudioLabel={state.formTriggerAudioLabel}
              setFormTriggerAudioLabel={setterFor("formTriggerAudioLabel")}
              formTriggerAudioMinScore={state.formTriggerAudioMinScore}
              setFormTriggerAudioMinScore={setterFor("formTriggerAudioMinScore")}
              formTriggerLineDirection={state.formTriggerLineDirection}
              setFormTriggerLineDirection={setterFor("formTriggerLineDirection")}
              formTriggerPlateMode={state.formTriggerPlateMode}
              setFormTriggerPlateMode={setterFor("formTriggerPlateMode")}
              formTriggerPlateList={state.formTriggerPlateList}
              setFormTriggerPlateList={setterFor("formTriggerPlateList")}
              formTriggerSpotZone={state.formTriggerSpotZone}
              setFormTriggerSpotZone={setterFor("formTriggerSpotZone")}
              formTriggerReservedPlates={state.formTriggerReservedPlates}
              setFormTriggerReservedPlates={setterFor("formTriggerReservedPlates")}
              formTriggerRequireStationary={state.formTriggerRequireStationary}
              setFormTriggerRequireStationary={setterFor("formTriggerRequireStationary")}
              formTriggerAllowedDirection={state.formTriggerAllowedDirection}
              setFormTriggerAllowedDirection={setterFor("formTriggerAllowedDirection")}
              formTriggerRequirePlate={state.formTriggerRequirePlate}
              setFormTriggerRequirePlate={setterFor("formTriggerRequirePlate")}
              formTriggerGeomPointsB={state.formTriggerGeomPointsB}
              setFormTriggerGeomPointsB={updaterFor("formTriggerGeomPointsB")}
              formTriggerDistanceM={state.formTriggerDistanceM}
              setFormTriggerDistanceM={setterFor("formTriggerDistanceM")}
              formTriggerMinSpeedKmh={state.formTriggerMinSpeedKmh}
              setFormTriggerMinSpeedKmh={setterFor("formTriggerMinSpeedKmh")}
              formTriggerRedAfter={state.formTriggerRedAfter}
              setFormTriggerRedAfter={setterFor("formTriggerRedAfter")}
              formTriggerRedBefore={state.formTriggerRedBefore}
              setFormTriggerRedBefore={setterFor("formTriggerRedBefore")}
              formTriggerSignalZone={state.formTriggerSignalZone}
              setFormTriggerSignalZone={setterFor("formTriggerSignalZone")}
              formTriggerCrosswalkZone={state.formTriggerCrosswalkZone}
              setFormTriggerCrosswalkZone={setterFor("formTriggerCrosswalkZone")}
              formTriggerLaneZone={state.formTriggerLaneZone}
              setFormTriggerLaneZone={setterFor("formTriggerLaneZone")}
              formTriggerMinVehicles={state.formTriggerMinVehicles}
              setFormTriggerMinVehicles={setterFor("formTriggerMinVehicles")}
              formTriggerSustainSeconds={state.formTriggerSustainSeconds}
              setFormTriggerSustainSeconds={setterFor("formTriggerSustainSeconds")}
              formTriggerGeomCamId={state.formTriggerGeomCamId}
              setFormTriggerGeomCamId={setterFor("formTriggerGeomCamId")}
              formTriggerGeomPoints={state.formTriggerGeomPoints}
              setFormTriggerGeomPoints={(v) => dispatch({ type: "setTriggerGeomPoints", value: v })}
              formTriggerLoiterSeconds={state.formTriggerLoiterSeconds}
              setFormTriggerLoiterSeconds={setterFor("formTriggerLoiterSeconds")}
              formTriggerObjectClass={state.formTriggerObjectClass}
              setFormTriggerObjectClass={setterFor("formTriggerObjectClass")}
              formTriggerClapCount={state.formTriggerClapCount}
              setFormTriggerClapCount={setterFor("formTriggerClapCount")}
              formTriggerPhrases={state.formTriggerPhrases}
              setFormTriggerPhrases={(v) => dispatch({ type: "setTriggerPhrases", value: v })}
              formTriggerPhraseMatch={state.formTriggerPhraseMatch}
              setFormTriggerPhraseMatch={setterFor("formTriggerPhraseMatch")}
            />
          </CollapsibleSection>

          <CollapsibleSection title="Conditions" summary={conditionsSummary} defaultOpen={!editRule}>
            <ConditionsSection
              cameras={cameras}
              systemTz={systemTz}
              systemTzIsFallback={systemTzIsFallback}
              formCondCameras={state.formCondCameras}
              setFormCondCameras={setterFor("formCondCameras")}
              formScheduleMode={state.formScheduleMode}
              setFormScheduleMode={setterFor("formScheduleMode")}
              formCondDays={state.formCondDays}
              setFormCondDays={updaterFor("formCondDays")}
              formCondTimeAfter={state.formCondTimeAfter}
              setFormCondTimeAfter={setterFor("formCondTimeAfter")}
              formCondTimeBefore={state.formCondTimeBefore}
              setFormCondTimeBefore={setterFor("formCondTimeBefore")}
              formCondConfidence={state.formCondConfidence}
              setFormCondConfidence={setterFor("formCondConfidence")}
            />
          </CollapsibleSection>

          {state.formSequenceEnabled && (
            <div className="text-[11px] text-muted-foreground -mb-2 px-1">
              These actions run when the sequence completes (on complete).
            </div>
          )}
          <ActionsSection
            telegramChannels={telegramChannels}
            telegramChannelsLoading={telegramChannelsLoading}
            devices={devices}
            formActions={state.formActions}
            setFormActions={updaterFor("formActions")}
            cardErrors={cardErrors}
          />

          <SequenceSection
            enabled={state.formSequenceEnabled}
            setEnabled={setterFor("formSequenceEnabled")}
            correlateBy={state.formSequenceCorrelateBy}
            setCorrelateBy={setterFor("formSequenceCorrelateBy")}
            onRefire={state.formSequenceOnRefire}
            setOnRefire={setterFor("formSequenceOnRefire")}
            maxActive={state.formSequenceMaxActive}
            setMaxActive={setterFor("formSequenceMaxActive")}
            steps={state.formSequenceSteps}
            setSteps={updaterFor("formSequenceSteps")}
            timeoutActions={state.formSequenceTimeoutActions}
            setTimeoutActions={updaterFor("formSequenceTimeoutActions")}
            telegramChannels={telegramChannels}
            telegramChannelsLoading={telegramChannelsLoading}
            devices={devices}
          />

          <div className="border border-border rounded-md p-3">
            <label className="text-xs font-medium text-muted-foreground block mb-1">Wait between alerts</label>
            <div className="grid grid-cols-3 sm:grid-cols-5 gap-1">
              {COOLDOWN_PRESETS.map((opt) => {
                const selected = !cooldownCustom && parseInt(opt.value) === cooldownNum;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => {
                      setCooldownCustom(false);
                      dispatch({ type: "setField", field: "formCooldown", value: opt.value });
                    }}
                    className={`px-2 py-1.5 text-xs rounded border transition-colors ${
                      selected ? "border-accent bg-accent/10 text-accent" : "border-border hover:bg-muted"
                    }`}
                  >
                    {opt.label}
                  </button>
                );
              })}
              <button
                type="button"
                onClick={() => setCooldownCustom(true)}
                className={`px-2 py-1.5 text-xs rounded border transition-colors ${
                  cooldownCustom ? "border-accent bg-accent/10 text-accent" : "border-border hover:bg-muted"
                }`}
              >
                Custom
              </button>
            </div>
            {showCustomInput && (
              <div className="mt-2 flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  value={state.formCooldown}
                  onChange={(e) => dispatch({ type: "setField", field: "formCooldown", value: e.target.value })}
                  className="w-32 px-2 py-1.5 rounded-md bg-background border border-border text-sm"
                />
                <span className="text-[11px] text-muted-foreground">seconds</span>
              </div>
            )}
            {showChattyWarning && (
              <div className="mt-1 text-[11px] text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1">
                This rule will fire on every keyframe. Consider raising the cooldown.
              </div>
            )}
            <label className="mt-3 flex items-start gap-2 text-xs text-muted-foreground cursor-pointer">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={state.formFireOncePerVisit}
                onChange={(e) =>
                  dispatch({ type: "setField", field: "formFireOncePerVisit", value: e.target.checked })
                }
              />
              <span>
                <span className="text-foreground">Fire once per visit</span> — alert once
                while a subject stays on camera, not every frame. A person who lingers on
                the porch triggers one alert; a new arrival triggers a fresh one. Works
                alongside the cooldown above.
              </span>
            </label>
          </div>
        </div>

        {/* Right. Live preview + test + save (sticky) */}
        <div className="lg:col-span-2">
          <div className="lg:sticky lg:top-6 space-y-4">
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-1">In plain language</div>
              <SummaryCard text={formSummary} className="p-3" />
            </div>

            <TestPanel payload={buildPayload} existingRuleId={editRule?.id ?? null} cameras={cameras} />

            {state.formError && <div className="text-xs text-red-400">{state.formError}</div>}

            <div className="flex justify-end gap-2">
              <button
                onClick={onCancel}
                className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={state.submitting}
                className="px-4 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50"
              >
                {saveLabel}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default RuleBuilder;
