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
  camera_name: string | null;
  unread: boolean;
  evidence: Record<string, unknown>;
  provenance: Record<string, unknown>;
};

type RelationshipDetail = {
  evidence_count: number;
  distinct_days: number;
  supporting_evidence_count?: number;
  contradictory_evidence_count?: number;
  confidence_score?: number | null;
  decision_explanation?: string | null;
  review_events?: {
    id: string;
    action: string;
    old_status: string;
    new_status: string;
    note: string | null;
    created_at: string;
  }[];
  evidence: {
    id: string;
    observed_at: string;
    role: string;
    explanation: string | null;
    camera_ids: string[];
    observation_ids: string[];
    metadata: Record<string, unknown>;
    source_status: "available" | "source_changed" | "source_expired";
    source_url: string | null;
  }[];
};

type PersonOption = {
  id: string;
  display_name: string;
  nickname?: string | null;
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
  const { authFetch, token } = useAuth();
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [decisionBusy, setDecisionBusy] = useState<string | null>(null);
  const [expandedEvidence, setExpandedEvidence] = useState<string | null>(null);
  const [relationshipDetails, setRelationshipDetails] = useState<Record<string, RelationshipDetail>>({});
  const [evidenceLoading, setEvidenceLoading] = useState<string | null>(null);
  const [persons, setPersons] = useState<PersonOption[]>([]);
  const [linkedPerson, setLinkedPerson] = useState<Record<string, string>>({});

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

  useEffect(() => {
    void authFetch("/api/persons").then(async (res) => {
      if (res.ok) setPersons(await res.json());
    }).catch(() => undefined);
  }, [authFetch]);

  const markNotificationRead = async (item: ReviewItem) => {
    if (item.kind !== "notification" || !item.unread) return;
    const res = await authFetch(`/api/notifications/${item.source_id}/read`, { method: "PATCH" });
    if (res.ok) setItems((current) => current.map((candidate) => candidate.id === item.id ? { ...candidate, unread: false, status: "resolved" } : candidate));
  };

  const decideRelationship = async (item: ReviewItem, decision: "confirm" | "reject" | "defer") => {
    if (item.source_type !== "association") return;
    setDecisionBusy(item.id);
    try {
      const res = await authFetch(`/api/review/relationship-suggestions/${item.source_id}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          decision,
          ...(decision === "confirm" && linkedPerson[item.id]
            ? { link_person_id: linkedPerson[item.id] }
            : {}),
        }),
      });
      if (!res.ok) throw new Error(`Could not ${decision} relationship (${res.status})`);
      setItems((current) => current.filter((candidate) => candidate.id !== item.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Relationship decision failed");
    } finally {
      setDecisionBusy(null);
    }
  };

  const toggleEvidence = async (item: ReviewItem) => {
    if (item.source_type !== "association") return;
    if (expandedEvidence === item.id) {
      setExpandedEvidence(null);
      return;
    }
    setExpandedEvidence(item.id);
    if (relationshipDetails[item.id]) return;
    setEvidenceLoading(item.id);
    try {
      const res = await authFetch(`/api/review/relationship-suggestions/${item.source_id}`);
      if (!res.ok) throw new Error(`Evidence unavailable (${res.status})`);
      const detail: RelationshipDetail = await res.json();
      setRelationshipDetails((current) => ({ ...current, [item.id]: detail }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Evidence unavailable");
      setExpandedEvidence(null);
    } finally {
      setEvidenceLoading(null);
    }
  };

  return (
    <section className="mb-5 rounded-lg border border-border bg-card/50" aria-labelledby="review-queue-heading">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h2 id="review-queue-heading" className="text-sm font-medium">Review queue</h2>
          <p className="text-xs text-muted-foreground mt-0.5">Incidents, notifications, and system suggestions in one place.</p>
        </div>
        <div className="flex items-center gap-3">
          <a href="/settings#privacy-controls" className="text-xs text-muted-foreground hover:text-foreground">Privacy controls</a>
          <button type="button" onClick={() => void load()} className="text-xs text-muted-foreground hover:text-foreground">Refresh</button>
        </div>
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
                  {item.camera_name && <span className="text-[10px] text-muted-foreground">{item.camera_name}</span>}
                </div>
                <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{item.summary}</p>
                {typeof item.evidence.peak_observation_id === "string" && token && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={`/api/observations/${item.evidence.peak_observation_id}/thumbnail?token=${encodeURIComponent(token)}`}
                    alt="Incident evidence"
                    className="mt-2 h-16 w-24 rounded border border-border object-cover"
                  />
                )}
                <span className="mt-1 block text-[10px] text-muted-foreground">{timeAgo(item.updated_at)}</span>
                {item.source_type === "association" && expandedEvidence === item.id && (
                  <div className="mt-2 rounded border border-border/70 bg-background/50 p-2">
                    {evidenceLoading === item.id ? (
                      <p className="text-[10px] text-muted-foreground">Loading supporting episodes…</p>
                    ) : relationshipDetails[item.id]?.evidence.length || relationshipDetails[item.id]?.review_events?.length ? (
                      <div className="space-y-1.5">
                        <p className="text-[10px] text-muted-foreground">
                          {relationshipDetails[item.id].distinct_days} independent visits · source episodes below
                        </p>
                        {relationshipDetails[item.id].decision_explanation && (
                          <p className="text-[10px] text-muted-foreground">
                            {relationshipDetails[item.id].decision_explanation}
                            {typeof relationshipDetails[item.id].confidence_score === "number"
                              ? ` Balance ${Math.round(Number(relationshipDetails[item.id].confidence_score) * 100)}%`
                              : ""}
                          </p>
                        )}
                        {relationshipDetails[item.id].evidence.slice(0, 5).map((evidence) => (
                          <div key={evidence.id} className="flex items-start gap-2 text-[10px] text-muted-foreground">
                            <span className={evidence.role === "contradictory" ? "text-amber-300" : "text-emerald-300"}>
                              {evidence.role === "contradictory" ? "Conflict" : "Support"}
                            </span>
                            <div className="min-w-0 flex-1">
                              <span className="text-foreground">{new Date(evidence.observed_at).toLocaleString()}</span>
                              {evidence.explanation ? ` — ${evidence.explanation}` : ""}
                              {evidence.observation_ids.slice(0, 2).map((observationId) => (
                                <a
                                  key={observationId}
                                  href={`/api/observations/${observationId}/thumbnail${token ? `?token=${encodeURIComponent(token)}` : ""}`}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="ml-2 text-accent hover:underline"
                                >
                                  Open frame
                                </a>
                              ))}
                              {typeof evidence.source_url === "string" && (
                                <a href={evidence.source_url} target="_blank" rel="noreferrer" className="ml-2 text-accent hover:underline">
                                  {evidence.metadata.transcript_id ? "Open transcript" : "Open journey"}
                                </a>
                              )}
                              {evidence.source_status === "source_changed" && (
                                <span className="ml-2 italic">Transcript edited; re-check this hypothesis</span>
                              )}
                              {evidence.source_status === "source_expired" && (
                                <span className="ml-2 italic">Source no longer retained</span>
                              )}
                            </div>
                          </div>
                        ))}
                        {relationshipDetails[item.id].review_events?.length ? (
                          <div className="border-t border-border/60 pt-1.5 text-[10px] text-muted-foreground">
                            <div className="mb-1 uppercase tracking-wide">Decision history</div>
                            {relationshipDetails[item.id].review_events?.slice(0, 5).map((event) => (
                              <div key={event.id}>
                                {new Date(event.created_at).toLocaleString()} · {event.action} · {event.old_status} → {event.new_status}
                                {event.note ? ` — ${event.note}` : ""}
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <p className="text-[10px] text-muted-foreground">No visible evidence episodes remain.</p>
                    )}
                  </div>
                )}
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
                {item.source_type === "association" && (
                  <>
                    {item.kind === "identity_suggestion" && item.provenance.relation === "possibly_named" && (
                      <select
                        aria-label={`Link ${item.title} to a person`}
                        value={linkedPerson[item.id] || ""}
                        onChange={(event) => setLinkedPerson((current) => ({ ...current, [item.id]: event.target.value }))}
                        className="max-w-36 rounded border border-border bg-background px-1.5 py-1 text-[11px]"
                      >
                        <option value="">Confirm name only</option>
                        {persons.map((person) => (
                          <option key={person.id} value={person.id}>
                            Link to {person.nickname || person.display_name}
                          </option>
                        ))}
                      </select>
                    )}
                    <button
                      type="button"
                      onClick={() => void toggleEvidence(item)}
                      disabled={evidenceLoading === item.id}
                      className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
                    >
                      {expandedEvidence === item.id ? "Hide evidence" : "Evidence"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void decideRelationship(item, "defer")}
                      disabled={decisionBusy === item.id}
                      className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
                    >
                      Not now
                    </button>
                    <button
                      type="button"
                      onClick={() => void decideRelationship(item, "reject")}
                      disabled={decisionBusy === item.id}
                      className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
                    >
                      Not related
                    </button>
                    <button
                      type="button"
                      onClick={() => void decideRelationship(item, "confirm")}
                      disabled={decisionBusy === item.id}
                      className="text-[11px] text-accent hover:underline disabled:opacity-50"
                    >
                      Confirm
                    </button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
