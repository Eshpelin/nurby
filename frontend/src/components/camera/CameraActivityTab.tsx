"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { ConversationCard } from "@/components/ConversationCard";
import { SummaryCard } from "@/components/SummaryCard";

interface ActivityConversation {
  id: string;
  camera_id: string;
  started_at: string;
  ended_at_provisional: string;
  ended_at: string | null;
  finalized: boolean;
  transcript_count: number;
  summary_text: string | null;
  cleaned_text: string | null;
  summary_provider_name: string | null;
  has_clip?: boolean;
}

interface ActivitySummary {
  id: string;
  camera_id: string;
  kind: string;
  started_at: string;
  ended_at: string;
  provider_name: string | null;
  trigger_reason: string;
  summary_text: string;
  people_seen: { name: string; sightings: number; first_seen?: string; last_seen?: string }[] | null;
  plates_seen: string[] | null;
  object_counts: Record<string, number> | null;
}

/**
 * Per-camera activity feed. Pulls /api/conversations and /api/summaries
 * scoped to this camera and renders them interleaved by recency. Uses
 * the same cards as the dashboard so a user can navigate from a tile
 * straight to the focused per-camera view without learning a new
 * layout.
 */
export function CameraActivityTab({
  cameraId,
  cameraName,
}: {
  cameraId: string;
  cameraName: string;
}) {
  const { authFetch } = useAuth();
  const [convs, setConvs] = useState<ActivityConversation[]>([]);
  const [summaries, setSummaries] = useState<ActivitySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "conversations" | "summaries">("all");

  const refresh = useCallback(async () => {
    try {
      const [cR, sR] = await Promise.all([
        authFetch(`/api/conversations?camera_id=${cameraId}&limit=50`),
        authFetch(`/api/summaries?camera_id=${cameraId}&limit=50`),
      ]);
      if (cR.ok) setConvs(await cR.json());
      if (sR.ok) setSummaries(await sR.json());
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [authFetch, cameraId]);

  useEffect(() => {
    refresh();
    const i = setInterval(refresh, 15000);
    return () => clearInterval(i);
  }, [refresh]);

  type Entry =
    | { kind: "conversation"; ts: number; data: ActivityConversation }
    | { kind: "summary"; ts: number; data: ActivitySummary };

  const entries: Entry[] = [];
  if (filter === "all" || filter === "conversations") {
    for (const c of convs) {
      entries.push({
        kind: "conversation",
        ts: new Date(c.ended_at_provisional).getTime(),
        data: c,
      });
    }
  }
  if (filter === "all" || filter === "summaries") {
    for (const s of summaries) {
      entries.push({
        kind: "summary",
        ts: new Date(s.ended_at).getTime(),
        data: s,
      });
    }
  }
  entries.sort((a, b) => b.ts - a.ts);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        {([
          { v: "all", l: `All (${convs.length + summaries.length})` },
          { v: "conversations", l: `Conversations (${convs.length})` },
          { v: "summaries", l: `Summaries (${summaries.length})` },
        ] as const).map((f) => (
          <button
            key={f.v}
            type="button"
            onClick={() => setFilter(f.v)}
            className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
              filter === f.v
                ? "border-accent bg-accent/10 text-accent-foreground"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            {f.l}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-muted-foreground/70 font-mono">
          refreshes every 15s
        </span>
      </div>

      {loading ? (
        <div className="text-xs text-muted-foreground">Loading activity.</div>
      ) : entries.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-card/30 p-8 text-center">
          <h3 className="text-sm font-medium mb-1">Nothing yet</h3>
          <p className="text-xs text-muted-foreground max-w-sm mx-auto">
            Activity rolls up here as conversations close and the
            summarizer worker runs. Check the dashboard timeline for the
            latest live signal.
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {entries.map((e) => {
            if (e.kind === "conversation") {
              const c = e.data;
              return (
                <ConversationCard
                  key={`c-${c.id}`}
                  id={c.id}
                  cameraId={c.camera_id}
                  cameraName={cameraName}
                  startedAt={c.started_at}
                  endedAtProvisional={c.ended_at_provisional}
                  endedAt={c.ended_at}
                  finalized={c.finalized}
                  transcriptCount={c.transcript_count}
                  summaryText={c.summary_text}
                  cleanedText={c.cleaned_text}
                  summaryProviderName={c.summary_provider_name}
                  hasClip={c.has_clip}
                />
              );
            }
            const s = e.data;
            return (
              <SummaryCard
                key={`s-${s.id}`}
                id={s.id}
                cameraId={s.camera_id}
                cameraName={cameraName}
                kind={s.kind}
                startedAt={s.started_at}
                endedAt={s.ended_at}
                providerName={s.provider_name}
                triggerReason={s.trigger_reason}
                summaryText={s.summary_text}
                peopleSeen={s.people_seen}
                platesSeen={s.plates_seen}
                objectCounts={s.object_counts}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
