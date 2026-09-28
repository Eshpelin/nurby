"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { formatDateTime, timeAgo } from "@/lib/time";
import { translate } from "@/lib/i18n";

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
    decision_metadata?: {
      link_type?: string | null;
      before?: Record<string, string>;
      after?: Record<string, string>;
    };
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
    transcript_audits?: {
      id: string;
      field: string;
      old_value: string | null;
      new_value: string | null;
      created_at: string;
    }[];
  }[];
};

type PersonOption = {
  id: string;
  display_name: string;
  nickname?: string | null;
};

type ClusterOption = {
  id: string;
  kind: "face" | "body";
  label: string;
  sighting_count?: number;
};

type RecurrenceEvidence = {
  cluster_kind?: "face" | "body";
  cluster_id?: string;
  distinct_days?: number;
  samples?: { id: string; captured_at: string; camera_id: string; thumbnail_path: string | null }[];
};

type VisualCandidate = {
  kind?: string;
  id?: string;
};

type ReviewQueueProps = {
  onOpenEvent?: (eventId: string) => void;
  focusId?: string | null;
};

type ReviewFilter = "all" | "incident" | "alert" | "camera_health" | "notification" | "suggestions";

const KIND_LABEL_KEY: Record<ReviewItem["kind"], string> = {
  incident: "review.incidents",
  alert: "review.alerts",
  notification: "review.notifications",
  camera_health: "review.camera_health",
  identity_suggestion: "review.suggestions",
  relationship_suggestion: "review.suggestions",
  privacy_review: "review.privacy_controls",
};

