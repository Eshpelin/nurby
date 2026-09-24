"use client";

import { useCallback, useEffect, useState } from "react";

interface DisclosureKey {
  key: string;
  label: string;
  description: string;
}

interface VoiceSettings {
  voice_enabled: boolean;
  voice_conversation_enabled: boolean;
  voice_max_volume: number;
  voice_quiet_hours_start: string | null;
  voice_quiet_hours_end: string | null;
  voice_session_max_turns: number;
  voice_session_max_seconds: number;
  voice_may_confirm: string[];
  voice_never_say: string[];
  disclosure_keys: DisclosureKey[];
  always_forbidden: string[];
}

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Household-wide voice settings, including the one thing that had no UI
 * at all: what the camera is allowed to disclose to a stranger.
 *
 * Self-contained (trigger plus modal) so mounting it costs the settings
 * page a single line rather than surgery on a very large file.
 */
export function VoiceSettingsCard() {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<VoiceSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [phrase, setPhrase] = useState("");

  const headers = useCallback((): Record<string, string> => {
    const token =
      typeof window === "undefined" ? null : localStorage.getItem("token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`${API}/api/voice/settings`, {
        headers: headers(),
      });
      if (!resp.ok) {
        throw new Error(
          `Could not load voice settings (HTTP ${resp.status}).`,
        );
      }
      setSettings(await resp.json());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not load voice settings.");
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (patch: Record<string, unknown>) => {
    setSaving(true);
    setError(null);
    try {
      const resp = await fetch(`${API}/api/voice/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...headers() },
        body: JSON.stringify(patch),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const next = await resp.json();
      setSettings((prev) => (prev ? { ...prev, ...next } : prev));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const toggleDisclosure = (key: string) => {
    if (!settings) return;
    const current = settings.voice_may_confirm ?? [];
    const next = current.includes(key)
      ? current.filter((k) => k !== key)
      : [...current, key];
    save({ may_confirm: next });
  };

  const addPhrase = () => {
    if (!settings || !phrase.trim()) return;
    save({ never_say: [...(settings.voice_never_say ?? []), phrase.trim()] });
    setPhrase("");
  };

  const removePhrase = (p: string) => {
    if (!settings) return;
    save({ never_say: (settings.voice_never_say ?? []).filter((x) => x !== p) });
  };

  const on = settings?.voice_enabled ?? false;
  const talking = settings?.voice_conversation_enabled ?? false;
  const allowedCount = settings?.voice_may_confirm?.length ?? 0;

  return (
    <>
      <div className="rounded-lg border border-border bg-card px-4 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span
            className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
              on ? "bg-amber-500" : "bg-muted-foreground/40"
            }`}
          />
          <div>
            <div className="text-sm font-medium flex items-center gap-2">
              Camera Voice
              <span className="text-[10px] font-normal uppercase tracking-wider text-amber-500/80 bg-amber-500/10 border border-amber-500/30 rounded px-1 py-0.5">
                safety
              </span>
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {!on
                ? "Cameras never speak."
                : talking
                  ? `Cameras can speak and hold conversations. ${allowedCount} disclosure${allowedCount === 1 ? "" : "s"} allowed.`
                  : "Cameras can make announcements. Conversations are off."}
            </div>
          </div>
        </div>
        <button
          onClick={() => setOpen(true)}
          className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted transition-colors"
        >
          Manage
        </button>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setOpen(false)}
          />
          <div className="relative bg-card border border-border rounded-lg p-6 w-full max-w-lg shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between mb-1">
              <h2 className="text-lg font-semibold">Camera Voice</h2>
              <button
                onClick={() => setOpen(false)}
                className="text-muted-foreground hover:text-foreground text-lg leading-none"
              >
                ×
              </button>
            </div>
            <p className="text-xs text-muted-foreground mb-4 leading-relaxed">
              What your cameras may say out loud. Off by default, because a
              camera that can talk is a camera that can give something away.
            </p>

            {loading ? (
              <div className="text-xs text-muted-foreground py-6 text-center">
                Loading.
              </div>
            ) : !settings ? (
              <div className="space-y-3 py-4">
                <div className="rounded-md border border-red-600/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                  {error ?? "Could not load voice settings."}
                </div>
                <button
                  onClick={load}
                  className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted transition-colors"
                >
                  Retry
                </button>
              </div>
            ) : (
              <div className="space-y-5">
                {error && (
                  <div className="rounded-md border border-red-600/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
                    {error}
                  </div>
                )}

                {/* Two switches, not one. Wanting a deterrent announcement
                    is not agreeing to an agent holding conversations. */}
                <label className="flex items-start justify-between gap-3">
                  <span>
                    <span className="text-sm font-medium block">
                      Let cameras speak
                    </span>
                    <span className="text-xs text-muted-foreground">
                      Announcements from rules, such as a warning when someone
                      is in the garden at night.
                    </span>
                  </span>
                  <input
                    type="checkbox"
                    checked={settings.voice_enabled}
                    disabled={saving}
                    onChange={(e) => save({ voice_enabled: e.target.checked })}
                    className="accent-amber-500 mt-1"
                  />
                </label>

                <label className="flex items-start justify-between gap-3">
                  <span>
                    <span className="text-sm font-medium block">
                      Let cameras hold a conversation
                    </span>
                    <span className="text-xs text-muted-foreground">
                      Answers a visitor at the door while you are notified. You
                      can take over at any point.
                    </span>
                  </span>
                  <input
                    type="checkbox"
                    checked={settings.voice_conversation_enabled}
                    disabled={saving || !settings.voice_enabled}
                    onChange={(e) =>
                      save({ voice_conversation_enabled: e.target.checked })
                    }
                    className="accent-amber-500 mt-1"
                  />
                </label>

                {/* The gap this component exists to close. */}
                <div>
                  <div className="text-sm font-medium mb-1">
                    What a camera may confirm
                  </div>
                  <p className="text-xs text-muted-foreground mb-2 leading-relaxed">
                    Everything here is off unless you turn it on. Each one tells
                    a stranger something about your household.
                  </p>
                  <div className="space-y-1.5">
                    {settings.disclosure_keys.map((entry) => (
                      <label
                        key={entry.key}
                        className="flex items-start gap-3 rounded-md border border-border bg-background px-3 py-2"
                      >
                        <input
                          type="checkbox"
                          checked={(settings.voice_may_confirm ?? []).includes(
                            entry.key,
                          )}
                          disabled={saving}
                          onChange={() => toggleDisclosure(entry.key)}
                          className="accent-amber-500 mt-0.5"
                        />
                        <span>
                          <span className="text-xs font-medium block">
                            {entry.label}
                          </span>
                          <span className="text-[11px] text-muted-foreground">
                            {entry.description}
                          </span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                {/* Said plainly so nobody hunts for a switch that does not
                    and should not exist. */}
                <div className="rounded-md border border-border bg-background px-3 py-2">
                  <div className="text-xs font-medium mb-1">
                    Never allowed, whatever you choose
                  </div>
                  <ul className="text-[11px] text-muted-foreground list-disc pl-4 space-y-0.5">
                    {settings.always_forbidden.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>

                <div>
                  <div className="text-sm font-medium mb-1">
                    Phrases to never say
                  </div>
                  <p className="text-xs text-muted-foreground mb-2">
                    Anything you would rather a camera never said out loud.
                  </p>
                  <div className="flex items-center gap-2 mb-2">
                    <input
                      type="text"
                      value={phrase}
                      onChange={(e) => setPhrase(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") addPhrase();
                      }}
                      placeholder="the dog"
                      className="flex-1 px-3 py-1.5 rounded-md bg-background border border-border text-xs"
                    />
                    <button
                      onClick={addPhrase}
                      disabled={saving || !phrase.trim()}
                      className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted disabled:opacity-50"
                    >
                      Add
                    </button>
                  </div>
                  {(settings.voice_never_say ?? []).length === 0 ? (
                    <p className="text-[11px] text-muted-foreground">
                      Nothing blocked yet.
                    </p>
                  ) : (
                    <div className="flex flex-wrap gap-1.5">
                      {(settings.voice_never_say ?? []).map((p) => (
                        <button
                          key={p}
                          onClick={() => removePhrase(p)}
                          disabled={saving}
                          className="px-2 py-1 text-[11px] rounded-md border border-border bg-background hover:border-red-500/40 hover:text-red-300"
                          title="Remove"
                        >
                          {p} ×
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
