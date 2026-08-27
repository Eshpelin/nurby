"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

// Inline SVG glyphs. The frontend does not bundle lucide-react.
const ArrowLeft = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="19" y1="12" x2="5" y2="12" />
    <polyline points="12 19 5 12 12 5" />
  </svg>
);
const Speaker = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
    <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
    <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
  </svg>
);

import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/time";

interface Capability {
  probed: boolean;
  supported: boolean | null;
  transport: string | null;
  codec?: string | null;
  vendor?: string | null;
  probed_at?: string | null;
  summary: string;
}

interface VoiceConfig {
  id: string;
  name: string;
  preset: string;
  speaker_enabled: boolean;
  speaker_transport: string | null;
  speaker_voice: string | null;
  speaker_volume: number;
  speaker_quiet_start: string | null;
  speaker_quiet_end: string | null;
  speaker_cooldown_seconds: number;
  speaker_daily_cap: number;
  speaker_endpoint: boolean;
  capability: Capability;
}

interface PresetOption {
  key: string;
  label: string;
  description: string;
}

interface SpeechEvent {
  id: string;
  trigger: string;
  text: string;
  status: string;
  suppressed_reason: string | null;
  transport: string | null;
  error_message: string | null;
  created_at: string | null;
}

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Suppression is not failure. A camera that correctly stayed quiet at 3am
// did its job, and colouring that red trains people to ignore red.
const STATUS_STYLES: Record<string, string> = {
  played: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  suppressed: "bg-zinc-500/15 text-zinc-300 border-zinc-600/40",
  failed: "bg-red-500/15 text-red-300 border-red-500/30",
  queued: "bg-blue-500/15 text-blue-300 border-blue-500/30",
};

const REASON_TEXT: Record<string, string> = {
  quiet_hours: "quiet hours",
  cooldown: "still in cooldown",
  daily_cap: "daily limit reached",
  disabled: "voice turned off",
  estop: "Nurby paused",
  unsupported: "camera cannot play audio",
  empty_text: "nothing to say",
  policy: "blocked by policy",
};

