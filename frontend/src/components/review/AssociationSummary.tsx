"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";

type Association = {
  id: string;
  subject_kind: string;
  subject_key: string;
  object_kind: string;
  object_key: string;
  object_label: string | null;
  relation: string;
  status: string;
  user_confirmed: boolean;
  evidence_count: number;
  supporting_evidence_count?: number;
  contradictory_evidence_count?: number;
  confidence_score?: number | null;
  decision_explanation?: string | null;
  distinct_days: number;
  counterpart_label: string;
  evidence_url: string;
};

type EvidenceDetail = {
  evidence: {
    id: string;
    observed_at: string;
    role: string;
    explanation: string | null;
    observation_ids: string[];
    metadata: Record<string, unknown>;
    source_url: string | null;
    source_status: "available" | "source_changed" | "source_expired";
  }[];
};

type AssociationSummaryProps = {
  objectKind?: string;
  objectKey?: string;
  subjectKind?: string;
  subjectKey?: string;
};

export function AssociationSummary({ objectKind, objectKey, subjectKind, subjectKey }: AssociationSummaryProps) {
  const { authFetch } = useAuth();
  const [items, setItems] = useState<Association[] | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, EvidenceDetail>>({});

  const load = useCallback(async () => {
    const params = new URLSearchParams();
    if (objectKind) params.set("object_kind", objectKind);
    if (objectKey) params.set("object_key", objectKey);
    if (subjectKind) params.set("subject_kind", subjectKind);
    if (subjectKey) params.set("subject_key", subjectKey);
    const response = await authFetch(`/api/review/associations?${params.toString()}`);
    if (response.ok) setItems(await response.json());
    else setItems([]);
  }, [authFetch, objectKey, objectKind, subjectKey, subjectKind]);

  useEffect(() => { void load(); }, [load]);

  const toggleEvidence = async (item: Association) => {
    if (expanded === item.id) {
      setExpanded(null);
      return;
    }
    setExpanded(item.id);
    if (details[item.id]) return;
    const response = await authFetch(item.evidence_url);
    if (response.ok) {
      const detail: EvidenceDetail = await response.json();
      setDetails((current) => ({ ...current, [item.id]: detail }));
    }
  };

  const changeDecision = async (item: Association, decision: "revoke" | "restore") => {
    const response = await authFetch(`/api/review/relationship-suggestions/${item.id}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    });
    if (response.ok) void load();
  };

  if (items === null || items.length === 0) return null;

  return (
    <section className="mb-4 rounded-md border border-border bg-card/40 p-3" aria-label="Identity associations">
      <div className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">Observed associations</div>
      <div className="space-y-1.5">
        {items.map((item) => {
          const label = item.counterpart_label;
          const relation = item.relation === "accompanies" ? "often seen with" : item.relation.replaceAll("_", " ");
          return (
            <div key={item.id} className="rounded border border-border/70 px-2.5 py-2">
              <div className="flex items-center gap-2">
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs">
                  {relation} <span className="font-medium">{label}</span>
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {item.distinct_days} independent {item.distinct_days === 1 ? "visit" : "visits"} · {item.evidence_count} evidence episodes
                  {(item.supporting_evidence_count ?? 0) > 0 && ` · ${item.supporting_evidence_count} support`}
                  {(item.contradictory_evidence_count ?? 0) > 0 && ` · ${item.contradictory_evidence_count} conflict`}
                </div>
                {item.decision_explanation && (
                  <div className="mt-1 text-[10px] text-muted-foreground">{item.decision_explanation}</div>
                )}
              </div>
              <span className={`text-[10px] ${item.status === "established" ? "text-emerald-400" : "text-amber-300"}`}>
                {item.user_confirmed ? "confirmed" : item.status === "candidate" ? "suggested" : item.status}
              </span>
              {item.status === "candidate" && (
                <Link href="/events" className="text-[10px] text-accent hover:underline">Review</Link>
              )}
              {item.user_confirmed && item.status === "established" && (
                <button type="button" onClick={() => void changeDecision(item, "revoke")} className="text-[10px] text-muted-foreground hover:text-foreground">
                  Remove
                </button>
              )}
              {item.status === "archived" && (
                <button type="button" onClick={() => void changeDecision(item, "restore")} className="text-[10px] text-accent hover:underline">
                  Restore for review
                </button>
              )}
              <button type="button" onClick={() => void toggleEvidence(item)} className="text-[10px] text-muted-foreground hover:text-foreground">
                {expanded === item.id ? "Hide evidence" : "Evidence"}
              </button>
              </div>
              {expanded === item.id && details[item.id] && (
                <div className="mt-2 space-y-1 border-t border-border/60 pt-2">
                  {details[item.id].evidence.slice(0, 5).map((evidence) => (
                    <div key={evidence.id} className="text-[10px] text-muted-foreground">
                      <span className={evidence.role === "contradictory" ? "text-amber-300" : "text-emerald-300"}>
                        {evidence.role === "contradictory" ? "Conflict" : "Support"}
                      </span>
                      {` · ${new Date(evidence.observed_at).toLocaleString()}`}
                      {evidence.explanation ? ` — ${evidence.explanation}` : ""}
                      {evidence.source_url && (
                        <a href={evidence.source_url} target="_blank" rel="noreferrer" className="ml-2 text-accent hover:underline">
                          {evidence.metadata.transcript_id ? "Open transcript" : evidence.metadata.transcript_id === undefined && evidence.source_url.includes("journeys") ? "Open journey" : "Open source"}
                        </a>
                      )}
                      {evidence.source_status === "source_changed" && <span className="ml-2 italic">Source changed; re-check</span>}
                      {evidence.source_status === "source_expired" && <span className="ml-2 italic">Source no longer retained</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
