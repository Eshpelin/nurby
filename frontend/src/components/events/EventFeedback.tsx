"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { extractApiError } from "@/lib/api-error";

// Structured alert feedback (#195). Rating an alert is independent of
// acknowledging it: ack means "seen/handled", this says whether the
// alert was useful or even correct. Two interactions — the rating and,
// for incorrect alerts, one optional reason. Correcting re-runs the
// same PUT; the server keeps one row per reviewer.

type Rating = "useful" | "correct_but_not_useful" | "incorrect";
type Reason = "wrong_object" | "wrong_person" | "duplicate" | "timing";

interface FeedbackRow {
  id: string;
  user_id: string | null;
  reviewer_display_name: string | null;
  rating: Rating;
  reason: Reason | null;
}

const RATINGS: { value: Rating; label: string; title: string }[] = [
  { value: "useful", label: "👍 Useful", title: "This alert was worth getting" },
  { value: "correct_but_not_useful", label: "🤷 Correct, not useful", title: "Accurate, but I don't want alerts like this" },
  { value: "incorrect", label: "👎 Incorrect", title: "Wrong detection or wrong person" },
];

const REASONS: { value: Reason; label: string }[] = [
  { value: "wrong_object", label: "Wrong object" },
  { value: "wrong_person", label: "Wrong person" },
  { value: "duplicate", label: "Duplicate" },
  { value: "timing", label: "Wrong timing" },
];

export function EventFeedbackPanel({ eventId }: { eventId: string }) {
  const { authFetch, user } = useAuth();
  const [rows, setRows] = useState<FeedbackRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await authFetch(`/api/events/${eventId}/feedback`);
      if (res.ok) setRows(await res.json());
    } catch {
      /* silent: feedback is optional, the panel stays quiet */
    }
  }, [authFetch, eventId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const mine = rows.find((r) => user && r.user_id === user.id) || null;

  const put = async (rating: Rating, reason: Reason | null = null) => {
    setSaving(true);
    setError(null);
    try {
      const res = await authFetch(`/api/events/${eventId}/feedback`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reason ? { rating, reason } : { rating }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setError(extractApiError(body, `Could not save (${res.status}).`));
        return;
      }
      await refresh();
    } catch {
      setError("Could not save.");
    } finally {
      setSaving(false);
    }
  };

  const showReasons = mine?.rating === "incorrect" && !mine.reason;

  return (
    <div className="mt-2" data-testid="event-feedback">
      <div className="flex items-center gap-1.5 flex-wrap">
        {RATINGS.map((r) => (
          <button
            key={r.value}
            type="button"
            disabled={saving}
            title={r.title}
            onClick={() => put(r.value)}
            className={`px-2 py-1 text-[11px] rounded-md border transition-colors ${
              mine?.rating === r.value
                ? "border-accent bg-accent/10 text-accent"
                : "border-border text-muted-foreground hover:text-foreground hover:border-muted-foreground/40"
            }`}
          >
            {r.label}
          </button>
        ))}
        {rows.length > 0 && (
          <span className="text-[11px] text-muted-foreground ml-1">
            {rows.length} review{rows.length === 1 ? "" : "s"}
            {mine ? " · yours saved" : ""}
          </span>
        )}
        {mine && (
          <button
            type="button"
            disabled={saving}
            onClick={async () => {
              setSaving(true);
              try {
                const res = await authFetch(`/api/events/${eventId}/feedback`, { method: "DELETE" });
                if (res.ok || res.status === 404) await refresh();
              } finally {
                setSaving(false);
              }
            }}
            className="text-[11px] text-muted-foreground hover:text-danger transition-colors"
          >
            Withdraw
          </button>
        )}
      </div>
      {showReasons && (
        <div className="flex items-center gap-1.5 flex-wrap mt-1.5">
          <span className="text-[11px] text-muted-foreground">What was wrong? (optional)</span>
          {REASONS.map((r) => (
            <button
              key={r.value}
              type="button"
              disabled={saving}
              onClick={() => put("incorrect", r.value)}
              className="px-2 py-0.5 text-[11px] rounded border border-border text-muted-foreground hover:text-foreground hover:border-muted-foreground/40 transition-colors"
            >
              {r.label}
            </button>
          ))}
        </div>
      )}
      {error && <p className="text-[11px] text-danger mt-1">{error}</p>}
    </div>
  );
}
