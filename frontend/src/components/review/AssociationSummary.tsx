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
  distinct_days: number;
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

  if (items === null || items.length === 0) return null;

  return (
    <section className="mb-4 rounded-md border border-border bg-card/40 p-3" aria-label="Identity associations">
      <div className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">Observed associations</div>
      <div className="space-y-1.5">
        {items.map((item) => {
          const isVehicleView = Boolean(objectKey);
          const label = isVehicleView ? item.subject_key : (item.object_label || item.object_key);
          const relation = isVehicleView ? "often seen with" : item.relation.replaceAll("_", " ");
          return (
            <div key={item.id} className="flex items-center gap-2 rounded border border-border/70 px-2.5 py-2">
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs">
                  {relation} <span className="font-medium">{label}</span>
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {item.distinct_days} independent {item.distinct_days === 1 ? "visit" : "visits"} · {item.evidence_count} evidence episodes
                </div>
              </div>
              <span className={`text-[10px] ${item.status === "established" ? "text-emerald-400" : "text-amber-300"}`}>
                {item.user_confirmed ? "confirmed" : item.status === "candidate" ? "suggested" : item.status}
              </span>
              {item.status === "candidate" && (
                <Link href="/events" className="text-[10px] text-accent hover:underline">Review</Link>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
