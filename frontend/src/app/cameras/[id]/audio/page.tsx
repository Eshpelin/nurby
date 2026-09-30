"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
// Inline SVG glyphs. The frontend does not bundle lucide-react.
const ArrowLeft = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="19" y1="12" x2="5" y2="12" />
    <polyline points="12 19 5 12 12 5" />
  </svg>
);
const Mic = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" y1="19" x2="12" y2="23" />
    <line x1="8" y1="23" x2="16" y2="23" />
  </svg>
);
const ShieldCheck = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    <polyline points="9 12 11 14 15 10" />
  </svg>
);

import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";

interface AudioConfig {
  audio_capture_enabled: boolean;
  audio_transcribe_enabled: boolean;
  audio_store_raw: boolean;
  transcript_store: string;
  audio_language: string;
  audio_retention_days: number;
  transcript_retention_days: number;
  stt_budget_minutes_per_hour: number;
  audio_stt_beam_size: number;
  audio_stt_condition_on_previous_text: boolean;
  audio_stt_no_speech_threshold: number;
}

interface Transcript {
  id: string;
  camera_id: string;
  audio_capture_id: string | null;
  started_at: string;
  ended_at: string;
  text: string;
  language: string | null;
  provider: string;
  filtered?: boolean;
}

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function CameraAudioPage() {
  const params = useParams();
  const cameraId = params?.id as string;
  const { token, user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);

  const [config, setConfig] = useState<AudioConfig | null>(null);
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showFiltered, setShowFiltered] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [summarizeMsg, setSummarizeMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !cameraId) return;
    let cancelled = false;
    (async () => {
      try {
        const camResp = await fetch(`${API}/api/cameras/${cameraId}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const cam = await camResp.json();
        if (cancelled) return;
        setConfig({
          audio_capture_enabled: !!cam.audio_capture_enabled,
          audio_transcribe_enabled: !!cam.audio_transcribe_enabled,
          audio_store_raw: !!cam.audio_store_raw,
          transcript_store: cam.transcript_store || "full",
          audio_language: cam.audio_language || "en",
          audio_retention_days: cam.audio_retention_days ?? 7,
          transcript_retention_days: cam.transcript_retention_days ?? 30,
          stt_budget_minutes_per_hour: cam.stt_budget_minutes_per_hour ?? 30,
          audio_stt_beam_size: cam.audio_stt_beam_size ?? 1,
          audio_stt_condition_on_previous_text:
            !!cam.audio_stt_condition_on_previous_text,
          audio_stt_no_speech_threshold:
            cam.audio_stt_no_speech_threshold ?? 0.6,
        });

        const txResp = await fetch(
          `${API}/api/transcripts?camera_id=${cameraId}&limit=100&include_filtered=${showFiltered}`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        const txList = await txResp.json();
        if (!cancelled) setTranscripts(Array.isArray(txList) ? txList : []);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : translate(user?.locale, "camera_audio.load_failed"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cameraId, token, showFiltered, user?.locale]);

  const runSummary = async () => {
    if (summarizing) return;
    setSummarizing(true);
    setSummarizeMsg(null);
    try {
      const resp = await fetch(`${API}/api/summaries/run`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ camera_id: cameraId, window_minutes: 30 }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      setSummarizeMsg(t("camera_audio.summary_generated"));
    } catch (e: unknown) {
      setSummarizeMsg(e instanceof Error ? e.message : t("camera_audio.summary_failed"));
    } finally {
      setSummarizing(false);
    }
  };

  const update = async (patch: Partial<AudioConfig>) => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      const resp = await fetch(`${API}/api/audio/cameras/${cameraId}/audio`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(patch),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const next = await resp.json();
      setConfig({ ...config, ...next });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("camera_audio.save_failed"));
    } finally {
      setSaving(false);
    }
  };

  if (!config) {
    return (
      <div className="min-h-screen bg-black text-zinc-200 p-8">
        <div className="text-zinc-400">{t("camera_audio.loading")}</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black text-zinc-200">
      <div className="max-w-5xl mx-auto p-8">
        <div className="flex items-center gap-3 mb-6">
          <Link
            href={`/cameras/${cameraId}`}
            className="text-zinc-400 hover:text-zinc-100"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <Mic className="w-5 h-5 text-emerald-400" />
            {t("camera_audio.title")}
          </h1>
        </div>

        <div className="mb-6 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs leading-relaxed text-amber-200">
          {t("camera_audio.warning")}
        </div>

        {error ? (
          <div className="mb-4 rounded-lg border border-red-900 bg-red-950/40 p-3 text-sm text-red-200">
            {error}
          </div>
        ) : null}

        <section className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 mb-6">
          <h2 className="text-sm font-medium text-zinc-300 mb-4 flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            {t("camera_audio.privacy")}
          </h2>
          <div className="grid gap-3">
            <ToggleRow
              label={t("camera_audio.capture")}
              hint={t("camera_audio.capture_hint")}
              value={config.audio_capture_enabled}
              onChange={(v) => update({ audio_capture_enabled: v })}
              disabled={saving}
            />
            <ToggleRow
              label={t("camera_audio.transcribe")}
              hint={t("camera_audio.transcribe_hint")}
              value={config.audio_transcribe_enabled}
              onChange={(v) => update({ audio_transcribe_enabled: v })}
              disabled={saving || !config.audio_capture_enabled}
            />
            <ToggleRow
              label={t("camera_audio.store_raw")}
              hint={t("camera_audio.store_raw_hint")}
              value={config.audio_store_raw}
              onChange={(v) => update({ audio_store_raw: v })}
              disabled={saving || !config.audio_capture_enabled}
            />
            <SelectRow
              label={t("camera_audio.transcript_storage")}
              value={config.transcript_store}
              options={[
                { v: "full", l: t("camera_audio.full_text") },
                { v: "redacted", l: t("camera_audio.redacted") },
                { v: "summary_only", l: t("camera_audio.summary_only") },
                { v: "off", l: t("camera_audio.off_live") },
              ]}
              onChange={(v) => update({ transcript_store: v })}
              disabled={saving}
            />
            <SelectRow
              label={t("camera_audio.spoken_language")}
              value={config.audio_language}
              options={[
                { v: "auto", l: t("camera_audio.auto_detect") },
                { v: "en", l: t("language.english") },
                { v: "es", l: t("language.spanish") },
                { v: "fr", l: t("language.french") },
                { v: "de", l: t("language.german") },
                { v: "it", l: t("language.italian") },
                { v: "pt", l: t("language.portuguese") },
                { v: "nl", l: t("language.dutch") },
                { v: "pl", l: t("language.polish") },
                { v: "ru", l: t("language.russian") },
                { v: "tr", l: t("language.turkish") },
                { v: "ar", l: t("language.arabic") },
                { v: "hi", l: t("language.hindi") },
                { v: "bn", l: t("language.bengali") },
                { v: "ja", l: t("language.japanese") },
                { v: "ko", l: t("language.korean") },
                { v: "zh", l: t("language.chinese") },
              ]}
              onChange={(v) => update({ audio_language: v })}
              disabled={saving}
            />
          </div>
        </section>

        <section className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 mb-6">
          <h2 className="text-sm font-medium text-zinc-300 mb-4">{t("camera_audio.retention")}</h2>
          <div className="grid gap-3 grid-cols-2">
            <NumberRow
              label={t("camera_audio.audio_retention")}
              value={config.audio_retention_days}
              onChange={(v) => update({ audio_retention_days: v })}
              disabled={saving}
            />
            <NumberRow
              label={t("camera_audio.transcript_retention")}
              value={config.transcript_retention_days}
              onChange={(v) => update({ transcript_retention_days: v })}
              disabled={saving}
            />
            <NumberRow
              label={t("camera_audio.stt_budget")}
              value={config.stt_budget_minutes_per_hour}
              onChange={(v) => update({ stt_budget_minutes_per_hour: v })}
              disabled={saving}
            />
          </div>
        </section>

        <section className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 mb-6">
          <h2 className="text-sm font-medium text-zinc-300 mb-1">
            {t("camera_audio.accuracy")}
          </h2>
          <p className="text-xs text-zinc-500 mb-4">
            {t("camera_audio.accuracy_hint")}
          </p>
          <div className="grid gap-3">
            <SelectRow
              label={t("camera_audio.beam_size")}
              value={String(config.audio_stt_beam_size)}
              options={[
                { v: "1", l: t("camera_audio.fastest") },
                { v: "2", l: t("camera_audio.balanced") },
                { v: "3", l: t("camera_audio.better") },
                { v: "5", l: t("camera_audio.most_accurate") },
              ]}
              onChange={(v) => update({ audio_stt_beam_size: Number(v) })}
              disabled={saving}
            />
            <ToggleRow
              label={t("camera_audio.carry_context")}
              hint={t("camera_audio.carry_context_hint")}
              value={config.audio_stt_condition_on_previous_text}
              onChange={(v) =>
                update({ audio_stt_condition_on_previous_text: v })
              }
              disabled={saving}
            />
            <NumberRow
              label={t("camera_audio.silence_threshold")}
              value={config.audio_stt_no_speech_threshold}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => update({ audio_stt_no_speech_threshold: v })}
              disabled={saving}
            />
          </div>
        </section>

        <section className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 mb-6">
          <h2 className="text-sm font-medium text-zinc-300 mb-3">
            {t("camera_audio.manual_actions")}
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={runSummary}
              disabled={summarizing}
              className="px-3 py-1.5 text-xs rounded-md bg-emerald-600/20 text-emerald-300 border border-emerald-600/40 hover:bg-emerald-600/30 disabled:opacity-50"
            >
              {summarizing ? t("camera_audio.generating") : t("camera_audio.summarize")}
            </button>
            <label className="flex items-center gap-2 text-xs text-zinc-400">
              <input
                type="checkbox"
                checked={showFiltered}
                onChange={(e) => setShowFiltered(e.target.checked)}
                className="accent-emerald-500"
              />
              {t("camera_audio.show_filtered")}
            </label>
            {summarizeMsg && (
              <span className="text-xs text-zinc-400">{summarizeMsg}</span>
            )}
          </div>
        </section>

        <section className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
          <h2 className="text-sm font-medium text-zinc-300 mb-4">
            {t("camera_audio.recent_transcripts", { count: transcripts.length })}
          </h2>
          {transcripts.length === 0 ? (
            <div className="text-sm text-zinc-500">
              {t("camera_audio.no_transcripts")}
            </div>
          ) : (
            <div className="grid gap-2">
              {transcripts.map((tx) => (
                <div
                  key={tx.id}
                  className={`rounded border p-3 ${
                    tx.filtered
                      ? "border-amber-700/40 bg-amber-950/10"
                      : "border-zinc-800 bg-zinc-900"
                  }`}
                >
                  <div className="text-xs text-zinc-500 mb-1 flex items-center gap-2">
                    <span>{formatDateTime(tx.started_at)}</span>
                    <span>·</span>
                    <span>{tx.provider}</span>
                    {tx.filtered && (
                      <span className="ml-auto text-[10px] uppercase tracking-wider text-amber-400">
                        {t("camera_audio.filtered")}
                      </span>
                    )}
                  </div>
                  <div
                    className={`text-sm italic ${
                      tx.filtered ? "text-zinc-400" : "text-zinc-100"
                    }`}
                  >
                    {tx.text}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  hint,
  value,
  onChange,
  disabled,
}: {
  label: string;
  hint: string;
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <div className="text-sm text-zinc-100">{label}</div>
        <div className="text-xs text-zinc-500 mt-0.5">{hint}</div>
      </div>
      <button
        type="button"
        onClick={() => onChange(!value)}
        disabled={disabled}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition ${
          value ? "bg-emerald-500" : "bg-zinc-700"
        } ${disabled ? "opacity-40" : ""}`}
      >
        <span
          className={`inline-block h-5 w-5 transform rounded-full bg-white transition ${
            value ? "translate-x-5" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}

function SelectRow({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  options: { v: string; l: string }[];
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="text-sm text-zinc-100">{label}</div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm"
      >
        {options.map((o) => (
          <option key={o.v} value={o.v}>
            {o.l}
          </option>
        ))}
      </select>
    </div>
  );
}

function NumberRow({
  label,
  value,
  onChange,
  disabled,
  min = 0,
  max,
  step,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  disabled?: boolean;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-zinc-400">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm"
      />
    </label>
  );
}
