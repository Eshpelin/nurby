"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { GOALS, goalsForPlace, type Experience, type ExperiencePreferences, type Goal, type Place } from "@/lib/onboarding";
import { DETECTION_GOALS, milestoneForGoal, type ActivationList, type ActivationView } from "@/lib/activation";
import { DailyPriorities } from "@/components/DailyPriorities";
import { Coachmark } from "@/components/Coachmark";

interface Props {
  cameraCount: number;
  camerasLoading: boolean;
  onSetupCamera: () => void;
  onClose: () => void;
  onChanged: () => void;
}

type StepKey = "goal" | "rule" | "test" | "confirm" | "done";

const DETECTION_STEPS: { key: StepKey; label: string }[] = [
  { key: "goal", label: "Goal" },
  { key: "rule", label: "Rule" },
  { key: "test", label: "Test" },
  { key: "confirm", label: "Confirm" },
];

const btn = "rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted/50 disabled:opacity-50";
const primary = "rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50";

const DEFAULT_DRAFT: ExperiencePreferences = { version: 1, place: "home", goal: "entrance", focus: "daily" };

export function SetupWizard({ cameraCount, camerasLoading, onSetupCamera, onClose, onChanged }: Props) {
  const { authFetch } = useAuth();
  const [experience, setExperience] = useState<Experience | null>(null);
  const [activation, setActivation] = useState<ActivationList | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<StepKey>("goal");
  const [draft, setDraft] = useState<ExperiencePreferences>(DEFAULT_DRAFT);
  // Once the person navigates the wizard themselves, stop auto-repositioning
  // them from server state so a background poll never yanks the step.
  const touched = useRef(false);
  // Coach-marks anchor to controls the wizard actually renders. Dismissals are
  // remembered per key so a hint never nags after it's been closed.
  const cameraBtnRef = useRef<HTMLButtonElement>(null);
  const draftLinkRef = useRef<HTMLAnchorElement>(null);
  const [dismissedMarks, setDismissedMarks] = useState<Set<string>>(() => new Set());
  const dismissMark = useCallback((k: string) => setDismissedMarks((s) => new Set(s).add(k)), []);

  const load = useCallback(async () => {
    try {
      const [expRes, actRes] = await Promise.all([
        authFetch("/api/auth/me/experience"),
        authFetch("/api/auth/me/activation"),
      ]);
      const exp: Experience | null = expRes.ok ? await expRes.json() : null;
      const acts: ActivationList | null = actRes.ok ? await actRes.json() : null;
      setExperience(exp);
      setActivation(acts);
      if (exp?.preferences) setDraft(exp.preferences);
      return { exp, acts };
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  // Position the wizard at the first unfinished step on open (resume).
  const positionFrom = useCallback((exp: Experience | null, acts: ActivationList | null) => {
    if (touched.current) return;
    const prefs = exp?.preferences ?? null;
    if (!prefs) return setStep("goal");
    if (!DETECTION_GOALS.has(prefs.goal)) return setStep("done");
    const m = milestoneForGoal(acts, prefs.goal);
    const done = (k: string) => m?.steps.find((s) => s.key === k)?.done ?? false;
    if (m?.verified) return setStep("done");
    if (!done("configured")) return setStep("rule");
    if (!done("tested")) return setStep("test");
    return setStep("confirm");
  }, []);

  useEffect(() => {
    void (async () => {
      const { exp, acts } = await load();
      positionFrom(exp, acts);
    })();
  }, [load, positionFrom]);

  const prefs = experience?.preferences ?? null;
  const view: ActivationView | null = useMemo(
    () => (prefs ? milestoneForGoal(activation, prefs.goal) : null),
    [activation, prefs],
  );
  const isDetection = prefs ? DETECTION_GOALS.has(prefs.goal) : DETECTION_GOALS.has(draft.goal);
  const stepDone = (k: string) => view?.steps.find((s) => s.key === k)?.done ?? false;

  // Poll while waiting for a real alert, so "Test" advances on its own.
  useEffect(() => {
    if (step !== "test" || stepDone("tested")) return;
    const id = setInterval(() => { void load(); }, 4000);
    return () => clearInterval(id);
  }, [step, load, view]); // eslint-disable-line react-hooks/exhaustive-deps

  const call = useCallback(async (path: string, body: unknown, fail: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch(path, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (!res.ok) {
        let detail = fail;
        try { detail = (await res.json())?.detail || fail; } catch { /* keep default */ }
        throw new Error(detail);
      }
      await load();
      onChanged();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : fail);
      return false;
    } finally {
      setBusy(false);
    }
  }, [authFetch, load, onChanged]);

  const putExperience = useCallback(async (next: ExperiencePreferences, fail: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch("/api/auth/me/experience", {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next),
      });
      if (!res.ok) throw new Error(fail);
      await load();
      onChanged();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : fail);
      return false;
    } finally {
      setBusy(false);
    }
  }, [authFetch, load, onChanged]);

  const saveGoal = useCallback(async (next: ExperiencePreferences, go: StepKey) => {
    if (await putExperience(next, "Could not save your goal. Try again.")) {
      touched.current = true;
      setStep(go);
    }
  }, [putExperience]);

  const goto = (k: StepKey) => { touched.current = true; setStep(k); };
  // Skipping is pure navigation: it never calls an activation endpoint, so a
  // skipped step is never marked configured/tested/confirmed. The pill and
  // stepper keep reading true server state. The current step's skip target,
  // or `null` to close the wizard outright.
  const skipTarget: Record<StepKey, StepKey | null> = {
    goal: null, rule: "test", test: "confirm", confirm: null, done: null,
  };
  const skip = () => { const to = skipTarget[step]; if (to) goto(to); else onClose(); };
  const changePlace = (place: Place) => setDraft((d) => ({
    ...d, place, goal: goalsForPlace(place).includes(d.goal) ? d.goal : goalsForPlace(place)[0],
  }));

  // ── progress header ────────────────────────────────────────────────
  const activeIndex = step === "done" ? DETECTION_STEPS.length : DETECTION_STEPS.findIndex((s) => s.key === step);
  const showStepper = isDetection && step !== "done";

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/50" onClick={onClose} aria-hidden />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Set up Nurby"
        className="flex h-full w-full max-w-md flex-col border-l border-border bg-card shadow-2xl motion-safe:animate-[wizardIn_.18s_ease-out]"
      >
        <style>{`@keyframes wizardIn{from{transform:translateX(16px);opacity:.6}to{transform:none;opacity:1}}`}</style>

        <header className="border-b border-border px-5 py-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold tracking-tight">Set up Nurby</h2>
            <button onClick={onClose} aria-label="Close" className="text-muted-foreground hover:text-foreground text-xl leading-none">×</button>
          </div>
          {showStepper && (
            <div className="mt-3">
              <div className="flex gap-1.5" aria-hidden>
                {DETECTION_STEPS.map((s, i) => (
                  <span key={s.key} className={`h-1 flex-1 rounded-full ${i < activeIndex ? "bg-accent" : i === activeIndex ? "bg-accent/60" : "bg-muted"}`} />
                ))}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Step {activeIndex + 1} of {DETECTION_STEPS.length} · {DETECTION_STEPS[activeIndex]?.label}
              </p>
            </div>
          )}
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          {loading ? (
            <p role="status" className="text-sm text-muted-foreground">Loading your setup…</p>
          ) : (
            <>
              {error && <p role="alert" className="mb-4 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
              {step === "goal" && renderGoal()}
              {step === "rule" && renderRule()}
              {step === "test" && renderTest()}
              {step === "confirm" && renderConfirm()}
              {step === "done" && renderDone()}
              {step !== "done" && (
                <div className="mt-6 border-t border-border/60 pt-3">
                  <button
                    type="button"
                    onClick={skip}
                    disabled={busy}
                    className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50"
                  >
                    {skipTarget[step] ? "Skip this step for now" : "Do this later"}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );

  // ── steps ──────────────────────────────────────────────────────────

  function renderGoal() {
    const selected = GOALS[draft.goal];
    return (
      <div>
        <h3 className="text-lg font-semibold tracking-tight">What should Nurby watch for first?</h3>
        <p className="mt-1 text-sm text-muted-foreground">Pick one goal. You can add more later. Choosing a goal changes nothing on its own.</p>

        <fieldset disabled={busy} className="mt-5">
          <legend className="mb-2 text-sm font-medium">Where are you using Nurby?</legend>
          <div className="grid grid-cols-2 gap-2">
            {(["home", "business"] as const).map((place) => (
              <button key={place} aria-pressed={draft.place === place}
                className={`${btn} ${draft.place === place ? "border-accent bg-accent/10" : ""}`}
                onClick={() => changePlace(place)}>
                {place === "home" ? "Home" : "Small business"}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset disabled={busy} className="mt-5">
          <legend className="mb-2 text-sm font-medium">Goal</legend>
          <div className="space-y-2">
            {goalsForPlace(draft.place ?? "home").map((goal: Goal) => (
              <button key={goal} aria-pressed={draft.goal === goal}
                className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors ${draft.goal === goal ? "border-accent bg-accent/10" : "border-border hover:bg-muted/40"}`}
                onClick={() => setDraft((d) => ({ ...d, goal }))}>
                <span className="block text-sm font-medium">{GOALS[goal].title}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">{GOALS[goal].description}</span>
              </button>
            ))}
          </div>
        </fieldset>

        <label className="mt-5 block text-sm font-medium" htmlFor="wiz-place-label">Name this place (optional)</label>
        <input id="wiz-place-label" type="text" maxLength={80} disabled={busy}
          placeholder={draft.place === "business" ? "e.g. Front shop" : "e.g. Home"}
          className="mt-2 w-full rounded-lg border border-border bg-background p-2 text-sm"
          value={draft.place_label ?? ""} onChange={(e) => setDraft((d) => ({ ...d, place_label: e.target.value || null }))} />

        <div className="mt-6 flex items-center gap-2">
          <button className={primary} disabled={busy}
            onClick={() => saveGoal({ ...draft, place: DETECTION_GOALS.has(draft.goal) ? draft.place : null }, DETECTION_GOALS.has(draft.goal) ? "rule" : "done")}>
            {busy ? "Saving…" : "Continue"}
          </button>
          <button className={btn} disabled={busy}
            onClick={() => saveGoal({ version: 1, place: null, goal: "explore", focus: "daily" }, "done")}>
            Just explore
          </button>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">{selected.needs}</p>
      </div>
    );
  }

  function renderRule() {
    const configured = stepDone("configured");
    const draftId = view?.draft_rule_id ?? null;
    const goal = prefs?.goal;
    return (
      <div>
        <h3 className="text-lg font-semibold tracking-tight">Set up the rule</h3>
        {configured ? (
          <>
            <p className="mt-1 text-sm text-muted-foreground">Your rule is enabled and pointed at a camera. Next, prove it works with a real event.</p>
            <p className="mt-4 flex items-center gap-2 text-sm"><span className="text-accent">✓</span> Rule configured</p>
            <StepNav onBack={() => goto("goal")} primaryLabel="Next: test it" onPrimary={() => goto("test")} />
          </>
        ) : !draftId ? (
          <>
            <p className="mt-1 text-sm text-muted-foreground">Nurby will create a starter rule for this goal, switched off. Nothing is armed until you review and enable it.</p>
            {!camerasLoading && cameraCount === 0 && (
              <div className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                Connect a real camera first. <button ref={cameraBtnRef} className="font-medium text-accent hover:underline" onClick={onSetupCamera}>Set up a camera</button>
                {!dismissedMarks.has("camera") && (
                  <Coachmark targetRef={cameraBtnRef} onDismiss={() => dismissMark("camera")}>
                    Start here. Connect a camera, then come back to this step to build the rule.
                  </Coachmark>
                )}
              </div>
            )}
            <div className="mt-5 flex items-center gap-2">
              <button className={primary} disabled={busy} onClick={() => call("/api/auth/me/activation/draft-rule", { goal }, "Could not create the draft rule.")}>
                {busy ? "Creating…" : "Create the draft rule"}
              </button>
              <button className={btn} disabled={busy} onClick={() => goto("goal")}>Back</button>
            </div>
          </>
        ) : (
          <>
            <p className="mt-1 text-sm text-muted-foreground">Open the draft, choose the camera and how you want to be alerted, then switch it on. Come back and mark it configured.</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Link ref={draftLinkRef} href={`/rules/${draftId}/edit`} className={btn}>Open the draft rule</Link>
            </div>
            {!dismissedMarks.has("draft") && (
              <Coachmark targetRef={draftLinkRef} onDismiss={() => dismissMark("draft")}>
                This opens the draft rule&apos;s editor. Pick the camera and how you&apos;re alerted, switch it on, then return here.
              </Coachmark>
            )}
            <div className="mt-5 flex items-center gap-2">
              <button className={primary} disabled={busy}
                onClick={() => call("/api/auth/me/activation/configure", { goal, rule_id: draftId }, "The rule is not enabled, has no camera, or has no way to alert you yet.")}>
                {busy ? "Checking…" : "I've enabled it"}
              </button>
              <button className={btn} disabled={busy} onClick={() => goto("goal")}>Back</button>
            </div>
          </>
        )}
      </div>
    );
  }

  function renderTest() {
    const tested = stepDone("tested");
    const synthetic = view?.steps.find((s) => s.key === "tested")?.synthetic;
    return (
      <div>
        <h3 className="text-lg font-semibold tracking-tight">Trigger a real event</h3>
        <p className="mt-1 text-sm text-muted-foreground">Walk in front of the camera. The alert should reach you within a few seconds. A saved rule alone doesn&apos;t prove this works.</p>
        <div className="mt-5 rounded-lg border border-border bg-muted/20 p-4 text-sm">
          {tested ? (
            <span className="flex items-center gap-2"><span className="text-accent">✓</span> Alert received{synthetic && <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-xs text-amber-600">demo camera</span>}</span>
          ) : (
            <span className="flex items-center gap-2 text-muted-foreground">
              <span className="h-3 w-3 animate-pulse rounded-full bg-accent/60" /> Waiting for the alert…
            </span>
          )}
        </div>
        {tested && synthetic && <p className="mt-3 text-xs text-amber-600">That was the demo camera, so it counts as a practice run. Trigger a real camera to verify.</p>}
        <StepNav onBack={() => goto("rule")} primaryLabel="Next: confirm the clip" onPrimary={() => goto("confirm")} primaryDisabled={!tested} extra={
          <button className={btn} disabled={busy} onClick={() => load()}>Check again</button>
        } />
      </div>
    );
  }

  function renderConfirm() {
    return (
      <div>
        <h3 className="text-lg font-semibold tracking-tight">Confirm the clip</h3>
        <p className="mt-1 text-sm text-muted-foreground">Open the alert&apos;s clip and check it shows what you needed to see. Then confirm it below.</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link href="/timeline" className={btn}>Open the alert clip</Link>
        </div>
        <div className="mt-5 flex items-center gap-2">
          <button className={primary} disabled={busy || !view?.event_id}
            onClick={async () => {
              if (!view?.event_id) return;
              // Confirm names the exact event that was tested, so a later
              // event can't silently satisfy an old confirmation.
              const ok = await call("/api/auth/me/activation/confirm", { goal: prefs?.goal, event_id: view.event_id }, "The test event changed. Review its evidence again.");
              if (ok) goto("done");
            }}>
            {busy ? "Confirming…" : "I opened the clip, it was useful"}
          </button>
          <button className={btn} disabled={busy} onClick={() => goto("test")}>Back</button>
        </div>
      </div>
    );
  }

  function renderDone() {
    const verified = view?.verified;
    const mins = view?.seconds_to_first_useful != null ? Math.max(1, Math.round(view.seconds_to_first_useful / 60)) : null;
    return (
      <div>
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/15 text-accent">✓</span>
          <h3 className="text-lg font-semibold tracking-tight">{verified ? "You're verified" : "You're all set"}</h3>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          {verified
            ? `Nurby delivered a real alert and you confirmed the clip${mins ? ` in ${mins} min` : ""}. Monitoring is working.`
            : prefs && DETECTION_GOALS.has(prefs.goal)
            ? "Your goal is saved. Finish the steps whenever you're ready to reach a verified alert."
            : "Your workspace is set. Open the timeline to review activity any time."}
        </p>

        {prefs && (
          <div className="mt-5">
            <DailyPriorities
              key={`${prefs.goal}:${prefs.focus}:${prefs.paused ? 1 : 0}:${prefs.place_label ?? ""}`}
              paused={!!prefs.paused}
              pauseBusy={busy}
              onTogglePause={() => { void putExperience({ ...prefs, paused: !prefs.paused }, "Could not update your workflow."); }}
            />
          </div>
        )}

        <div className="mt-6 flex items-center gap-2">
          <button className={primary} onClick={onClose}>Done</button>
          <button className={btn} onClick={() => { setDraft(prefs ?? DEFAULT_DRAFT); goto("goal"); }}>Change goal</button>
        </div>
      </div>
    );
  }
}

function StepNav({ onBack, onPrimary, primaryLabel, primaryDisabled, extra }: {
  onBack: () => void; onPrimary: () => void; primaryLabel: string; primaryDisabled?: boolean; extra?: React.ReactNode;
}) {
  return (
    <div className="mt-6 flex items-center gap-2">
      <button className={primary} disabled={primaryDisabled} onClick={onPrimary}>{primaryLabel}</button>
      {extra}
      <button className={btn} onClick={onBack}>Back</button>
    </div>
  );
}
