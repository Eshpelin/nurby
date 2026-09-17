"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { GOALS, goalsForPlace, type Experience, type ExperiencePreferences, type Goal, type Place } from "@/lib/onboarding";
import { ActivationSteps } from "@/components/ActivationSteps";
import { DailyPriorities } from "@/components/DailyPriorities";
import { DETECTION_GOALS } from "@/lib/activation";

interface Props {
  cameraCount: number;
  camerasLoading: boolean;
  onSetup: () => void;
  // Rendered inside the Getting-started launcher popover, which already
  // provides the card chrome: drop the outer border/background/margin so it
  // is not a card-in-a-card.
  embedded?: boolean;
  // Fires after preferences save, so a host (the launcher) can refresh its
  // progress badge.
  onChanged?: () => void;
}

const button = "rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted/50 disabled:opacity-50";
const primary = `${button} bg-accent text-white hover:opacity-90`;

export function PersonalOnboardingCard({ cameraCount, camerasLoading, onSetup, embedded = false, onChanged }: Props) {
  const { authFetch } = useAuth();
  const shell = embedded ? "" : "mb-4 rounded-xl border border-border bg-card p-4 sm:p-5";
  const shellSm = embedded ? "" : "mb-4 rounded-xl border border-border p-4";
  const [experience, setExperience] = useState<Experience | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState(false);
  const [draft, setDraft] = useState<ExperiencePreferences>({ version: 1, place: "home", goal: "entrance", focus: "daily" });
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const response = await authFetch("/api/auth/me/experience");
        if (!response.ok) throw new Error("load");
        const data: Experience = await response.json();
        if (cancelled) return;
        setExperience(data);
        setEditing(data.preferences === null && data.audience === "administrator");
        setDraft(data.preferences ?? { version: 1, place: "home", goal: "entrance", focus: "daily" });
      } catch {
        if (!cancelled) setError("Could not load your preferences. Your current setup is unchanged.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [authFetch, retry]);

  const save = useCallback(async (preferences: ExperiencePreferences) => {
    setSaving(true);
    setError(null);
    try {
      const response = await authFetch("/api/auth/me/experience", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(preferences),
      });
      if (!response.ok) throw new Error("save");
      setExperience(await response.json());
      setEditing(false);
      setPreview(false);
      onChanged?.();
    } catch {
      setError("Could not save your preferences. Please try again.");
    } finally {
      setSaving(false);
    }
  }, [authFetch, onChanged]);

  if (loading) return <div role="status" className={`${embedded ? "" : "mb-4 "}text-sm text-muted-foreground`}>Loading your workspace preferences…</div>;
  if (!experience) return (
    <section className={shellSm}>
      <p role="alert" className="mb-3 text-sm">{error}</p>
      <button className={button} onClick={() => setRetry((n) => n + 1)}>Retry preferences</button>
    </section>
  );
  if (experience.audience === "guardian") return (
    <section className={shellSm}>
      <h2 className="font-semibold">Your dependant updates</h2>
      <p className="my-2 text-sm text-muted-foreground">View updates and notification preferences for the people linked to your account.</p>
      <Link href="/guardian" className={button}>Open Guardian</Link>
    </section>
  );
  if (experience.audience === "viewer") return (
    <section className={shellSm}>
      <h2 className="font-semibold">Your review workspace</h2>
      <p className="my-2 text-sm text-muted-foreground">Review activity from the cameras shared with you. Your administrator manages installation and access.</p>
      {!camerasLoading && cameraCount === 0 ? (
        <p className="text-sm">No cameras are available to this account. Ask your administrator to check your access.</p>
      ) : <Link href="/timeline" className={button}>Review available activity</Link>}
    </section>
  );

  const selected = GOALS[draft.goal];
  const preferences = experience.preferences;
  const current = preferences ? GOALS[preferences.goal] : null;
  const changePlace = (place: Place) => setDraft((d) => ({ ...d, place, goal: goalsForPlace(place).includes(d.goal) ? d.goal : goalsForPlace(place)[0] }));

  return (
    <section aria-label="Your Nurby setup" className={shell}>
      {error && <p role="alert" className="mb-3 text-sm text-red-500">{error}</p>}
      {editing ? (
        <>
          <p className="mb-1 text-xs text-muted-foreground">{preview ? "2 of 2 · Review your recommendation" : "1 of 2 · Make Nurby useful to you"}</p>
          <h2 className="text-lg font-semibold">{preview ? selected.title : "What would you like help with first?"}</h2>
          {!preview ? (
            <>
              <fieldset disabled={saving} className="mt-4">
                <legend className="mb-2 text-sm font-medium">Where are you using Nurby?</legend>
                <div className="flex gap-2">
                  {(["home", "business"] as const).map((place) => (
                    <button key={place} aria-pressed={draft.place === place} className={`${button} ${draft.place === place ? "border-accent bg-accent/10" : ""}`} onClick={() => changePlace(place)}>
                      {place === "home" ? "Home" : "Small business"}
                    </button>
                  ))}
                </div>
              </fieldset>
              <fieldset disabled={saving} className="mt-4">
                <legend className="mb-2 text-sm font-medium">Choose one starting goal</legend>
                <div className="grid gap-2 sm:grid-cols-3">
                  {goalsForPlace(draft.place ?? "home").map((goal: Goal) => (
                    <button key={goal} aria-pressed={draft.goal === goal} className={`${button} text-left ${draft.goal === goal ? "border-accent bg-accent/10" : ""}`} onClick={() => setDraft((d) => ({ ...d, goal }))}>
                      <span className="block font-medium">{GOALS[goal].title}</span>
                      <span className="mt-1 block text-xs text-muted-foreground">{GOALS[goal].description}</span>
                    </button>
                  ))}
                </div>
              </fieldset>
              <label className="mt-4 block text-sm font-medium" htmlFor="experience-place-label">Name this place (optional)</label>
              <input
                id="experience-place-label"
                type="text"
                maxLength={80}
                disabled={saving}
                placeholder={draft.place === "business" ? "e.g. Front shop" : "e.g. Home"}
                className="mt-2 w-full rounded-lg border border-border bg-background p-2 text-sm sm:w-64"
                value={draft.place_label ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, place_label: e.target.value || null }))}
              />
              <label className="mt-4 block text-sm font-medium" htmlFor="experience-focus">What will you mainly do here?</label>
              <select id="experience-focus" disabled={saving} className="mt-2 rounded-lg border border-border bg-background p-2 text-sm" value={draft.focus} onChange={(e) => setDraft((d) => ({ ...d, focus: e.target.value as ExperiencePreferences["focus"] }))}>
                <option value="daily">Monitor and review day to day</option>
                <option value="setup">Set up and maintain the cameras</option>
              </select>
              <div className="mt-4 flex flex-wrap gap-2">
                <button className={primary} disabled={saving} onClick={() => setPreview(true)}>Preview recommendation</button>
                <button className={button} disabled={saving} onClick={() => save({ version: 1, place: null, goal: "explore", focus: "daily" })}>Explore first</button>
                {preferences && <button className={button} disabled={saving} onClick={() => { setEditing(false); setError(null); }}>Cancel</button>}
              </div>
            </>
          ) : (
            <>
              <p className="mt-2 text-sm">{selected.description}</p>
              <dl className="mt-4 space-y-3 text-sm">
                <div><dt className="font-medium">You will need</dt><dd className="text-muted-foreground">{selected.needs}</dd></div>
                <div><dt className="font-medium">Next, configure</dt><dd className="text-muted-foreground">{selected.next}</dd></div>
                <div><dt className="font-medium">Then, test it</dt><dd className="text-muted-foreground">{selected.template ? "Create a real event at the camera, check that the alert reaches you, and open its evidence. A saved rule alone does not prove this works." : "Open a real event and confirm its evidence is available for the time you need."}</dd></div>
              </dl>
              {draft.focus === "setup" && <p className="mt-3 text-sm">Your workspace will prioritize camera setup and system health.</p>}
              <p className="mt-3 text-xs text-muted-foreground">Saving chooses your workspace defaults. It does not create rules, enable recording or change permissions.</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button className={primary} disabled={saving} onClick={() => save(draft)}>{saving ? "Saving…" : "Use this setup"}</button>
                <button className={button} disabled={saving} onClick={() => setPreview(false)}>Back</button>
              </div>
            </>
          )}
        </>
      ) : current && preferences ? (
        <>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs text-muted-foreground">{preferences.focus === "setup" ? "Camera setup and maintenance" : preferences.place === "business" ? "Your business workspace" : preferences.place === "home" ? "Your home workspace" : "Your workspace"}</p>
              <h2 className="mt-1 text-lg font-semibold tracking-tight">{current.title}</h2>
            </div>
            <button className={button} onClick={() => { setDraft(preferences.goal === "explore" ? { ...preferences, place: "home", goal: "entrance" } : preferences); setEditing(true); setPreview(false); setError(null); }}>Change preferences</button>
          </div>
          <p className="my-3 text-sm text-muted-foreground">{preferences.goal === "explore" ? current.next : current.description}</p>
          {!camerasLoading && cameraCount === 0 && <p className="mb-3 text-sm">Start by connecting a real camera. You can keep exploring while you set it up.</p>}
          <div className="flex flex-wrap gap-2">
            {(cameraCount === 0 || preferences.focus === "setup") && <button className={primary} onClick={onSetup}>Set up a camera</button>}
            {preferences.focus === "setup" ? <Link href="/settings" className={button}>Check system health</Link> : (
              <Link href={current.href} className={button}>{current.template ? "Review starter rule" : "Review activity"}</Link>
            )}
            {current.template && <Link href="/rules" className={button}>Manage existing rules</Link>}
            <Link href="/timeline" className={button}>Open timeline</Link>
          </div>
          {DETECTION_GOALS.has(preferences.goal) && <ActivationSteps goal={preferences.goal} cameraId={null} />}
          <DailyPriorities
            key={`${preferences.goal}:${preferences.focus}:${preferences.paused ? 1 : 0}:${preferences.place_label ?? ""}`}
            paused={!!preferences.paused}
            pauseBusy={saving}
            onTogglePause={() => save({ ...preferences, paused: !preferences.paused })}
          />
        </>
      ) : null}
    </section>
  );
}