export function ReviewQueue({ onOpenEvent, focusId }: ReviewQueueProps) {
  const { authFetch, token, user } = useAuth();
  const t = useCallback((key: string) => translate(user?.locale, key), [user?.locale]);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [decisionBusy, setDecisionBusy] = useState<string | null>(null);
  const [expandedEvidence, setExpandedEvidence] = useState<string | null>(null);
  const [relationshipDetails, setRelationshipDetails] = useState<Record<string, RelationshipDetail>>({});
  const [evidenceLoading, setEvidenceLoading] = useState<string | null>(null);
  const [persons, setPersons] = useState<PersonOption[]>([]);
  const [clusters, setClusters] = useState<ClusterOption[]>([]);
  const [linkedPerson, setLinkedPerson] = useState<Record<string, string>>({});
  const [linkedCluster, setLinkedCluster] = useState<Record<string, string>>({});
  const [linkedSubject, setLinkedSubject] = useState<Record<string, string>>({});
  const [linkedObject, setLinkedObject] = useState<Record<string, string>>({});
  const [showArchived, setShowArchived] = useState(false);
  const [filter, setFilter] = useState<ReviewFilter>("all");
  const [unreadOnly, setUnreadOnly] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "25" });
      if (showArchived) params.set("include_archived", "true");
      if (unreadOnly) params.set("unread_only", "true");
      if (filter === "suggestions") {
        params.set("kind", "identity_suggestion,relationship_suggestion");
      } else if (filter !== "all") {
        params.set("kind", filter);
      }
      const res = await authFetch(`/api/review?${params.toString()}`);
      if (!res.ok) throw new Error(`Review queue failed (${res.status})`);
      const body: { items: ReviewItem[] } = await res.json();
      const visible = body.items;
      if (focusId) {
        const focused = visible.find((item) => item.id === focusId || item.source_id === focusId);
        setItems(focused ? [focused, ...visible.filter((item) => item.id !== focused.id)] : visible);
      } else {
        setItems(visible);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("review.unavailable"));
    } finally {
      setLoading(false);
    }
  }, [authFetch, filter, focusId, showArchived, unreadOnly, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void authFetch("/api/persons").then(async (res) => {
      if (res.ok) setPersons(await res.json());
    }).catch(() => undefined);
    void Promise.all([
      authFetch("/api/persons/suggestions?min_sightings=1"),
      authFetch("/api/body-clusters/suggestions?min_sightings=1"),
    ]).then(async ([faceRes, bodyRes]) => {
      const face = faceRes.ok ? await faceRes.json() : [];
      const body = bodyRes.ok ? await bodyRes.json() : [];
      setClusters([
        ...(Array.isArray(face) ? face.map((cluster: { id: string; auto_label?: string; sighting_count?: number }) => ({
          id: cluster.id,
          kind: "face" as const,
          label: cluster.auto_label || "Unknown face",
          sighting_count: cluster.sighting_count,
        })) : []),
        ...(Array.isArray(body) ? body.map((cluster: { id: string; auto_label?: string; sighting_count?: number }) => ({
          id: cluster.id,
          kind: "body" as const,
          label: cluster.auto_label || "Unknown body",
          sighting_count: cluster.sighting_count,
        })) : []),
      ]);
    }).catch(() => undefined);
  }, [authFetch]);

  const markNotificationRead = async (item: ReviewItem) => {
    if (item.kind !== "notification" || !item.unread) return;
    const res = await authFetch(`/api/notifications/${item.source_id}/read`, { method: "PATCH" });
    if (res.ok) setItems((current) => current.map((candidate) => candidate.id === item.id ? { ...candidate, unread: false, status: "resolved" } : candidate));
  };

  const decideRelationship = async (item: ReviewItem, decision: "confirm" | "reject" | "defer" | "ambiguous" | "restore") => {
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
            ...(decision === "confirm" && linkedCluster[item.id]
              ? {
                  link_cluster_id: linkedCluster[item.id].split(":")[1],
                  link_cluster_kind: linkedCluster[item.id].split(":")[0],
                }
              : {}),
            ...(decision === "confirm" && linkedSubject[item.id]
              ? { link_subject_person_id: linkedSubject[item.id] }
              : {}),
            ...(decision === "confirm" && linkedObject[item.id]
              ? { link_object_person_id: linkedObject[item.id] }
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
      setError(err instanceof Error ? err.message : t("review.unavailable"));
      setExpandedEvidence(null);
    } finally {
      setEvidenceLoading(null);
    }
  };

  return (
    <section className="mb-5 rounded-lg border border-border bg-card/50" aria-labelledby="review-queue-heading">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <h2 id="review-queue-heading" className="text-sm font-medium">{t("review.queue")}</h2>
          <p className="text-xs text-muted-foreground mt-0.5">{t("review.queue_help")}</p>
        </div>
        <div className="flex items-center gap-3">
          <a href="/settings#privacy-controls" className="text-xs text-muted-foreground hover:text-foreground">{t("review.privacy_controls")}</a>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="sr-only">{t("review.type")}</span>
            <select
              aria-label={t("review.type")}
              value={filter}
              onChange={(event) => setFilter(event.target.value as ReviewFilter)}
              className="rounded border border-border bg-background px-1.5 py-1 text-xs"
            >
              <option value="all">{t("review.all")}</option>
              <option value="incident">{t("review.incidents")}</option>
              <option value="alert">{t("review.alerts")}</option>
              <option value="camera_health">{t("review.camera_health")}</option>
              <option value="notification">{t("review.notifications")}</option>
              <option value="suggestions">{t("review.suggestions")}</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={unreadOnly}
              onChange={(event) => setUnreadOnly(event.target.checked)}
              className="accent-accent"
            />
            {t("review.unread")}
          </label>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(event) => setShowArchived(event.target.checked)}
              className="accent-accent"
            />
            {t("review.show_archived")}
          </label>
          <button type="button" onClick={() => void load()} className="text-xs text-muted-foreground hover:text-foreground">{t("review.refresh")}</button>
        </div>
      </div>
      {loading ? (
        <p className="px-4 py-5 text-xs text-muted-foreground">{t("review.loading")}</p>
      ) : error ? (
        <p className="px-4 py-5 text-xs text-red-400">{error}</p>
      ) : items.length === 0 ? (
        <p className="px-4 py-5 text-xs text-muted-foreground">{t("review.empty")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <li key={item.id} className={`flex items-start gap-3 px-4 py-3 ${item.unread ? "bg-accent/5" : ""}`}>
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${item.priority === "high" ? "bg-red-400" : "bg-accent"}`} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{item.title}</span>
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{t(KIND_LABEL_KEY[item.kind])}</span>
                  {item.camera_name && <span className="text-[10px] text-muted-foreground">{item.camera_name}</span>}
                </div>
                <p className="mt-1 text-xs text-muted-foreground line-clamp-2">{item.summary}</p>
                {item.kind === "identity_suggestion" && (() => {
                  const candidate = item.evidence.visual_candidate as VisualCandidate | undefined;
                  if (!candidate?.kind) return null;
                  const label = candidate.kind === "person"
                    ? "recognized person"
                    : candidate.kind === "face_cluster"
                      ? "unknown face cluster"
                      : candidate.kind === "body_cluster"
                        ? "unknown body cluster"
                        : "visual subject";
                  return (
                    <p className="mt-1 text-[10px] text-muted-foreground">
                      Visual candidate: <span className="text-foreground">{label}</span>
                    </p>
                  );
                })()}
                {typeof item.evidence.peak_observation_id === "string" && token && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={`/api/observations/${item.evidence.peak_observation_id}/thumbnail?token=${encodeURIComponent(token)}`}
                    alt="Incident evidence"
                    className="mt-2 h-16 w-24 rounded border border-border object-cover"
                  />
                )}
                {Boolean(item.evidence.recurrence) && Boolean(token) && (() => {
                  const recurrence = item.evidence.recurrence as RecurrenceEvidence | undefined;
                  if (!recurrence?.samples?.length || !recurrence.cluster_id || !recurrence.cluster_kind) return null;
                  const prefix = recurrence.cluster_kind === "face" ? "/api/persons" : "/api/body-clusters";
                  return (
                    <div className="mt-2 flex items-center gap-1.5" aria-label="Recurring sample evidence">
                      <span className="mr-1 text-[10px] text-muted-foreground">{t("review.linked_appearances")}</span>
                      {recurrence.samples.map((sample) => (
                        <a
                          key={sample.id}
                          href={`${prefix}/suggestions/${recurrence.cluster_id}/samples/${sample.id}/thumbnail?token=${encodeURIComponent(token || "")}`}
                          target="_blank"
                          rel="noreferrer"
                          title={new Date(sample.captured_at).toLocaleString()}
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={`${prefix}/suggestions/${recurrence.cluster_id}/samples/${sample.id}/thumbnail?token=${encodeURIComponent(token || "")}`} alt="Recurring sample" className="h-10 w-10 rounded border border-border object-cover" />
                        </a>
                      ))}
                    </div>
                  );
                })()}
                <span className="mt-1 block text-[10px] text-muted-foreground">{timeAgo(item.updated_at)}</span>
                {item.source_type === "association" && expandedEvidence === item.id && (
                  <div className="mt-2 rounded border border-border/70 bg-background/50 p-2">
                    {evidenceLoading === item.id ? (
                      <p className="text-[10px] text-muted-foreground">{t("review.loading_evidence")}</p>
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
                        {Boolean(item.evidence.evidence_policy && typeof item.evidence.evidence_policy === "object") && (
                          <p className="text-[10px] text-muted-foreground">
                            Decision guidance: {String((item.evidence.evidence_policy as { confidence_band?: string }).confidence_band ?? "review").replaceAll("_", " ")}
                            {String((item.evidence.evidence_policy as { decision_recommendation?: string }).decision_recommendation ?? "").replaceAll("_", " ")
                              ? ` · ${String((item.evidence.evidence_policy as { decision_recommendation?: string }).decision_recommendation).replaceAll("_", " ")}`
                              : ""}
                          </p>
                        )}
                        {relationshipDetails[item.id].evidence.slice(0, 5).map((evidence) => (
                          <div key={evidence.id} className="flex items-start gap-2 text-[10px] text-muted-foreground">
                            <span className={evidence.role === "contradictory" ? "text-amber-300" : "text-emerald-300"}>
                              {evidence.role === "contradictory" ? "Conflict" : "Support"}
                            </span>
                            <div className="min-w-0 flex-1">
                              <span className="text-foreground">{formatDateTime(evidence.observed_at)}</span>
                              {evidence.explanation ? ` — ${evidence.explanation}` : ""}
                              {Array.isArray(evidence.metadata.plate_reads) && evidence.metadata.plate_reads.length > 0 && (
                                <span className="ml-2 text-foreground/80">
                                  Plate reads: {(evidence.metadata.plate_reads as { text?: string; confidence?: number | null }[])
                                    .map((read) => `${read.text || "unknown"}${typeof read.confidence === "number" ? ` (${Math.round(read.confidence * 100)}%)` : ""}`)
                                    .join(", ")}
                                </span>
                              )}
                              {typeof evidence.metadata.identity_kind === "string" && (
                                <span className="ml-2 text-foreground/80">Source: {evidence.metadata.identity_kind}</span>
                              )}
                              {typeof evidence.metadata.visit_timing === "object" && evidence.metadata.visit_timing !== null &&
                                typeof (evidence.metadata.visit_timing as { relation_hint?: unknown }).relation_hint === "string" && (
                                  <span className="ml-2 text-foreground/80">
                                    Timing: {(evidence.metadata.visit_timing as { relation_hint: string }).relation_hint.replaceAll("_", " ")}
                                  </span>
                                )}
                              {token && evidence.observation_ids.length > 0 && (
                                <div className="mt-1 flex gap-1.5" aria-label="Evidence thumbnails">
                                  {evidence.observation_ids.slice(0, 3).map((observationId) => {
                                    const thumbnail = `/api/observations/${observationId}/thumbnail?token=${encodeURIComponent(token)}`;
                                    return (
                                      <a key={observationId} href={thumbnail} target="_blank" rel="noreferrer" title="Open evidence frame">
                                        {/* eslint-disable-next-line @next/next/no-img-element */}
                                        <img src={thumbnail} alt="Evidence frame" className="h-12 w-16 rounded border border-border object-cover" />
                                      </a>
                                    );
                                  })}
                                </div>
                              )}
                              {evidence.observation_ids.slice(0, 2).map((observationId) => (
                                <a
                                  key={observationId}
                                  href={`/api/observations/${observationId}/thumbnail${token ? `?token=${encodeURIComponent(token)}` : ""}`}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="ml-2 text-accent hover:underline"
                                >
                                  {t("review.open_frame")}
                                </a>
                              ))}
                              {typeof evidence.source_url === "string" && (
                                <a href={evidence.source_url} target="_blank" rel="noreferrer" className="ml-2 text-accent hover:underline">
                                  {evidence.metadata.transcript_id ? t("review.open_transcript") : t("review.open_journey")}
                                </a>
                              )}
                              {evidence.source_status === "source_changed" && (
                                <span className="ml-2 italic">{t("review.source_changed")}</span>
                              )}
                              {evidence.transcript_audits?.length ? (
                                <div className="mt-1 text-[10px] text-amber-200">
                                  {evidence.transcript_audits.map((audit) => (
                                    <div key={audit.id}>
                                      Correction logged: {audit.field === "transcript_speaker" ? "speaker attribution" : "transcript text"} · {formatDateTime(audit.created_at)}
                                    </div>
                                  ))}
                                </div>
                              ) : null}
                              {evidence.source_status === "source_expired" && (
                                <span className="ml-2 italic">{t("review.source_expired")}</span>
                              )}
                            </div>
                          </div>
                        ))}
                        {relationshipDetails[item.id].review_events?.length ? (
                          <div className="border-t border-border/60 pt-1.5 text-[10px] text-muted-foreground">
                            <div className="mb-1 uppercase tracking-wide">{t("review.decision_history")}</div>
                            {relationshipDetails[item.id].review_events?.slice(0, 5).map((event) => (
                              <div key={event.id}>
                                {formatDateTime(event.created_at)} · {event.action} · {event.old_status} → {event.new_status}
                                {event.note ? ` — ${event.note}` : ""}
                                {event.decision_metadata?.link_type
                                  ? ` · ${event.decision_metadata.link_type.replaceAll("_", " ")} reconciliation recorded`
                                  : ""}
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <p className="text-[10px] text-muted-foreground">{t("review.no_evidence")}</p>
                    )}
                  </div>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {item.source_type === "event" && onOpenEvent && (
                  <button type="button" onClick={() => onOpenEvent(item.source_id)} className="text-[11px] text-accent hover:underline">{t("review.open")}</button>
                )}
                {item.kind === "notification" && item.unread && (
                  <button type="button" onClick={() => void markNotificationRead(item)} className="text-[11px] text-muted-foreground hover:text-foreground">{t("review.mark_read")}</button>
                )}
                {item.kind === "identity_suggestion" && (
                  <a href="/people" className="text-[11px] text-accent hover:underline">{t("review.people")}</a>
                )}
                {item.source_type === "association" && (
                  <>
                    {item.kind === "identity_suggestion" && item.provenance.relation === "possibly_named" && (
                      <>
                        <select
                          aria-label={`Link ${item.title} to a person`}
                          value={linkedPerson[item.id] || ""}
                          onChange={(event) => {
                            setLinkedPerson((current) => ({ ...current, [item.id]: event.target.value }));
                            setLinkedCluster((current) => ({ ...current, [item.id]: "" }));
                          }}
                          className="max-w-36 rounded border border-border bg-background px-1.5 py-1 text-[11px]"
                        >
                          <option value="">Confirm name for this visual</option>
                          {persons.map((person) => (
                            <option key={person.id} value={person.id}>
                              Link to {person.nickname || person.display_name}
                            </option>
                          ))}
                        </select>
                        <select
                          aria-label={`Link ${item.title} to an unknown visual cluster`}
                          value={linkedCluster[item.id] || ""}
                          onChange={(event) => {
                            setLinkedCluster((current) => ({ ...current, [item.id]: event.target.value }));
                            setLinkedPerson((current) => ({ ...current, [item.id]: "" }));
                          }}
                          className="max-w-44 rounded border border-border bg-background px-1.5 py-1 text-[11px]"
                        >
                          <option value="">Keep current visual</option>
                          {clusters.map((cluster) => (
                            <option key={`${cluster.kind}:${cluster.id}`} value={`${cluster.kind}:${cluster.id}`}>
                              Link to {cluster.label} ({cluster.kind})
                            </option>
                          ))}
                        </select>
                      </>
                    )}
                    {item.kind === "relationship_suggestion" && ["co_present_with", "arrives_with", "accompanies"].includes(String(item.provenance.relation)) && (
                      <>
                        <select
                          aria-label={`Link subject of ${item.title} to a person`}
                          value={linkedSubject[item.id] || ""}
                          onChange={(event) => setLinkedSubject((current) => ({ ...current, [item.id]: event.target.value }))}
                          className="max-w-36 rounded border border-border bg-background px-1.5 py-1 text-[11px]"
                        >
                          <option value="">Subject stays anonymous</option>
                          {persons.map((person) => (
                            <option key={person.id} value={person.id}>
                              Subject: {person.nickname || person.display_name}
                            </option>
                          ))}
                        </select>
                        <select
                          aria-label={`Link companion of ${item.title} to a person`}
                          value={linkedObject[item.id] || ""}
                          onChange={(event) => setLinkedObject((current) => ({ ...current, [item.id]: event.target.value }))}
                          className="max-w-36 rounded border border-border bg-background px-1.5 py-1 text-[11px]"
                        >
                          <option value="">Companion stays anonymous</option>
                          {persons.map((person) => (
                            <option key={person.id} value={person.id}>
                              Companion: {person.nickname || person.display_name}
                            </option>
                          ))}
                        </select>
                      </>
                    )}
                    <button
                      type="button"
                      onClick={() => void toggleEvidence(item)}
                      disabled={evidenceLoading === item.id}
                      className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
                    >
                      {expandedEvidence === item.id ? t("review.hide_evidence") : t("review.evidence")}
                    </button>
                    {item.status === "archived" && (
                      <button
                        type="button"
                        onClick={() => void decideRelationship(item, "restore")}
                        disabled={decisionBusy === item.id}
                        className="text-[11px] text-accent hover:underline disabled:opacity-50"
                      >
                        {t("review.restore")}
                      </button>
                    )}
                    {item.status !== "archived" && <button
                      type="button"
                      onClick={() => void decideRelationship(item, "defer")}
                      disabled={decisionBusy === item.id}
                      className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
                    >
                      {t("review.not_now")}
                    </button>}
                    {item.status !== "archived" && <>
                    <button
                      type="button"
                      onClick={() => void decideRelationship(item, "ambiguous")}
                      disabled={decisionBusy === item.id}
                      className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
                    >
                      {t("review.insufficient")}
                    </button>
                    <button
                      type="button"
                      onClick={() => void decideRelationship(item, "reject")}
                      disabled={decisionBusy === item.id}
                      className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
                    >
                      {t("review.not_related")}
                    </button>
                    <button
                      type="button"
                      onClick={() => void decideRelationship(item, "confirm")}
                      disabled={decisionBusy === item.id}
                      className="text-[11px] text-accent hover:underline disabled:opacity-50"
                    >
                      {t("review.confirm")}
                    </button>
                    </>}
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
