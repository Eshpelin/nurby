"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useWSSubscribe } from "@/lib/ws";
import { ReinterpretButton } from "@/components/ReinterpretButton";
import { MomentModal } from "@/components/MomentModal";
import { formatDateTime, formatWith } from "@/lib/time";

interface IncidentObs {
  id: string;
  started_at: string;
  vlm_description: string | null;
  thumbnail_path: string | null;
  refined_by_provider_name?: string | null;
  primary_vlm_description?: string | null;
}

interface Incident {
  id: string;
  camera_id: string;
  signature_kind: string;
  signature_key: string;
  started_at: string;
  last_seen_at: string;
  ended_at: string | null;
  finalized: boolean;
  occurrence_count: number;
  peak_observation_id: string | null;
  observation_ids: string[] | null;
  thumbnails: { obs_id: string; path: string | null; ts: string }[] | null;
  summary_text: string | null;
  summary_provider_name: string | null;
  status?: string;
}

interface OwnershipEvent {
  action: string;
  actor: string | null;
  reason: string | null;
  detail: string | null;
  at: string | null;
}

interface Ownership {
  status: string;
  resolved_by: string | null;
  resolved_at: string | null;
  resolution_reason: string | null;
  assigned_to: string | null;
  history: OwnershipEvent[];
}

interface IncidentAlert {
  event_id: string;
  fired_at: string | null;
  severity: string | null;
  trigger_reason: string | null;
  action_type: string | null;
  action_status: string | null;
  action_error: string | null;
  seen: boolean;
  seen_at: string | null;
  notes: { text: string; source: string; at: string | null }[];
}

interface RelatedSighting {
  id: string;
  camera_id: string;
  started_at: string;
  last_seen_at: string;
  summary_text: string | null;
  status: string;
}

interface ExactClip {
  recording_id: string;
  started_at: string;
  ended_at: string | null;
  anchor_at: string;
  thumbnail_path: string | null;
}

interface IncidentDetail {
  status?: string;
  observations?: IncidentObs[];
  ownership?: Ownership;
  alerts?: IncidentAlert[];
  related_sightings?: RelatedSighting[];
  exact_clip?: ExactClip | null;
  evidence_export?: { path: string; params: Record<string, string> };
}

interface Props {
  incident: Incident;
  cameraName?: string;
}

const STATUS_TONE: Record<string, string> = {
  open: "text-amber-300 bg-amber-500/10 border-amber-500/30",
  resolved: "text-emerald-300 bg-emerald-500/10 border-emerald-500/30",
  dismissed: "text-slate-400 bg-slate-500/10 border-slate-500/30",
};

const RepeatIcon = ({ className }: { className?: string }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <polyline points="17 1 21 5 17 9" />
    <path d="M3 11V9a4 4 0 0 1 4-4h14" />
    <polyline points="7 23 3 19 7 15" />
    <path d="M21 13v2a4 4 0 0 1-4 4H3" />
  </svg>
);

const ChevronDown = ({ className }: { className?: string }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <polyline points="6 9 12 15 18 9" />
  </svg>
);

const Sparkle = ({ className }: { className?: string }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
    <circle cx="12" cy="12" r="2" />
  </svg>
);

/**
 * Persistent incident card. Renders /api/incidents rows. Subscribes
 * to incident_updated and incident_finalized so the count and
 * summary appear in real time. Click to expand and lazy-load the
 * full observation list with descriptions.
 */
