"use client";

// Editor for the FindAnything "Visual condition" (locate) action. Runs the
// grounding model on the triggering frame; the chain continues if the thing is
// located. Corroboration (overlap with a YOLO detection) is OFF by default —
// it's a precision gate for common objects, but it would veto open-vocabulary
// things YOLO can't detect, which is the whole point of FindAnything. No
// confidence slider: the model has no calibrated score.

import { type LocateDraft } from "../types";
import { StyledSelect } from "../StyledSelect";

export interface LocateEditorProps {
  draft: LocateDraft;
  onChange: (next: LocateDraft) => void;
}

export function LocateEditor({ draft, onChange }: LocateEditorProps) {
  const d = draft;
  const set = (patch: Partial<LocateDraft>) => onChange({ ...d, ...patch });

  return (
    <div className="space-y-3">
      <div className="text-[11px] text-muted-foreground bg-muted/50 rounded px-2 py-1.5">
        After a cheap trigger fires (motion or an object), scan the frame for a
        specific thing described in plain language. The rest of the rule runs
        only if it&apos;s found. Needs FindAnything enabled in Settings.
      </div>
      <div className="text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded px-2 py-1.5">
        This runs a GPU vision model — it&apos;s seconds per frame, not free. It
        only fires when the trigger above does, so keep a cheap trigger and a
        cooldown (Wait between alerts) so it never runs on every frame. The
        grounding service also self-limits (one inference at a time + a result
        cache), so a chatty trigger can&apos;t pile up GPU work.
      </div>

      <div>
        <label className="text-xs text-muted-foreground block mb-1">
          What to locate
        </label>
        <textarea
          value={d.prompt}
          onChange={(e) => set({ prompt: e.target.value })}
          rows={2}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm resize-y"
          placeholder="a chicken in the coop"
        />
      </div>

      <div className="flex items-center gap-2">
        <input
          id="locate-corroborate"
          type="checkbox"
          checked={d.requireCorroboration}
          onChange={(e) => set({ requireCorroboration: e.target.checked })}
          className="accent-green-500"
        />
        <label htmlFor="locate-corroborate" className="text-xs text-muted-foreground">
          Require a YOLO detection in the same spot — a precision gate. Leave
          OFF for open-vocabulary things (a chicken, a key). Turn ON only for
          common objects (person, car) to cut false alarms.
        </label>
      </div>

      {d.requireCorroboration && (
        <div>
          <label className="text-xs text-muted-foreground block mb-1">
            Minimum overlap. {d.minOverlap.toFixed(2)}
          </label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={d.minOverlap}
            onChange={(e) => set({ minOverlap: parseFloat(e.target.value) })}
            className="w-full accent-green-500"
          />
          <div className="text-[10px] text-muted-foreground">
            How much the located box must overlap a detection to count.
          </div>
        </div>
      )}

      <div>
        <label className="text-xs text-muted-foreground block mb-1">
          If not found
        </label>
        <StyledSelect
          value={d.onFail}
          options={[
            { value: "stop", label: "Stop the rule" },
            { value: "continue", label: "Continue anyway" },
          ]}
          onChange={(v) => set({ onFail: v as LocateDraft["onFail"] })}
        />
      </div>

      <div>
        <label className="text-xs text-muted-foreground block mb-1">
          Result name (for later actions)
        </label>
        <input
          type="text"
          value={d.output}
          onChange={(e) => set({ output: e.target.value })}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono"
          placeholder="loc"
        />
        <div className="text-[10px] text-muted-foreground">
          Reference it later as {"{{vars."}
          {d.output || "loc"}
          {".found}}"}, {"{{vars."}
          {d.output || "loc"}
          {".count}}"}.
        </div>
      </div>
    </div>
  );
}

export default LocateEditor;
