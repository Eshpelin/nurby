"use client";

import {
  TRIGGER_TYPES,
  TRIGGER_ACCENTS,
  AUDIO_LABELS,
  type Camera,
  type Person,
} from "./types";
import Link from "next/link";
import { ModelClassPicker } from "./ModelClassPicker";
import { StyledSelect } from "./StyledSelect";
import { GeometryEditor } from "./GeometryEditor";
import { RulePhraseInput } from "./RulePhraseInput";

export interface TriggerSectionProps {
  cameras: Camera[];
  persons: Person[];
  activeModels: string[];
  modelClasses: string[];
  modelClassesLoading: boolean;

  formTriggerType: string;
  setFormTriggerType: (v: string) => void;
  formTriggerLabel: string;
  setFormTriggerLabel: (v: string) => void;
  formTriggerMinFrames: string;
  setFormTriggerMinFrames: (v: string) => void;
  formTriggerObjectState: string;
  setFormTriggerObjectState: (v: string) => void;
  formTriggerZones: string[];
  setFormTriggerZones: (v: string[]) => void;
  formTriggerPersonId: string;
  setFormTriggerPersonId: (v: string) => void;
  formTriggerSensitivity: string;
  setFormTriggerSensitivity: (v: string) => void;
  formTriggerAudioLabel: string;
  setFormTriggerAudioLabel: (v: string) => void;
  formTriggerAudioMinScore: string;
  setFormTriggerAudioMinScore: (v: string) => void;
  formTriggerLineDirection: string;
  setFormTriggerLineDirection: (v: string) => void;
  formTriggerGeomCamId: string;
  setFormTriggerGeomCamId: (v: string) => void;
  formTriggerGeomPoints: number[][];
  setFormTriggerGeomPoints: (v: number[][]) => void;
  formTriggerLoiterSeconds: string;
  setFormTriggerLoiterSeconds: (v: string) => void;
  formTriggerObjectClass: string;
  setFormTriggerObjectClass: (v: string) => void;
  formTriggerClapCount: string;
  setFormTriggerClapCount: (v: string) => void;
  formTriggerPhrases: string[];
  setFormTriggerPhrases: (v: string[]) => void;
  formTriggerPhraseMatch: "any" | "all";
  setFormTriggerPhraseMatch: (v: "any" | "all") => void;
  formTriggerPlateMode: "blacklist" | "whitelist";
  setFormTriggerPlateMode: (v: "blacklist" | "whitelist") => void;
  formTriggerPlateList: string;
  setFormTriggerPlateList: (v: string) => void;
  formTriggerSpotZone: string;
  setFormTriggerSpotZone: (v: string) => void;
  formTriggerReservedPlates: string;
  setFormTriggerReservedPlates: (v: string) => void;
  formTriggerRequireStationary: boolean;
  setFormTriggerRequireStationary: (v: boolean) => void;
  formTriggerAllowedDirection: "in" | "out";
  setFormTriggerAllowedDirection: (v: "in" | "out") => void;
  formTriggerRequirePlate: boolean;
  setFormTriggerRequirePlate: (v: boolean) => void;
  formTriggerGeomPointsB: number[][];
  setFormTriggerGeomPointsB: (v: number[][]) => void;
  formTriggerDistanceM: string;
  setFormTriggerDistanceM: (v: string) => void;
  formTriggerMinSpeedKmh: string;
  setFormTriggerMinSpeedKmh: (v: string) => void;
  formTriggerRedAfter: string;
  setFormTriggerRedAfter: (v: string) => void;
  formTriggerRedBefore: string;
  setFormTriggerRedBefore: (v: string) => void;
  formTriggerSignalZone: string;
  setFormTriggerSignalZone: (v: string) => void;
  formTriggerCrosswalkZone: string;
  setFormTriggerCrosswalkZone: (v: string) => void;
  formTriggerLaneZone: string;
  setFormTriggerLaneZone: (v: string) => void;
  formTriggerMinVehicles: string;
  setFormTriggerMinVehicles: (v: string) => void;
  formTriggerSustainSeconds: string;
  setFormTriggerSustainSeconds: (v: string) => void;
}

