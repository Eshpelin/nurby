"use client";

import { useState } from "react";
import { CAMERA_PERSONAS, type Persona, type PersonaPatch } from "@/lib/camera-personas";

interface Props {
  // Called with the merged patch when the user confirms a persona.
  onApply: (patch: PersonaPatch, persona: Persona) => void;
  // Compact = inline, no modal. Used in the create flow.
  variant?: "compact" | "card-grid";
  // Optional label override.
  title?: string;
}

/**
 * Renders a grid of persona cards. Click a card to preview the patch
 * payload, click Apply to fire ``onApply``. The parent decides what to
 * do with the patch (overwrite local state, POST to API, etc).
 */
export function PersonaPicker({
  onApply,
  variant = "card-grid",
  title = "Quick setup",
}: Props) {
  const [previewing, setPreviewing] = useState<Persona | null>(null);

  if (variant === "compact") {
    return (
      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground block">
          {title}
        </label>
        <div className="flex flex-wrap gap-1.5">
          {CAMERA_PERSONAS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => onApply(p.patch, p)}
              title={p.hint}
              className="px-2.5 py-1.5 text-xs rounded-md border border-border hover:border-accent hover:bg-accent/10 hover:text-accent-foreground transition-colors flex items-center gap-1.5"
            >
              <PersonaIcon path={p.iconPath} className="w-3.5 h-3.5" />
              {p.label}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-3">
        <div>
          <h3 className="text-sm font-medium">{title}</h3>
          <p className="text-xs text-muted-foreground">
            Pick a preset to fill the camera config in one click. You can
            still edit anything afterward.
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {CAMERA_PERSONAS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setPreviewing(p)}
              className="text-left p-3 rounded-lg border border-border hover:border-accent hover:bg-accent/5 transition-colors group"
            >
              <div className="flex items-center gap-2 mb-1.5">
                <PersonaIcon path={p.iconPath} className="w-4 h-4 text-accent" />
                <div className="font-medium text-sm">{p.label}</div>
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                {p.hint}
              </p>
            </button>
          ))}
        </div>
      </div>

      {previewing && (
        <PersonaPreviewModal
          persona={previewing}
          onCancel={() => setPreviewing(null)}
          onConfirm={() => {
            const p = previewing;
            setPreviewing(null);
            onApply(p.patch, p);
          }}
        />
      )}
    </>
  );
}

function PersonaIcon({
  path,
  className,
}: {
  path: string;
  className?: string;
}) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={path} />
    </svg>
  );
}

function PersonaPreviewModal({
  persona,
  onCancel,
  onConfirm,
}: {
  persona: Persona;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  // Render the patch as a friendly bullet list so the user knows what's
  // about to change. Fields with no value are skipped.
  const lines = describePatch(persona.patch);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="rounded-lg border border-border bg-card p-5 max-w-md w-full shadow-2xl">
        <div className="flex items-center gap-2 mb-2">
          <PersonaIcon path={persona.iconPath} className="w-5 h-5 text-accent" />
          <h2 className="text-base font-semibold">{persona.label}</h2>
        </div>
        <p className="text-xs text-muted-foreground mb-4">{persona.hint}</p>
        <div className="text-xs space-y-1 mb-5 max-h-64 overflow-y-auto pr-1">
          {lines.map((l, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-muted-foreground/60 mt-0.5">·</span>
              <span>{l}</span>
            </div>
          ))}
        </div>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-3 py-1.5 text-xs rounded-md bg-accent text-accent-foreground font-medium hover:opacity-90"
          >
            Apply preset
          </button>
        </div>
      </div>
    </div>
  );
}

function describePatch(p: PersonaPatch): string[] {
  const out: string[] = [];
  if (p.scene_mode) out.push(`Scene: ${p.scene_mode}`);
  if (p.detection_models?.length) {
    out.push(`Detection models: ${p.detection_models.map((m) => m.model).join(", ")}`);
  }
  if (p.vlm_trigger === "on_object" && p.vlm_trigger_objects?.length) {
    out.push(`VLM trigger: ${p.vlm_trigger_objects.join(", ")}`);
  } else if (p.vlm_trigger === "always") {
    out.push("VLM trigger: every keyframe");
  }
  if (p.recording_mode) {
    if (p.recording_mode === "on_object" && p.recording_trigger_objects?.length) {
      out.push(`Recording: on detection of ${p.recording_trigger_objects.join(", ")}`);
    } else {
      out.push(`Recording: ${p.recording_mode}`);
    }
  }
  if (p.retention_mode === "time" && p.retention_days)
    out.push(`Retention: ${p.retention_days} days`);
  if (p.retention_mode === "size" && p.retention_gb)
    out.push(`Retention: ${p.retention_gb} GB max`);
  if (p.summary_mode && p.summary_mode !== "off") {
    if (p.summary_mode === "event" && p.summary_event_trigger_objects?.length)
      out.push(`Summaries: event-bound on ${p.summary_event_trigger_objects.join(", ")}`);
    else if (p.summary_mode === "periodic" && p.summary_period_seconds)
      out.push(`Summaries: every ${Math.round(p.summary_period_seconds / 60)} min`);
    else out.push(`Summaries: ${p.summary_mode}`);
  }
  if (p.audio_capture_enabled) {
    out.push(
      p.audio_transcribe_enabled
        ? "Audio: capture + transcribe"
        : "Audio: capture only"
    );
  } else if (p.audio_capture_enabled === false) {
    out.push("Audio: off");
  }
  if (p.detect_faces === false) out.push("Face recognition: off");
  return out;
}
