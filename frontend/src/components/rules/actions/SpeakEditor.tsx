"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

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
  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) =>
    translate(user?.locale, key, values);
  const set = (patch: Partial<SpeakDraft>) => onChange({ ...d, ...patch });

  const [previewing, setPreviewing] = useState(false);
  const [previewResult, setPreviewResult] = useState<string | null>(null);

  // Nobody should ship a rule whose words they have not heard. The
  // preview speaks through the chosen camera using the real path, so it
  // is subject to the same quiet hours and limits a real fire would be,
  // and says so when it refuses.
  const preview = async () => {
    if (!d.camera_id) {
      setPreviewResult(t("rules.speak.pick_camera"));
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
          ? t("rules.speak.played", { transport: body.transport })
          : t("rules.speak.not_played", { reason: body.reason ?? t("rules.speak.unknown") }),
      );
    } catch {
      setPreviewResult(t("rules.speak.camera_unreachable"));
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
        placeholder={t("rules.speak.text_placeholder")}
      />

      <div className="grid grid-cols-2 gap-2">
        <select
          value={d.camera_id}
          onChange={(e) => set({ camera_id: e.target.value })}
          className="px-3 py-2 rounded-md bg-background border border-border text-sm"
        >
          <option value="">{t("rules.speak.camera_select")}</option>
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
          placeholder={t("rules.speak.volume_placeholder")}
        />
      </div>

      <input
        type="text"
        value={d.voice}
        onChange={(e) => set({ voice: e.target.value })}
        className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
        placeholder={t("rules.speak.voice_placeholder")}
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
          title={t("rules.speak.preview_title")}
        >
          {previewing ? t("rules.speak.speaking") : t("rules.speak.hear_it")}
        </button>
        {previewResult && (
          <span className="text-xs text-muted-foreground">{previewResult}</span>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        {t("rules.speak.limits_help")}
      </p>
    </>
  );
}