export function IncidentCard({ incident, cameraName }: Props) {
  const { token, authFetch, user } = useAuth();
  const [expanded, setExpanded] = useState(false);
  const [moment, setMoment] = useState<{ obsId: string; ts: string } | null>(null);
  const [obs, setObs] = useState<IncidentObs[] | null>(null);
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [status, setStatus] = useState<string>(incident.status ?? "open");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [live, setLive] = useState({
    occurrence_count: incident.occurrence_count,
    last_seen_at: incident.last_seen_at,
    finalized: incident.finalized,
    summary_text: incident.summary_text,
    summary_provider_name: incident.summary_provider_name,
  });

  useEffect(() => {
    setLive({
      occurrence_count: incident.occurrence_count,
      last_seen_at: incident.last_seen_at,
      finalized: incident.finalized,
      summary_text: incident.summary_text,
      summary_provider_name: incident.summary_provider_name,
    });
  }, [
    incident.occurrence_count,
    incident.last_seen_at,
    incident.finalized,
    incident.summary_text,
    incident.summary_provider_name,
  ]);

  useWSSubscribe(
    ["incident_updated", "incident_finalized"],
    (msg) => {
      if (msg.incident_id !== incident.id) return;
      if (msg.type === "incident_updated") {
        setLive((s) => ({
          ...s,
          occurrence_count: Number(msg.occurrence_count) || s.occurrence_count,
          last_seen_at: String(msg.last_seen_at) || s.last_seen_at,
        }));
      }
      if (msg.type === "incident_finalized") {
        setLive((s) => ({
          ...s,
          finalized: true,
          summary_text:
            (typeof msg.summary_text === "string" ? msg.summary_text : null) ||
            s.summary_text,
        }));
      }
    },
    incident.camera_id
  );

  const span = Math.max(
    0,
    Math.round(
      (new Date(live.last_seen_at).getTime() -
        new Date(incident.started_at).getTime()) /
        1000
    )
  );
  const spanLabel =
    span < 60
      ? `${span}s`
      : span < 3600
        ? `${Math.round(span / 60)}m`
        : `${(span / 3600).toFixed(1)}h`;

  const headline = formatSignature(incident.signature_kind, incident.signature_key);

  const tone = live.finalized
    ? "border-emerald-700/40 bg-emerald-950/15 hover:border-emerald-600/60"
    : "border-violet-700/40 bg-violet-950/15 hover:border-violet-600/60";
  const accent = live.finalized ? "text-emerald-300" : "text-violet-300";
  const accentDot = live.finalized ? "text-emerald-400" : "text-violet-400";

  function applyDetail(data: IncidentDetail) {
    setDetail(data);
    setObs(data.observations || []);
    if (data.status) setStatus(data.status);
    else if (data.ownership?.status) setStatus(data.ownership.status);
  }

  async function loadDetail(force = false) {
    if ((detail !== null && !force) || loading) return;
    setLoading(true);
    try {
      const res = await authFetch(`/api/incidents/${incident.id}`);
      if (res.ok) applyDetail(await res.json());
    } finally {
      setLoading(false);
    }
  }

  async function act(action: string, body?: Record<string, unknown>) {
    if (busy) return;
    setBusy(true);
    try {
      const res = await authFetch(`/api/incidents/${incident.id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
      });
      if (res.ok) {
        // The action endpoints return the row + ownership; re-fetch the full
        // detail so alerts / related / clip stay consistent in one view.
        await loadDetail(true);
        setReason("");
      }
    } finally {
      setBusy(false);
    }
  }

  function toggle() {
    setExpanded((v) => {
      const next = !v;
      if (next) loadDetail();
      return next;
    });
  }

  const peakThumbObs = incident.peak_observation_id;
  const thumbId = peakThumbObs ?? (incident.thumbnails?.[0]?.obs_id ?? null);

  return (
    <div className={`rounded-lg border ${tone} overflow-hidden transition-colors`}>
      {/* div with button semantics: a real <button> here would nest the
          ReinterpretButton and thumbnail chips inside it, which is invalid
          HTML and breaks hydration. */}
      <div
        role="button"
        tabIndex={0}
        onClick={toggle}
        onKeyDown={(e) => {
          // Only react to keys on the header itself, not on nested
          // interactive children (their keydowns bubble up here).
          if (e.target !== e.currentTarget) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggle();
          }
        }}
        className="w-full text-left px-3 py-2.5 cursor-pointer"
      >
        <div className="flex items-center gap-2 text-[11px] mb-1.5">
          <RepeatIcon className={`w-3.5 h-3.5 ${accentDot}`} />
          <span className={`font-medium uppercase tracking-wider ${accent}`}>
            {live.finalized ? "Incident closed" : "Incident · live"}
          </span>
          {!live.finalized && (
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-violet-400 opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-violet-400" />
            </span>
          )}
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground">{cameraName || "Camera"}</span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground font-mono">
            {live.occurrence_count}× over {spanLabel}
          </span>
          {status && status !== "open" && (
            <span
              className={`px-1.5 py-0.5 rounded border text-[10px] font-medium capitalize ${
                STATUS_TONE[status] ?? STATUS_TONE.open
              }`}
            >
              {status}
            </span>
          )}
          <ChevronDown
            className={`ml-auto w-3.5 h-3.5 text-muted-foreground transition-transform ${
              expanded ? "rotate-180" : ""
            }`}
          />
        </div>
        <div className="flex gap-3">
          {thumbId && (
            <div className="w-20 h-14 flex-shrink-0 bg-black/50 rounded overflow-hidden">
              <img
                src={`/api/observations/${thumbId}/thumbnail${
                  token ? `?token=${token}` : ""
                }`}
                alt=""
                className="w-full h-full object-cover"
              />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium leading-snug">
              {headline}
              <span className="ml-1 text-xs font-normal text-muted-foreground">
                seen {live.occurrence_count}×
              </span>
            </p>
            {live.finalized && live.summary_text ? (
              <p className="mt-1 text-xs text-foreground leading-relaxed">
                <Sparkle className="inline-block w-3 h-3 mr-1 text-emerald-400" />
                {live.summary_text}
              </p>
            ) : null}
            <div className="mt-1 flex items-center gap-1 flex-wrap">
              {(incident.thumbnails || []).slice(-8).map((t) => (
                <span
                  key={t.obs_id}
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    // Don't toggle the card. open the moment modal instead.
                    e.stopPropagation();
                    setMoment({ obsId: t.obs_id, ts: t.ts });
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.stopPropagation();
                      e.preventDefault();
                      setMoment({ obsId: t.obs_id, ts: t.ts });
                    }
                  }}
                  className={`text-[10px] font-mono ${accent}/80 px-1 py-0.5 rounded bg-violet-500/10 hover:bg-violet-500/25 hover:underline transition-colors cursor-pointer`}
                  title={`View this moment. ${formatDateTime(t.ts)}`}
                >
                  {formatWith(new Date(t.ts), {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              ))}
            </div>
            {live.finalized && live.summary_provider_name && (
              <p className="mt-1 text-[10px] text-muted-foreground/70">
                summary by {live.summary_provider_name}
              </p>
            )}
            {live.finalized && (
              <div className="mt-2">
                <ReinterpretButton
                  endpoint={`/api/incidents/${incident.id}/reinterpret`}
                  label="Reinterpret"
                  variant="compact"
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-border/40 bg-black/20 px-3 py-2.5 space-y-2">
          {/* Workflow: status + resolve/dismiss/reopen + assignment + who-did-what (#197) */}
          <div className="rounded border border-border/50 bg-card/40 p-2.5 space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Status
              </span>
              <span
                className={`px-1.5 py-0.5 rounded border text-[10px] font-medium capitalize ${
                  STATUS_TONE[status] ?? STATUS_TONE.open
                }`}
              >
                {status}
              </span>
              <div className="ml-auto flex items-center gap-1.5">
                {status === "open" ? (
                  <>
                    <button
                      disabled={busy}
                      onClick={() => act("resolve", { reason })}
                      className="text-[11px] px-2 py-0.5 rounded border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/15 disabled:opacity-50"
                    >
                      Resolve
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => act("dismiss", { reason })}
                      className="text-[11px] px-2 py-0.5 rounded border border-slate-500/40 text-slate-300 hover:bg-slate-500/15 disabled:opacity-50"
                    >
                      Dismiss
                    </button>
                  </>
                ) : (
                  <button
                    disabled={busy}
                    onClick={() => act("reopen")}
                    className="text-[11px] px-2 py-0.5 rounded border border-amber-500/40 text-amber-300 hover:bg-amber-500/15 disabled:opacity-50"
                  >
                    Reopen
                  </button>
                )}
              </div>
            </div>
            {status === "open" && (
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Reason (optional)"
                className="w-full text-[11px] bg-black/30 border border-border/50 rounded px-2 py-1 outline-none focus:border-border"
              />
            )}
            <div className="flex items-center gap-2 text-[11px]">
              <span className="text-muted-foreground">Assigned</span>
              <span className="text-foreground/90">
                {detail?.ownership?.assigned_to ?? "nobody"}
              </span>
              <div className="ml-auto flex gap-1.5">
                {user && !detail?.ownership?.assigned_to && (
                  <button
                    disabled={busy}
                    onClick={() => act("assign", { user_id: user.id })}
                    className="text-[11px] px-2 py-0.5 rounded border border-sky-500/40 text-sky-300 hover:bg-sky-500/15 disabled:opacity-50"
                  >
                    Assign to me
                  </button>
                )}
                {detail?.ownership?.assigned_to && (
                  <button
                    disabled={busy}
                    onClick={() => act("assign", { user_id: null })}
                    className="text-[11px] px-2 py-0.5 rounded border border-slate-500/40 text-slate-300 hover:bg-slate-500/15 disabled:opacity-50"
                  >
                    Unassign
                  </button>
                )}
              </div>
            </div>
            {detail?.ownership?.history && detail.ownership.history.length > 0 && (
              <div className="space-y-0.5 pt-1 border-t border-border/40">
                {detail.ownership.history.map((h, i) => (
                  <div key={i} className="text-[10px] text-muted-foreground">
                    <span className="capitalize text-foreground/80">{h.action}</span>
                    {h.actor ? ` by ${h.actor}` : ""}
                    {h.detail ? ` → ${h.detail}` : ""}
                    {h.reason ? ` — "${h.reason}"` : ""}
                    {h.at ? ` · ${formatDateTime(h.at)}` : ""}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Alerts this incident fired: trigger reason + action result + seen (#197) */}
          {detail?.alerts && detail.alerts.length > 0 && (
            <div className="rounded border border-border/50 bg-card/40 p-2.5 space-y-1.5">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Alerts
              </p>
              {detail.alerts.map((a) => (
                <div key={a.event_id} className="text-[11px] flex items-center gap-2 flex-wrap">
                  <span className="text-foreground/90">{a.trigger_reason ?? "rule"}</span>
                  <span className="text-muted-foreground">·</span>
                  <span
                    className={
                      a.action_status === "failed"
                        ? "text-rose-300"
                        : a.action_status === "sent"
                          ? "text-emerald-300"
                          : "text-amber-300"
                    }
                  >
                    {a.action_type ?? "action"}: {a.action_status ?? "—"}
                  </span>
                  {a.action_error && (
                    <span className="text-rose-300/80" title={a.action_error}>
                      (failed)
                    </span>
                  )}
                  <span className="ml-auto text-[10px] text-muted-foreground">
                    {a.seen ? "seen" : "unseen"}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Exact clip + scoped evidence export (#197) */}
          <div className="flex items-center gap-2 flex-wrap text-[11px]">
            {incident.peak_observation_id && (
              <button
                onClick={() =>
                  setMoment({
                    obsId: incident.peak_observation_id!,
                    ts: incident.started_at,
                  })
                }
                className="px-2 py-0.5 rounded border border-violet-500/40 text-violet-300 hover:bg-violet-500/15"
              >
                Open exact clip
              </button>
            )}
            {detail?.evidence_export && (
              <a
                href={`${detail.evidence_export.path}?${new URLSearchParams({
                  ...detail.evidence_export.params,
                  ...(token ? { token } : {}),
                }).toString()}`}
                className="px-2 py-0.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-border"
              >
                Download evidence
              </a>
            )}
          </div>

          {/* Related sightings across cameras (#197) */}
          {detail?.related_sightings && detail.related_sightings.length > 0 && (
            <div className="rounded border border-border/50 bg-card/40 p-2.5 space-y-1">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                Related sightings
              </p>
              {detail.related_sightings.map((r) => (
                <div key={r.id} className="text-[11px] text-muted-foreground">
                  <span className="font-mono">{formatDateTime(r.started_at)}</span>
                  {r.summary_text ? ` — ${r.summary_text}` : ""}
                </div>
              ))}
            </div>
          )}

          {loading && obs === null ? (
            <p className="text-xs text-muted-foreground">Loading occurrences.</p>
          ) : obs && obs.length > 0 ? (
            obs.map((o) => (
              <div
                key={o.id}
                className="rounded border border-border/50 bg-card/40 p-2 text-xs"
              >
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground mb-1">
                  <span className="font-mono">
                    {formatWith(new Date(o.started_at), { hour: "numeric", minute: "2-digit", second: "2-digit" })}
                  </span>
                  {o.refined_by_provider_name && (
                    <span className="text-sky-300">✨ refined</span>
                  )}
                </div>
                {o.vlm_description ? (
                  <p className="leading-relaxed">{o.vlm_description}</p>
                ) : (
                  <p className="text-muted-foreground italic">
                    (no description)
                  </p>
                )}
              </div>
            ))
          ) : (
            <p className="text-xs text-muted-foreground">No occurrences recorded.</p>
          )}
        </div>
      )}

      {moment && (
        <MomentModal
          observationId={moment.obsId}
          cameraId={incident.camera_id}
          cameraName={cameraName}
          ts={moment.ts}
          onClose={() => setMoment(null)}
        />
      )}
    </div>
  );
}

function formatSignature(kind: string, key: string): string {
  if (kind === "person") return key;
  if (kind === "cluster") {
    const short = key.split(",")[0]?.slice(0, 8) ?? "stranger";
    return `Recurring stranger ${short}`;
  }
  // Matched by body appearance, no face this time. Say so plainly rather
  // than claiming a recognition we did not make.
  if (kind === "body") return "Unrecognized person (matched by appearance)";
  if (kind === "unknown") return "Unknown person";
  if (kind === "object") {
    const labels = key.split(",");
    if (labels.length === 1) return capitalize(labels[0]);
    if (labels.length === 2) return `${capitalize(labels[0])} + ${labels[1]}`;
    return `${capitalize(labels[0])} + ${labels.length - 1} more`;
  }
  return "Motion";
}

function capitalize(s: string): string {
  return s.length === 0 ? s : s[0].toUpperCase() + s.slice(1);
}
