"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/time";

type ReviewItem = {
  id: string;
  kind: "incident" | "alert" | "notification" | "identity_suggestion" | "relationship_suggestion" | "camera_health" | "privacy_review";
  status: string;
  priority: string;
  title: string;
  summary: string;
  created_at: string;
  updated_at: string;
  source_type: string;
  source_id: string;
  camera_id: string | null;
  unread: boolean;
  evidence: Record<string, unknown>;
  provenance: Record<string, unknown>;
};

type ReviewQueueProps = {
  onOpenEvent?: (eventId: string) => void;
};

const KIND_LABEL: Record<ReviewItem["kind"], string> = {
  incident: "Incident",
  alert: "Alert",
  notification: "Notification",
  camera_health: "Camera health",
  identity_suggestion: "Identity suggestion",
  relationship_suggestion: "Relationship suggestion",
  privacy_review: "Privacy review",
};

export function ReviewQueue({ onOpenEvent }: ReviewQueueProps) {
  const { authFetch } = useAuth();
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authFetch("/api/review?limit=25");
      if (!res.ok) throw new Error(`Review queue failed (${res.status})`);
      const body: { items: ReviewItem[] } = await res.json();
      // Alerts remain in the detailed history below. The queue currently
      // foregrounds the other reviewable sources so the same alert is not
      // rendered twice while the adapter is being rolled out.
      setItems(body.items.filter((item) => item.kind !== "alert"));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review queue unavailable");
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    void load();
  }, [load]);

  const markNotificationRead = async (item: ReviewItem) => {
    if (item.kind !== "notification" || !item.unread) return;
    const res = await authFetch(`/api/notifications/${item.source_id}/read`, { method: "PATCH" });
    if (res.ok) setItems((current) => current.map((candidate) => candidate.id === item.id ? { ...candidate, unread: false, status: "resolved" } : candidate));
  };

  return (
    <section className="mb-5 rounded-lg border border-border bg-card/50" aria-labelledby="review-queue-heading">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h2 id="review-queue-heading" className="text-sm font-medium">Review queue</h2>
          <p className="text-xs text-muted-foreground mt-0.5">Incidents, notifications, and system suggestions in one place.</p>
        </div>
        <button type="button" onClick={() => void load()} className="text-xs text-muted-foreground hover:text-foreground">Refresh</button>
      </div>
      {loading ? (
        <p className="px-4 py-5 text-xs text-muted-foreground">Loading review items…</p>
      ) : error ? (
        <p className="px-4 py-5 text-xs text-red-400">{error}</p>
      ) : items.length === 0 ? (
        <p className="px-4 py-5 text-xs text-muted-foreground">Nothing else needs review right now.</p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <li key={item.id} className={`flex items-start gap-3 px-4 py-3 ${item.unread ? "bg-accent/5" : ""}`}>
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${item.priority === "high" ? "bg-red-400" : "bg-accent"}`} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{item.title}</span>
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{KIND_LABEL[item.kind]}</span>
                  {item.camera_id && <span className="text-[10px] text-muted-foreground">Camera {item.camera_id.slice(0, 8)}</span>}
                </div>
                <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{item.summary}</p>
                <span className="mt-1 block text-[10px] text-muted-foreground">{timeAgo(item.updated_at)}</span>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {item.source_type === "event" && onOpenEvent && (
                  <button type="button" onClick={() => onOpenEvent(item.source_id)} className="text-[11px] text-accent hover:underline">Open</button>
                )}
                {item.kind === "notification" && item.unread && (
                  <button type="button" onClick={() => void markNotificationRead(item)} className="text-[11px] text-muted-foreground hover:text-foreground">Mark read</button>
                )}
                {item.kind === "identity_suggestion" && (
                  <a href="/people" className="text-[11px] text-accent hover:underline">Review in People</a>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
