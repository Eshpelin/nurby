"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import {
  STEP_LABELS,
  milestoneForGoal,
  type ActivationList,
  type ActivationView,
} from "@/lib/activation";

interface Props {
  goal: string;
  cameraId: string | null;
}

const button = "rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted/50 disabled:opacity-50";
const primary = `${button} bg-accent text-white hover:opacity-90`;

// The verified-activation checklist for one detection goal. It never
// claims success on its own: only a real, delivered, confirmed event flips
// `verified`, and everything else is shown as still-to-do.
export function ActivationSteps({ goal, cameraId }: Props) {
  const { authFetch, token } = useAuth();
  const [view, setView] = useState<ActivationView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [evidence, setEvidence] = useState<{ event_id: string; recording_id: string; seek_seconds: number } | null>(null);
  const [played, setPlayed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setEvidence(null);
    setPlayed(false);
    try {
      const res = await authFetch("/api/auth/me/activation");
      if (!res.ok) throw new Error("load");
      const data: ActivationList = await res.json();
      setView(milestoneForGoal(data, goal));
    } catch {
      setError("Could not load activation progress.");
    } finally {
      setLoading(false);
    }
  }, [authFetch, goal]);

  useEffect(() => {
    void load();
  }, [load]);

  const post = useCallback(async (path: string, body: unknown, failMsg: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch(path, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (!res.ok) {
        let detail = failMsg;
        try { detail = (await res.json())?.detail || failMsg; } catch { /* keep default */ }
        throw new Error(detail);
      }
      setView(await res.json());
      setEvidence(null);
      setPlayed(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : failMsg);
    } finally {
      setBusy(false);
    }
  }, [authFetch]);

  async function reviewEvidence() {
    setBusy(true);
    setError(null);
    setEvidence(null);
    setPlayed(false);
    try {
      const res = await authFetch(`/api/auth/me/activation/evidence?goal=${encodeURIComponent(goal)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not load test evidence.");
      setEvidence(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load test evidence.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p role="status" className="mt-4 text-sm text-muted-foreground">Loading activation progress…</p>;

  const steps = view?.steps ?? [
    { key: "configured" as const, done: false, synthetic: false },
    { key: "tested" as const, done: false, synthetic: false },
    { key: "confirmed" as const, done: false, synthetic: false },
  ];

  return (
    <section aria-label="Verified activation" className="mt-4 rounded-lg border border-border bg-muted/20 p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Reach a real, verified result</h3>
        {view?.verified ? (
          <span className="rounded-full bg-green-600/15 px-2 py-0.5 text-xs font-medium text-green-600">Verified</span>
        ) : null}
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-red-500">{error}</p>}

      <ol className="mt-3 space-y-2">
        {steps.map((s) => {
          const label = STEP_LABELS[s.key];
          return (
            <li key={s.key} className="flex gap-2 text-sm">
              <span aria-hidden className={s.done ? "text-green-600" : "text-muted-foreground"}>{s.done ? "✓" : "○"}</span>
              <div>
                <span className="font-medium">{label.title}</span>
                {s.synthetic && <span className="ml-2 rounded bg-amber-500/15 px-1.5 py-0.5 text-xs text-amber-600">Synthetic test</span>}
                <p className="text-xs text-muted-foreground">{label.detail}</p>
              </div>
            </li>
          );
        })}
      </ol>

      <div className="mt-3 flex flex-wrap gap-2">
        <button className={button} disabled={busy} onClick={() => void load()}>Refresh test progress</button>
        {!view?.draft_rule_id && (
          <button
            className={button}
            disabled={busy}
            onClick={() => post("/api/auth/me/activation/draft-rule", { goal, camera_id: cameraId }, "Could not create a draft rule.")}
          >
            {busy ? "Working…" : "Create draft rule (disabled)"}
          </button>
        )}
        {view?.draft_rule_id && (
          <Link href={`/rules/${view.draft_rule_id}/edit`} className={button}>Review and enable the draft</Link>
        )}
        {view?.rule_id && !view.steps[0].done && (
          <button
            className={button}
            disabled={busy}
            onClick={() => post("/api/auth/me/activation/configure", { goal, rule_id: view.rule_id }, "The rule is not fully configured yet.")}
          >
            Mark configured
          </button>
        )}
        {view?.steps[1].done && !view.steps[2].done && (
          <>
            <button className={button} disabled={busy} onClick={() => void reviewEvidence()}>Review this test clip</button>
            <button
              className={primary}
              disabled={busy || !played || !evidence}
              onClick={() => post("/api/auth/me/activation/confirm", { goal, event_id: evidence?.event_id }, "Confirm needs a delivered test event first.")}
            >
              I received this alert and this clip was useful
            </button>
          </>
        )}
        {view?.steps[0].done && (
          <button className={button} disabled={busy} onClick={() => post("/api/auth/me/activation/retest", { goal }, "Could not start a new test.")}>Start a new test</button>
        )}
      </div>

      {evidence && token && (
        <div className="mt-3">
          <video
            aria-label="Recording for this test event"
            controls
            className="w-full rounded-lg"
            src={`/api/recordings/${evidence.recording_id}/stream?token=${encodeURIComponent(token)}`}
            onLoadedMetadata={(e) => { e.currentTarget.currentTime = evidence.seek_seconds; }}
            onPlaying={() => setPlayed(true)}
            onError={() => { setPlayed(false); setError("This clip could not be played. Check recording availability before confirming."); }}
          />
          <p className="mt-2 text-xs text-muted-foreground">Play this test clip before confirming. Confirmation records your own assessment that you received the alert and found its evidence useful.</p>
        </div>
      )}

      {view?.verified ? (
        <p className="mt-3 text-xs text-green-600">
          Verified with a real delivered alert you confirmed
          {view.seconds_to_first_useful != null ? ` in ${Math.round(view.seconds_to_first_useful / 60)} min.` : "."}
        </p>
      ) : (
        <p className="mt-3 text-xs text-muted-foreground">
          A saved goal or a scaffolded rule is not activation. Trigger the camera, receive the alert, and open the clip to verify.
        </p>
      )}
    </section>
  );
}