export function TriggerSection(props: TriggerSectionProps) {
  const {
    cameras,
    persons,
    activeModels,
    modelClasses,
    modelClassesLoading,
    formTriggerType,
    setFormTriggerType,
    formTriggerLabel,
    setFormTriggerLabel,
    formTriggerMinFrames,
    setFormTriggerMinFrames,
    formTriggerObjectState,
    setFormTriggerObjectState,
    formTriggerZones,
    setFormTriggerZones,
    formTriggerPersonId,
    setFormTriggerPersonId,
    formTriggerSensitivity,
    setFormTriggerSensitivity,
    formTriggerAudioLabel,
    setFormTriggerAudioLabel,
    formTriggerAudioMinScore,
    setFormTriggerAudioMinScore,
    formTriggerLineDirection,
    setFormTriggerLineDirection,
    formTriggerGeomCamId,
    setFormTriggerGeomCamId,
    formTriggerGeomPoints,
    setFormTriggerGeomPoints,
    formTriggerLoiterSeconds,
    setFormTriggerLoiterSeconds,
    formTriggerObjectClass,
    setFormTriggerObjectClass,
    formTriggerClapCount,
    setFormTriggerClapCount,
    formTriggerPhrases,
    setFormTriggerPhrases,
    formTriggerPhraseMatch,
    setFormTriggerPhraseMatch,
    formTriggerPlateMode,
    setFormTriggerPlateMode,
    formTriggerPlateList,
    setFormTriggerPlateList,
    formTriggerSpotZone,
    setFormTriggerSpotZone,
    formTriggerReservedPlates,
    setFormTriggerReservedPlates,
    formTriggerRequireStationary,
    setFormTriggerRequireStationary,
    formTriggerAllowedDirection,
    setFormTriggerAllowedDirection,
    formTriggerRequirePlate,
    setFormTriggerRequirePlate,
    formTriggerGeomPointsB,
    setFormTriggerGeomPointsB,
    formTriggerDistanceM,
    setFormTriggerDistanceM,
    formTriggerMinSpeedKmh,
    setFormTriggerMinSpeedKmh,
    formTriggerRedAfter,
    setFormTriggerRedAfter,
    formTriggerRedBefore,
    setFormTriggerRedBefore,
    formTriggerSignalZone,
    setFormTriggerSignalZone,
    formTriggerCrosswalkZone,
    setFormTriggerCrosswalkZone,
    formTriggerLaneZone,
    setFormTriggerLaneZone,
    formTriggerMinVehicles,
    setFormTriggerMinVehicles,
    formTriggerSustainSeconds,
    setFormTriggerSustainSeconds,
  } = props;

  return (
    <fieldset className="border border-border rounded-md p-3 space-y-3">
      <legend className="text-xs font-medium text-muted-foreground px-1">
        When should this rule fire
      </legend>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        {TRIGGER_TYPES.map((t) => {
          const selected = formTriggerType === t.value;
          const accent = TRIGGER_ACCENTS[t.accent] || TRIGGER_ACCENTS.slate;
          return (
            <button
              key={t.value}
              type="button"
              onClick={() => setFormTriggerType(t.value)}
              className={`relative text-left rounded-md border p-3 transition-all ${
                selected
                  ? `${accent.active} ring-2`
                  : "border-border bg-background hover:bg-muted/60"
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <t.icon className={selected ? "text-foreground" : "text-muted-foreground"} />
                <span className="text-sm font-medium">{t.label}</span>
                {selected && <span className={`ml-auto w-2 h-2 rounded-full ${accent.dot}`} />}
              </div>
              <div className="text-[11px] text-muted-foreground leading-snug">{t.desc}</div>
            </button>
          );
        })}
      </div>

      {formTriggerType === "object_detected" && (
        <div className="space-y-3">
          <ModelClassPicker
            value={formTriggerLabel}
            onChange={setFormTriggerLabel}
            activeModels={activeModels}
            classes={modelClasses}
            loading={modelClassesLoading}
            anyLabel="Any object"
          />
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Confirmation</label>
            <div className="flex gap-1.5">
              {([
                { v: "1", l: "Instant" },
                { v: "2", l: "2 frames" },
                { v: "3", l: "3 frames" },
                { v: "5", l: "5 frames" },
              ] as const).map((m) => (
                <button
                  key={m.v}
                  type="button"
                  onClick={() => setFormTriggerMinFrames(m.v)}
                  className={`px-3 py-1.5 text-sm rounded-md border transition-colors ${
                    formTriggerMinFrames === m.v
                      ? "border-green-500 bg-green-500/10 text-green-300"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {m.l}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground mt-1.5">
              How many keyframes the same object must persist before firing.
              Instant reacts fastest; more frames kill one-frame false
              positives like headlight flare or a leaf gusting past.
            </p>
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Movement</label>
            <div className="flex gap-1.5">
              {([
                { v: "any", l: "Any" },
                { v: "moving", l: "Moving only" },
                { v: "stationary", l: "Parked & still only" },
              ] as const).map((m) => (
                <button
                  key={m.v}
                  type="button"
                  onClick={() => setFormTriggerObjectState(m.v)}
                  className={`px-3 py-1.5 text-sm rounded-md border transition-colors ${
                    formTriggerObjectState === m.v
                      ? "border-green-500 bg-green-500/10 text-green-300"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {m.l}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground mt-1.5">
              &quot;Moving only&quot; is the parked-car fix: an object that has
              held still stops re-alerting, but starts alerting again the
              moment it moves.
            </p>
          </div>
          {(() => {
            const areaNames = [
              ...new Set(
                cameras.flatMap((c) =>
                  ((c as { motion_zones?: { type?: string; name?: string }[] }).motion_zones || [])
                    .filter((z) => z.type === "zone" || z.type === "loiter")
                    .map((z) => z.name || "")
                    .filter(Boolean)
                )
              ),
            ];
            if (areaNames.length === 0) return (
              <p className="text-[11px] text-muted-foreground">
                Tip: draw a <span className="font-medium">Named area</span> on a
                camera (camera settings → Zones) and you can scope this rule to
                it, e.g. only a person in the Driveway.
              </p>
            );
            return (
              <div>
                <label className="text-xs text-muted-foreground block mb-1">
                  Only in named areas (optional)
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {areaNames.map((name) => {
                    const selected = formTriggerZones.includes(name);
                    return (
                      <button
                        key={name}
                        type="button"
                        onClick={() =>
                          setFormTriggerZones(
                            selected
                              ? formTriggerZones.filter((z) => z !== name)
                              : [...formTriggerZones, name]
                          )
                        }
                        className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
                          selected
                            ? "border-sky-500 bg-sky-500/10 text-sky-300"
                            : "border-border text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        {name}
                      </button>
                    );
                  })}
                </div>
                <p className="text-[11px] text-muted-foreground mt-1.5">
                  Fires only when the object&apos;s feet are inside one of the
                  selected areas. No selection = anywhere in frame.
                </p>
              </div>
            );
          })()}
        </div>
      )}

      {formTriggerType === "vehicle_detected" && (
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground block">License plate</label>
          <input
            value={formTriggerLabel}
            onChange={(e) => setFormTriggerLabel(e.target.value.toUpperCase())}
            placeholder="ABC123  (leave blank for any vehicle)"
            className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono"
          />
          <p className="text-[11px] text-muted-foreground">
            Matches when a plate containing this text is read. Leave blank to fire on any
            vehicle that has been read. Plate reading runs automatically on cars, trucks,
            buses, and vans.
          </p>
        </div>
      )}

      {formTriggerType === "plate_list" && (
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1.5">Mode</label>
            <div className="grid grid-cols-2 gap-1.5">
              <button
                type="button"
                onClick={() => setFormTriggerPlateMode("blacklist")}
                className={`px-3 py-2 text-xs rounded-md border text-left transition-colors ${
                  formTriggerPlateMode === "blacklist"
                    ? "border-rose-500 bg-rose-500/10 text-rose-300"
                    : "border-border hover:bg-muted"
                }`}
              >
                <div className="font-medium">Block-list</div>
                <div className="text-[10px] text-muted-foreground">Alert when a listed plate appears</div>
              </button>
              <button
                type="button"
                onClick={() => setFormTriggerPlateMode("whitelist")}
                className={`px-3 py-2 text-xs rounded-md border text-left transition-colors ${
                  formTriggerPlateMode === "whitelist"
                    ? "border-emerald-500 bg-emerald-500/10 text-emerald-300"
                    : "border-border hover:bg-muted"
                }`}
              >
                <div className="font-medium">Allow-list</div>
                <div className="text-[10px] text-muted-foreground">Alert on anyone NOT listed</div>
              </button>
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">
              {formTriggerPlateMode === "blacklist" ? "Blocked plates" : "Allowed plates"} (one per line)
            </label>
            <textarea
              value={formTriggerPlateList}
              onChange={(e) => setFormTriggerPlateList(e.target.value.toUpperCase())}
              rows={4}
              placeholder={"ABC123\nXYZ789"}
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              {formTriggerPlateMode === "blacklist"
                ? "Fires when any of these plates is read. Spacing and case are ignored."
                : "Fires on any vehicle whose plate is NOT in this list, e.g. an unknown car entering your garage."}
            </p>
          </div>
          {formTriggerPlateMode === "whitelist" && (
            <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
              <input
                type="checkbox"
                checked={!formTriggerRequirePlate}
                onChange={(e) => setFormTriggerRequirePlate(!e.target.checked)}
              />
              Also alert on vehicles whose plate cannot be read
            </label>
          )}
        </div>
      )}

      {formTriggerType === "parking_violation" && (
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Reserved spot (zone name)</label>
            <input
              value={formTriggerSpotZone}
              onChange={(e) => setFormTriggerSpotZone(e.target.value)}
              placeholder="Spot A"
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Draw the parking spot as a named zone in the camera&apos;s
              <span className="font-medium"> Zones &amp; Tripwires</span> settings, then type its exact name here.
            </p>
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Allowed plate(s) (one per line)</label>
            <textarea
              value={formTriggerReservedPlates}
              onChange={(e) => setFormTriggerReservedPlates(e.target.value.toUpperCase())}
              rows={3}
              placeholder={"MYCAR1  (leave blank to alert on ANY vehicle)"}
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              The rule fires when a vehicle that is not on this list parks in the spot.
              Leave blank to alert whenever anything parks there.
            </p>
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
            <input
              type="checkbox"
              checked={formTriggerRequireStationary}
              onChange={(e) => setFormTriggerRequireStationary(e.target.checked)}
            />
            Only alert once the vehicle is actually parked (not just passing through)
          </label>
        </div>
      )}

      {formTriggerType === "face_recognized" && (
        <div className="space-y-2">
          <label className="text-xs text-muted-foreground block">Person</label>
          {persons.length === 0 ? (
            <p className="text-xs px-2 py-3 rounded-md border border-dashed border-amber-500/40 bg-amber-500/5 text-amber-300">
              No people in your library yet, so this rule will fire for{" "}
              <span className="font-medium">any known face</span> once one
              exists. To alert on a specific person,{" "}
              <Link href="/people" className="underline hover:text-amber-200">
                add them on the People page
              </Link>{" "}
              first (name + face photo), then pick them here.
            </p>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 max-h-60 overflow-y-auto">
              <button
                type="button"
                onClick={() => setFormTriggerPersonId("")}
                className={`flex items-center gap-2 rounded-md border p-2 text-left transition-colors ${
                  formTriggerPersonId === ""
                    ? "border-sky-500 bg-sky-500/10 ring-2 ring-sky-500/40"
                    : "border-border bg-background hover:bg-muted/60"
                }`}
              >
                <span className="w-8 h-8 rounded-full bg-muted flex items-center justify-center text-xs text-muted-foreground flex-shrink-0">*</span>
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">Anyone known</div>
                  <div className="text-[10px] text-muted-foreground truncate">Any recognized face</div>
                </div>
              </button>
              {persons.map((p) => {
                const selected = formTriggerPersonId === p.id;
                const initial = (p.display_name || "?").slice(0, 1).toUpperCase();
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => setFormTriggerPersonId(p.id)}
                    className={`flex items-center gap-2 rounded-md border p-2 text-left transition-colors ${
                      selected
                        ? "border-sky-500 bg-sky-500/10 ring-2 ring-sky-500/40"
                        : "border-border bg-background hover:bg-muted/60"
                    }`}
                  >
                    {p.photo_path ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={`/api/files/${p.photo_path}`} alt="" className="w-8 h-8 rounded-full object-cover flex-shrink-0" />
                    ) : (
                      <span className="w-8 h-8 rounded-full bg-sky-500/20 text-sky-300 flex items-center justify-center text-xs font-medium flex-shrink-0">{initial}</span>
                    )}
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">{p.display_name}</div>
                      {p.relationship && <div className="text-[10px] text-muted-foreground truncate">{p.relationship}</div>}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {formTriggerType === "motion" && (
        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">
            Motion sensitivity
          </label>
          <div className="grid grid-cols-4 gap-1">
            {[
              { value: "very_high", label: "Any movement", desc: "Triggers on smallest change" },
              { value: "high", label: "Sensitive", desc: "Small movements" },
              { value: "medium", label: "Normal", desc: "Moderate activity" },
              { value: "low", label: "Only major", desc: "Large movements only" },
            ].map((s) => (
              <button
                key={s.value}
                type="button"
                onClick={() => setFormTriggerSensitivity(s.value)}
                className={`px-2 py-2 text-xs rounded border transition-colors text-center ${
                  formTriggerSensitivity === s.value
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-border hover:bg-muted"
                }`}
              >
                <div className="font-medium">{s.label}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {formTriggerType === "audio_event" && (
        <div className="space-y-2">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Sound type</label>
            <StyledSelect
              value={formTriggerAudioLabel}
              options={AUDIO_LABELS.map((a) => ({ value: a.value, label: a.label }))}
              onChange={setFormTriggerAudioLabel}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">
              Confidence threshold (0.1 low, 0.7 strict)
            </label>
            <input
              type="number" min="0.05" max="0.95" step="0.05"
              value={formTriggerAudioMinScore}
              onChange={(e) => setFormTriggerAudioMinScore(e.target.value)}
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
            />
          </div>
          <p className="text-[11px] text-muted-foreground">
            Detection runs locally on each camera&apos;s audio track. Needs an RTSP stream that publishes audio.
          </p>
        </div>
      )}

      {formTriggerType === "clap_pattern" && (
        <div className="space-y-2">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Number of claps</label>
            <div className="flex gap-1.5">
              {["2", "3", "4", "5"].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setFormTriggerClapCount(n)}
                  className={`px-3 py-1.5 text-sm rounded-md border transition-colors ${
                    formTriggerClapCount === n
                      ? "border-rose-500 bg-rose-500/10 text-rose-300"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {n} claps
                </button>
              ))}
            </div>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Counts claps that land within ~2s of each other.
            Two claps lights one action, three claps another.
            Needs audio enabled on the camera.
          </p>
        </div>
      )}

      {formTriggerType === "speech_phrase" && (
        <div className="space-y-2">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Phrases to listen for</label>
            <RulePhraseInput
              values={formTriggerPhrases}
              onChange={setFormTriggerPhrases}
              placeholder='e.g. "lights on", "we have a problem"'
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Match mode</label>
            <div className="flex gap-1.5">
              {([
                { v: "any", l: "Any phrase" },
                { v: "all", l: "All phrases" },
              ] as const).map((m) => (
                <button
                  key={m.v}
                  type="button"
                  onClick={() => setFormTriggerPhraseMatch(m.v)}
                  className={`px-3 py-1.5 text-sm rounded-md border transition-colors ${
                    formTriggerPhraseMatch === m.v
                      ? "border-rose-500 bg-rose-500/10 text-rose-300"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {m.l}
                </button>
              ))}
            </div>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Matches transcript text from the camera&apos;s STT pipeline.
            Case-insensitive substring. Needs audio + transcription enabled.
          </p>
        </div>
      )}

      {(formTriggerType === "camera_offline" || formTriggerType === "camera_online" || formTriggerType === "incident_started" || formTriggerType === "incident_ended") && (
        <div className="space-y-2">
          <label className="text-xs text-muted-foreground block mb-1.5">
            Which camera (optional)
          </label>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            <button
              type="button"
              onClick={() => setFormTriggerGeomCamId("")}
              className={`flex items-center gap-2 rounded-md border p-2 text-left transition-colors ${
                !formTriggerGeomCamId
                  ? "border-rose-500 bg-rose-500/10 ring-2 ring-rose-500/40"
                  : "border-border bg-background hover:bg-muted/60"
              }`}
            >
              <span className="text-sm font-medium">Any camera</span>
            </button>
            {cameras.map((cam) => {
              const selected = formTriggerGeomCamId === cam.id;
              return (
                <button
                  key={cam.id}
                  type="button"
                  onClick={() => setFormTriggerGeomCamId(cam.id)}
                  className={`flex items-center gap-2 rounded-md border p-2 text-left transition-colors ${
                    selected
                      ? "border-rose-500 bg-rose-500/10 ring-2 ring-rose-500/40"
                      : "border-border bg-background hover:bg-muted/60"
                  }`}
                >
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                    cam.status === "recording" ? "bg-green-500" :
                    cam.status === "online" ? "bg-accent" :
                    "bg-muted-foreground/40"
                  }`} />
                  <span className="text-sm font-medium truncate">{cam.name}</span>
                </button>
              );
            })}
          </div>
          <p className="text-[11px] text-muted-foreground">
            {formTriggerType === "camera_offline"
              ? "Fires when the camera stops responding: power cut, network drop, or tampering. Pair with a cooldown so a flaky camera does not spam you."
              : formTriggerType === "camera_online"
              ? "Fires when a camera recovers after being offline. Useful to close the loop on an outage alert."
              : formTriggerType === "incident_started"
              ? "Fires the moment repeat sightings of the same person or vehicle cluster into a new incident."
              : "Fires once when an incident closes, carrying its duration, sighting count, and an AI-written recap your webhook, email, or Telegram message can include."}
          </p>
        </div>
      )}

      {(formTriggerType === "loitering" || formTriggerType === "line_cross" || formTriggerType === "wrong_way" || formTriggerType === "red_light_cross") && (
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1.5">Pick a camera</label>
            {cameras.length === 0 ? (
              <p className="text-xs text-muted-foreground px-2 py-3 rounded-md border border-dashed border-border">
                No cameras yet. Add one on the Cameras page first.
              </p>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {cameras.map((cam) => {
                  const selected = formTriggerGeomCamId === cam.id;
                  return (
                    <button
                      key={cam.id}
                      type="button"
                      onClick={() => {
                        setFormTriggerGeomCamId(cam.id);
                        setFormTriggerGeomPoints([]);
                      }}
                      className={`flex items-center gap-2 rounded-md border p-2 text-left transition-colors ${
                        selected
                          ? "border-indigo-500 bg-indigo-500/10 ring-2 ring-indigo-500/40"
                          : "border-border bg-background hover:bg-muted/60"
                      }`}
                    >
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                        cam.status === "recording" ? "bg-green-500" :
                        cam.status === "online" ? "bg-accent" :
                        "bg-muted-foreground/40"
                      }`} />
                      <span className="text-sm font-medium truncate">{cam.name}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {formTriggerGeomCamId && (() => {
            const cam = cameras.find((c) => c.id === formTriggerGeomCamId);
            if (!cam) return null;
            return (
              <div>
                <label className="text-xs text-muted-foreground block mb-1.5">
                  {formTriggerType === "line_cross"
                    ? "Draw tripwire. Click two points on the feed."
                    : formTriggerType === "wrong_way"
                    ? "Draw the lane line. Click two points across the lane."
                    : formTriggerType === "red_light_cross"
                    ? "Draw the stop line. Click two points across the lane."
                    : "Draw loiter zone. Click at least three points."}
                </label>
                <GeometryEditor
                  camera={cam}
                  mode={formTriggerType === "line_cross" || formTriggerType === "wrong_way" || formTriggerType === "red_light_cross" ? "line" : "polygon"}
                  points={formTriggerGeomPoints}
                  onChange={setFormTriggerGeomPoints}
                />
              </div>
            );
          })()}

          <div>
            <label className="text-xs text-muted-foreground block mb-1">Which objects count (optional)</label>
            <ModelClassPicker
              value={formTriggerObjectClass}
              onChange={setFormTriggerObjectClass}
              activeModels={activeModels}
              classes={modelClasses}
              loading={modelClassesLoading}
              anyLabel="Any tracked object"
            />
          </div>

          {formTriggerType === "loitering" && (
            <div>
              <label className="text-xs text-muted-foreground block mb-1">
                Loiter threshold (seconds inside the zone)
              </label>
              <div className="flex gap-1 flex-wrap">
                {["10", "30", "60", "120", "300"].map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setFormTriggerLoiterSeconds(s)}
                    className={`px-3 py-1.5 text-xs rounded border transition-colors ${
                      formTriggerLoiterSeconds === s
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-border hover:bg-muted"
                    }`}
                  >{parseInt(s) >= 60 ? `${Math.round(parseInt(s) / 60)} min` : `${s}s`}</button>
                ))}
                <input
                  type="number"
                  min="1"
                  value={formTriggerLoiterSeconds}
                  onChange={(e) => setFormTriggerLoiterSeconds(e.target.value)}
                  className="w-20 px-2 py-1.5 text-xs rounded border border-border bg-background"
                />
              </div>
            </div>
          )}

          {formTriggerType === "line_cross" && (
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Direction</label>
              <div className="grid grid-cols-3 gap-1">
                {[
                  { v: "any", l: "Either way" },
                  { v: "in", l: "Inbound" },
                  { v: "out", l: "Outbound" },
                ].map((d) => (
                  <button
                    key={d.v}
                    type="button"
                    onClick={() => setFormTriggerLineDirection(d.v)}
                    className={`px-2 py-2 text-xs rounded border transition-colors ${
                      formTriggerLineDirection === d.v
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-border hover:bg-muted"
                    }`}
                  >{d.l}</button>
                ))}
              </div>
            </div>
          )}
          {formTriggerType === "wrong_way" && (
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Allowed direction of travel</label>
              <div className="grid grid-cols-2 gap-1">
                {[
                  { v: "in", l: "This way is OK" },
                  { v: "out", l: "That way is OK" },
                ].map((d) => (
                  <button
                    key={d.v}
                    type="button"
                    onClick={() => setFormTriggerAllowedDirection(d.v as "in" | "out")}
                    className={`px-2 py-2 text-xs rounded border transition-colors ${
                      formTriggerAllowedDirection === d.v
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-border hover:bg-muted"
                    }`}
                  >{d.l}</button>
                ))}
              </div>
              <p className="text-[11px] text-muted-foreground mt-1.5">
                Pick the legal direction across the line. The rule fires on a
                vehicle crossing the OTHER way. Use &quot;Run test&quot; below to
                confirm the side after drawing.
              </p>
            </div>
          )}

          {formTriggerType === "red_light_cross" && (
            <div className="space-y-3">
              <div>
                <label className="text-xs text-muted-foreground block mb-1">
                  Signal zone (auto-detected colour)
                </label>
                <input
                  value={formTriggerSignalZone}
                  onChange={(e) => setFormTriggerSignalZone(e.target.value)}
                  placeholder="Signal North"
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                />
                <p className="text-[11px] text-muted-foreground mt-1">
                  Draw a <span className="font-medium">Traffic signal</span> zone over the light in the
                  camera&apos;s <span className="font-medium">Zones &amp; Tripwires</span> settings, then type
                  its exact name here. Nurby reads the lamp colour and fires only when it is red. Leave
                  blank to use a manual time window instead.
                </p>
              </div>
              {!formTriggerSignalZone.trim() && (
            <div>
              <label className="text-xs text-muted-foreground block mb-1">
                Red-light window (local time)
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="time"
                  value={formTriggerRedAfter}
                  onChange={(e) => setFormTriggerRedAfter(e.target.value)}
                  className="px-2 py-1.5 rounded-md bg-background border border-border text-sm"
                />
                <span className="text-xs text-muted-foreground">to</span>
                <input
                  type="time"
                  value={formTriggerRedBefore}
                  onChange={(e) => setFormTriggerRedBefore(e.target.value)}
                  className="px-2 py-1.5 rounded-md bg-background border border-border text-sm"
                />
              </div>
              <p className="text-[11px] text-muted-foreground mt-1.5">
                Only crossings inside this window count. Leave both blank to
                treat the light as always red. Overnight windows (e.g. 22:00
                to 06:00) wrap midnight. This manual window is the fallback
                when no signal zone is set above.
              </p>
            </div>
              )}
            </div>
          )}
        </div>
      )}

      {formTriggerType === "speed_over" && (
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1.5">Pick a camera</label>
            {cameras.length === 0 ? (
              <p className="text-xs text-muted-foreground px-2 py-3 rounded-md border border-dashed border-border">
                No cameras yet. Add one on the Cameras page first.
              </p>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {cameras.map((cam) => {
                  const selected = formTriggerGeomCamId === cam.id;
                  return (
                    <button
                      key={cam.id}
                      type="button"
                      onClick={() => {
                        setFormTriggerGeomCamId(cam.id);
                        setFormTriggerGeomPoints([]);
                        setFormTriggerGeomPointsB([]);
                      }}
                      className={`flex items-center gap-2 rounded-md border p-2 text-left transition-colors ${
                        selected
                          ? "border-rose-500 bg-rose-500/10 ring-2 ring-rose-500/40"
                          : "border-border bg-background hover:bg-muted/60"
                      }`}
                    >
                      <span className="text-sm font-medium truncate">{cam.name}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          {formTriggerGeomCamId && (() => {
            const cam = cameras.find((c) => c.id === formTriggerGeomCamId);
            if (!cam) return null;
            return (
              <>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1.5">
                    Gate 1. Click two points across the lane.
                  </label>
                  <GeometryEditor camera={cam} mode="line" points={formTriggerGeomPoints} onChange={setFormTriggerGeomPoints} />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1.5">
                    Gate 2. A second line further along the lane.
                  </label>
                  <GeometryEditor camera={cam} mode="line" points={formTriggerGeomPointsB} onChange={setFormTriggerGeomPointsB} />
                </div>
              </>
            );
          })()}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Real distance between gates (metres)</label>
              <input
                type="number"
                min="1"
                step="0.5"
                value={formTriggerDistanceM}
                onChange={(e) => setFormTriggerDistanceM(e.target.value)}
                className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Alert above (km/h)</label>
              <input
                type="number"
                min="1"
                value={formTriggerMinSpeedKmh}
                onChange={(e) => setFormTriggerMinSpeedKmh(e.target.value)}
                className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-sm"
              />
            </div>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Nurby times a vehicle between the two gates and divides by the
            real distance you measured on the ground. This is approximate
            (roughly within 10-20%), good for catching a speeder on your
            street, not for legal citations.
          </p>
        </div>
      )}

      {formTriggerType === "crosswalk_violation" && (
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Crosswalk (zone name)</label>
            <input
              value={formTriggerCrosswalkZone}
              onChange={(e) => setFormTriggerCrosswalkZone(e.target.value)}
              placeholder="Crosswalk"
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Draw the crossing as a named zone in the camera&apos;s
              <span className="font-medium"> Zones &amp; Tripwires</span> settings, then type its exact name
              here. The rule fires when a vehicle and a pedestrian are in the zone at the same time.
            </p>
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Vehicle type (optional)</label>
            <input
              value={formTriggerObjectClass}
              onChange={(e) => setFormTriggerObjectClass(e.target.value)}
              placeholder="any vehicle (car, truck, bus, motorcycle)"
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
            />
          </div>
        </div>
      )}

      {formTriggerType === "lane_occupancy" && (
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Lane (zone name)</label>
            <input
              value={formTriggerLaneZone}
              onChange={(e) => setFormTriggerLaneZone(e.target.value)}
              placeholder="Lane 1"
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Draw the lane as a named zone in the camera&apos;s
              <span className="font-medium"> Zones &amp; Tripwires</span> settings, then type its exact name here.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Alert at (vehicles)</label>
              <input
                type="number"
                min="1"
                value={formTriggerMinVehicles}
                onChange={(e) => setFormTriggerMinVehicles(e.target.value)}
                className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Vehicle type (optional)</label>
              <input
                value={formTriggerObjectClass}
                onChange={(e) => setFormTriggerObjectClass(e.target.value)}
                placeholder="any vehicle"
                className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-sm"
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
            <input
              type="checkbox"
              checked={formTriggerRequireStationary}
              onChange={(e) => setFormTriggerRequireStationary(e.target.checked)}
            />
            Only count stopped vehicles (a real backup, not free-flowing traffic)
          </label>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Must hold for (seconds)</label>
            <input
              type="number"
              min="0"
              value={formTriggerSustainSeconds}
              onChange={(e) => setFormTriggerSustainSeconds(e.target.value)}
              className="w-24 px-2 py-1.5 rounded-md bg-background border border-border text-sm"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              The lane must stay over the threshold this long before firing. 0 fires on the
              first frame; a few seconds avoids a brief cluster passing through.
            </p>
          </div>
        </div>
      )}
    </fieldset>
  );
}
