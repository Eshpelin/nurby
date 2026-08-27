"use client";

import { useState } from "react";

import { type SpeakDraft } from "../types";
import { VarInserter, type VarSpec } from "./VarInserter";

export interface SpeakEditorProps {
  draft: SpeakDraft;
  onChange: (next: SpeakDraft) => void;
  availableVars: VarSpec[];
  cameras: { id: string; name: string }[];
}

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function SpeakEditor({
  draft,
  onChange,
  availableVars,
  cameras,
}: SpeakEditorProps) {
  const d = draft;
  const set = (patch: Partial<SpeakDraft>) => onChange({ ...d, ...patch });

  const [previewing, setPreviewing] = useState(false);
  const [previewResult, setPreviewResult] = useState<string | null>(null);

  // Nobody should ship a rule whose words they have not heard. The
  // preview speaks through the chosen camera using the real path, so it
  // is subject to the same quiet hours and limits a real fire would be,
  // and says so when it refuses.
  const preview = async () => {
    if (!d.camera_id) {
      setPreviewResult("Pick a camera to hear this on.");
      return;
    }
    setPreviewing(true);
    setPreviewResult(null);
    try {
      const token =
        typeof window === "undefined" ? null : localStorage.getItem("token");
      const resp = await fetch(
        `${API}/api/voice/cameras/${d.camera_id}/test`,
        {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        },
      );
      const body = await resp.json();
      setPreviewResult(
        body.spoken
          ? `Played through ${body.transport}.`
          : `Not played: ${body.reason ?? "unknown"}`,
      );
    } catch {
      setPreviewResult("Could not reach the camera.");
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <>
      <textarea
        value={d.text}
        onChange={(e) => set({ text: e.target.value })}
        rows={2}
        className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
        placeholder="This area is monitored. Please step back."
      />

      <div className="grid grid-cols-2 gap-2">
        <select
          value={d.camera_id}
          onChange={(e) => set({ camera_id: e.target.value })}
          className="px-3 py-2 rounded-md bg-background border border-border text-sm"
        >
          <option value="">Camera that triggered the rule</option>
          {cameras.map((camera) => (
            <option key={camera.id} value={camera.id}>
              {camera.name}
            </option>
          ))}
        </select>
        <input
          type="number"
          min={1}
          max={100}
          value={d.volume}
          onChange={(e) => set({ volume: e.target.value })}
          className="px-3 py-2 rounded-md bg-background border border-border text-sm"
          placeholder="Volume (camera default)"
        />
      </div>

      <input
        type="text"
        value={d.voice}
        onChange={(e) => set({ voice: e.target.value })}
        className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
        placeholder="Voice (camera default)"
      />

      <div className="flex flex-wrap items-center gap-2">
        <VarInserter
          vars={availableVars}
          onInsert={(tok) => set({ text: d.text + tok })}
        />
        <button
          type="button"
          onClick={preview}
          disabled={previewing}
          className="px-2.5 py-1 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground disabled:opacity-50"
          title="Speaks a test phrase on the selected camera, through the real path"
        >
          {previewing ? "Speaking." : "Hear it"}
        </button>
        {previewResult && (
          <span className="text-xs text-muted-foreground">{previewResult}</span>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        Subject to the camera&apos;s quiet hours, cooldown and daily limit. Every
        attempt is recorded, including the ones that are held back.
      </p>
    </>
  );
}