export default function CameraVoicePage() {
  const params = useParams();
  const cameraId = params?.id as string;
  const { token } = useAuth();

  const [config, setConfig] = useState<VoiceConfig | null>(null);
  const [presets, setPresets] = useState<PresetOption[]>([]);
  const [events, setEvents] = useState<SpeechEvent[]>([]);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const authHeaders = useCallback(
    () => ({ Authorization: `Bearer ${token}` }),
    [token],
  );

  const loadEvents = useCallback(async () => {
    const resp = await fetch(
      `${API}/api/voice/events?camera_id=${cameraId}&limit=50`,
      { headers: authHeaders() },
    );
    if (resp.ok) setEvents((await resp.json()).events ?? []);
  }, [cameraId, authHeaders]);

  useEffect(() => {
    if (!token || !cameraId) return;
    (async () => {
      try {
        const [cfgResp, presetResp] = await Promise.all([
          fetch(`${API}/api/voice/cameras/${cameraId}`, { headers: authHeaders() }),
          fetch(`${API}/api/voice/presets`, { headers: authHeaders() }),
        ]);
        if (!cfgResp.ok) throw new Error(await cfgResp.text());
        setConfig(await cfgResp.json());
        if (presetResp.ok) setPresets((await presetResp.json()).presets ?? []);
        await loadEvents();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Could not load voice settings");
      }
    })();
  }, [token, cameraId, authHeaders, loadEvents]);

  const update = async (patch: Record<string, unknown>) => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      const resp = await fetch(`${API}/api/voice/cameras/${cameraId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(patch),
      });
      if (!resp.ok) throw new Error(await resp.text());
      setConfig(await resp.json());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const resp = await fetch(`${API}/api/voice/cameras/${cameraId}/test`, {
        method: "POST",
        headers: authHeaders(),
      });
      const body = await resp.json();
      if (body.spoken) {
        setTestResult(`Played through ${body.transport}.`);
      } else {
        // The test runs through the real guards, so a refusal here is
        // the same refusal a rule would get. Say which one it was.
        const reason = REASON_TEXT[body.reason] ?? body.reason ?? "unknown";
        setTestResult(`Not played: ${reason}${body.detail ? ` (${body.detail})` : ""}`);
      }
      await loadEvents();
    } catch (e: unknown) {
      setTestResult(e instanceof Error ? e.message : "Test failed");
    } finally {
      setTesting(false);
    }
  };

  if (!config) {
    return (
      <div className="min-h-screen bg-black text-zinc-200 p-8">
        <div className="text-zinc-400">
          {error ?? "Loading voice settings."}
        </div>
      </div>
    );
  }

  const cap = config.capability;
  const capTone = !cap.probed
    ? "border-zinc-700 bg-zinc-900/60 text-zinc-400"
    : cap.supported
      ? "border-emerald-600/40 bg-emerald-500/10 text-emerald-300"
      : "border-amber-600/40 bg-amber-500/10 text-amber-300";

  return (
    <div className="min-h-screen bg-black text-zinc-200 p-8">
      <div className="max-w-3xl mx-auto">
        <Link
          href={`/cameras/${cameraId}`}
          className="inline-flex items-center gap-2 text-xs text-zinc-500 hover:text-zinc-300 mb-4"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to {config.name}
        </Link>

        <h1 className="flex items-center gap-2 text-lg font-medium text-zinc-100 mb-1">
          <Speaker className="w-5 h-5 text-zinc-400" />
          Voice
        </h1>
        <p className="text-xs text-zinc-500 mb-6">
          What this camera is allowed to say out loud, and when.
        </p>

        {error && (
          <div className="mb-4 rounded-md border border-red-600/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {error}
          </div>
        )}

        {/* Capability. Stated plainly, including when we have not looked. */}
        <section className={`rounded-lg border p-4 mb-6 ${capTone}`}>
          <div className="text-xs font-medium mb-1">
            {!cap.probed
              ? "Speaker not checked"
              : cap.supported
                ? "Speaker available"
                : "No usable speaker"}
          </div>
          <p className="text-xs opacity-90">{cap.summary}</p>
          {cap.probed_at && (
            <p className="text-[11px] opacity-60 mt-1">
              Checked {formatDateTime(cap.probed_at)}
              {cap.vendor ? ` · ${cap.vendor}` : ""}
            </p>
          )}
        </section>

        {/* Presets are the product; the numbers below are the escape hatch. */}
        <section className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 mb-6">
          <h2 className="text-sm font-medium text-zinc-300 mb-1">How it behaves</h2>
          <p className="text-xs text-zinc-500 mb-4">
            Pick an intent. The timing and volume follow from it, and you can
            still adjust them below.
          </p>
          <div className="grid gap-2">
            {presets.map((preset) => {
              const active = config.preset === preset.key;
              return (
                <button
                  key={preset.key}
                  disabled={saving || preset.key === "custom"}
                  onClick={() => update({ preset: preset.key })}
                  className={`text-left rounded-md border px-3 py-2.5 transition ${
                    active
                      ? "border-emerald-600/50 bg-emerald-500/10"
                      : "border-zinc-800 bg-zinc-900/40 hover:border-zinc-700"
                  } ${preset.key === "custom" ? "cursor-default opacity-70" : ""}`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-zinc-200">
                      {preset.label}
                    </span>
                    {active && (
                      <span className="text-[10px] uppercase tracking-wide text-emerald-400">
                        current
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-zinc-500 mt-1">{preset.description}</p>
                </button>
              );
            })}
          </div>
        </section>

        <section className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 mb-6">
          <h2 className="text-sm font-medium text-zinc-300 mb-4">Details</h2>

          <label className="flex items-center justify-between gap-3 mb-4">
            <span className="text-xs text-zinc-400">
              Allow this camera to speak
            </span>
            <input
              type="checkbox"
              checked={config.speaker_enabled}
              disabled={saving}
              onChange={(e) => update({ speaker_enabled: e.target.checked })}
              className="accent-emerald-500"
            />
          </label>

          <div className="grid sm:grid-cols-2 gap-4">
            <label className="block">
              <span className="text-xs text-zinc-400">Volume ceiling</span>
              <input
                type="number"
                min={1}
                max={100}
                value={config.speaker_volume}
                disabled={saving}
                onChange={(e) => update({ speaker_volume: Number(e.target.value) })}
                className="mt-1 w-full rounded-md border border-zinc-800 bg-black px-2 py-1.5 text-xs text-zinc-200"
              />
              <span className="text-[11px] text-zinc-600">
                A rule cannot exceed this.
              </span>
            </label>

            <label className="block">
              <span className="text-xs text-zinc-400">Voice</span>
              <input
                type="text"
                value={config.speaker_voice ?? ""}
                placeholder="household default"
                disabled={saving}
                onChange={(e) => update({ speaker_voice: e.target.value || null })}
                className="mt-1 w-full rounded-md border border-zinc-800 bg-black px-2 py-1.5 text-xs text-zinc-200"
              />
            </label>

            <label className="block">
              <span className="text-xs text-zinc-400">Quiet from</span>
              <input
                type="time"
                value={config.speaker_quiet_start ?? ""}
                disabled={saving}
                onChange={(e) => update({ speaker_quiet_start: e.target.value || null })}
                className="mt-1 w-full rounded-md border border-zinc-800 bg-black px-2 py-1.5 text-xs text-zinc-200"
              />
            </label>

            <label className="block">
              <span className="text-xs text-zinc-400">Quiet until</span>
              <input
                type="time"
                value={config.speaker_quiet_end ?? ""}
                disabled={saving}
                onChange={(e) => update({ speaker_quiet_end: e.target.value || null })}
                className="mt-1 w-full rounded-md border border-zinc-800 bg-black px-2 py-1.5 text-xs text-zinc-200"
              />
            </label>

            <label className="block">
              <span className="text-xs text-zinc-400">Cooldown (seconds)</span>
              <input
                type="number"
                min={0}
                value={config.speaker_cooldown_seconds}
                disabled={saving}
                onChange={(e) =>
                  update({ speaker_cooldown_seconds: Number(e.target.value) })
                }
                className="mt-1 w-full rounded-md border border-zinc-800 bg-black px-2 py-1.5 text-xs text-zinc-200"
              />
              <span className="text-[11px] text-zinc-600">0 means no cooldown.</span>
            </label>

            <label className="block">
              <span className="text-xs text-zinc-400">Most times per day</span>
              <input
                type="number"
                min={0}
                value={config.speaker_daily_cap}
                disabled={saving}
                onChange={(e) => update({ speaker_daily_cap: Number(e.target.value) })}
                className="mt-1 w-full rounded-md border border-zinc-800 bg-black px-2 py-1.5 text-xs text-zinc-200"
              />
              <span className="text-[11px] text-zinc-600">0 means no limit.</span>
            </label>
          </div>
        </section>

        {/* The test goes through the real path, guards included. */}
        <section className="rounded-lg border border-zinc-800 bg-zinc-950 p-5 mb-6">
          <h2 className="text-sm font-medium text-zinc-300 mb-1">Test it</h2>
          <p className="text-xs text-zinc-500 mb-3">
            Plays a short phrase through the same path a rule would use, with
            the same quiet hours and limits. If it refuses, it says why.
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={runTest}
              disabled={testing}
              className="px-3 py-1.5 text-xs rounded-md bg-emerald-600/20 text-emerald-300 border border-emerald-600/40 hover:bg-emerald-600/30 disabled:opacity-50"
            >
              {testing ? "Speaking." : "Say a test phrase"}
            </button>
            {testResult && (
              <span className="text-xs text-zinc-400">{testResult}</span>
            )}
          </div>
        </section>

        {/* Suppressed rows are shown too: a rule muted for a month is
            otherwise indistinguishable from one that never fired. */}
        <section className="rounded-lg border border-zinc-800 bg-zinc-950 p-5">
          <h2 className="text-sm font-medium text-zinc-300 mb-1">
            What this camera said
          </h2>
          <p className="text-xs text-zinc-500 mb-4">
            Including what it decided not to say.
          </p>
          {events.length === 0 ? (
            <p className="text-xs text-zinc-600">Nothing yet.</p>
          ) : (
            <ul className="divide-y divide-zinc-900">
              {events.map((event) => (
                <li key={event.id} className="py-2.5 flex items-start gap-3">
                  <span
                    className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] ${
                      STATUS_STYLES[event.status] ?? STATUS_STYLES.queued
                    }`}
                  >
                    {event.status}
                  </span>
                  <div className="min-w-0">
                    <p className="text-xs text-zinc-300 truncate">{event.text}</p>
                    <p className="text-[11px] text-zinc-600">
                      {event.created_at ? formatDateTime(event.created_at) : ""}
                      {event.suppressed_reason
                        ? ` · ${REASON_TEXT[event.suppressed_reason] ?? event.suppressed_reason}`
                        : ""}
                      {event.error_message ? ` · ${event.error_message}` : ""}
                      {` · ${event.trigger}`}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
