"use client";

/**
 * Memory — household knowledge (#185). Everything Nurby knows about the
 * household in one place: notes you wrote, notes attached to a person,
 * vehicle or camera, and proposals Nurby learned from observation that
 * wait for your accept/reject. A note with a schedule can mute matching
 * alerts during that window, but only after you switch that on — and you
 * can switch it off again just as easily.
 */

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useToast, useConfirm } from "@/lib/feedback";
import { EmptyState } from "@/components/EmptyState";
import { timeAgo } from "@/lib/time";
import { extractApiError } from "@/lib/api-error";

interface Fact {
  id: string;
  text: string;
  kind: string;
  source: string; // user | agent
  status: string; // established | candidate | archived | rejected
  enabled: boolean;
  pinned: boolean;
  evidence_count: number;
  entity_kind: string | null; // household | person | vehicle | camera
  entity_key: string | null;
  entity_label: string | null;
  schedule: {
    days: number[];
    start_minute: number;
    end_minute: number;
    tz: string | null;
    summary: string;
  } | null;
  suppresses_alerts: boolean;
  suppression_armed: boolean;
  suppression_hit_count: number;
  last_suppressed_at: string | null;
  created_via: string | null;
  established_at: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  created_at: string | null;
  updated_at: string | null;
  last_confirmed_at: string | null;
}

interface Evidence {
  kind: string;
  id: string;
  missing?: boolean;
  unavailable?: boolean;
  relation?: string;
  object_label?: string | null;
  distinct_days?: number;
  evidence_count?: number;
  usual_hours?: number[];
  last_seen_at?: string | null;
  camera_id?: string;
  started_at?: string | null;
  vlm_description?: string | null;
}

interface PickerItem {
  id: string;
  display_name?: string;
  name?: string;
}

const FILTERS = [
  { key: "all", label: "All" },
  { key: "review", label: "Needs review" },
  { key: "established", label: "Established" },
  { key: "archived", label: "Archived" },
  { key: "notes", label: "Your notes" },
  { key: "rejected", label: "Rejected" },
] as const;
type FilterKey = (typeof FILTERS)[number]["key"];

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const ENTITY_BADGES: Record<string, string> = {
  household: "border-sky-500/40 text-sky-300",
  person: "border-violet-500/40 text-violet-300",
  vehicle: "border-amber-500/40 text-amber-300",
  camera: "border-teal-500/40 text-teal-300",
};

function hhmm(minutes: number) {
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

function filterParams(filter: FilterKey): string {
  switch (filter) {
    case "review":
      return "status=candidate";
    case "established":
      return "status=established";
    case "archived":
      return "status=archived";
    case "rejected":
      return "status=rejected";
    case "notes":
      return "source=user";
    default:
      return "include_archived=true"; // everything except rejected
  }
}

export default function MemoryPage() {
  return (
    <Suspense fallback={<div className="max-w-3xl mx-auto px-4 py-6"><p className="text-sm text-muted-foreground">Loading…</p></div>}>
      <MemoryPageInner />
    </Suspense>
  );
}

function MemoryPageInner() {
  const { authFetch } = useAuth();
  const toast = useToast();
  const confirm = useConfirm();
  const searchParams = useSearchParams();

  const [filter, setFilter] = useState<FilterKey>("all");
  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [entityFilter, setEntityFilter] = useState<{
    kind: string;
    key: string;
    label: string | null;
  } | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Record<string, Evidence[]>>({});

  // Deep link: /memory?entity_kind=person&entity_key=… (from a person,
  // vehicle or camera page) narrows the list to that attach point.
  useEffect(() => {
    const kind = searchParams.get("entity_kind");
    const key = searchParams.get("entity_key");
    if (kind && key) setEntityFilter({ kind, key, label: searchParams.get("label") });
  }, [searchParams]);

  const load = useCallback(async () => {
    let url = `/api/household/facts?${filterParams(filter)}`;
    if (entityFilter) {
      url += `&entity_kind=${encodeURIComponent(entityFilter.kind)}&entity_key=${encodeURIComponent(entityFilter.key)}`;
    }
    const res = await authFetch(url);
    if (res.ok) setFacts(await res.json());
    else setFacts([]);
  }, [authFetch, filter, entityFilter]);

  useEffect(() => { load(); }, [load]);

  const entityLabel = useCallback(async (kind: string, key: string): Promise<string | null> => {
    const paths: Record<string, string> = {
      person: "/api/persons",
      vehicle: "/api/vehicles",
      camera: "/api/cameras?limit=100",
    };
    const path = paths[kind];
    if (!path) return kind === "household" ? "Household" : null;
    try {
      const res = await authFetch(path);
      if (!res.ok) return null;
      const rows: PickerItem[] = await res.json();
      const row = rows.find((r) => r.id === key);
      return row ? (row.display_name ?? row.name ?? null) : null;
    } catch {
      return null;
    }
  }, [authFetch]);

  // Resolve a deep-linked entity's label once the page mounts.
  useEffect(() => {
    if (!entityFilter || entityFilter.label) return;
    entityLabel(entityFilter.kind, entityFilter.key).then((label) => {
      setEntityFilter((prev) => (prev ? { ...prev, label } : prev));
    });
  }, [entityFilter, entityLabel]);

  async function act(f: Fact, path: string, body: unknown, method = "POST") {
    const res = await authFetch(`/api/household/facts/${f.id}${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.ok) {
      await load();
      return true;
    }
    toast.error(extractApiError(await res.json().catch(() => null), "That did not go through."));
    return false;
  }

  async function decide(f: Fact, decision: "accept" | "reject") {
    if (decision === "reject") {
      const ok = await confirm({
        title: "Reject this proposal?",
        body: "Nurby will never propose it again — rejection is permanent.",
        confirmLabel: "Reject",
        danger: true,
      });
      if (!ok) return;
    }
    await act(f, "/decision", { decision });
  }

  async function toggleSuppression(f: Fact) {
    if (!f.suppresses_alerts) {
      const what = f.entity_label ?? "the household";
      const ok = await confirm({
        title: "Mute alerts in this window?",
        body:
          `While this note's schedule (${f.schedule?.summary}) holds, alerts about ${what} ` +
          "will be silenced instead of sent. You can undo this any time from the note.",
        confirmLabel: "Mute alerts",
      });
      if (!ok) return;
    }
    await act(f, "/suppression", { enabled: !f.suppresses_alerts });
  }

  async function remove(f: Fact) {
    const ok = await confirm({
      title: "Delete this note?",
      body: "This removes it for good — archive is the reversible option.",
      danger: true,
      confirmLabel: "Delete",
    });
    if (!ok) return;
    await act(f, "", undefined, "DELETE");
  }

  async function togglePin(f: Fact) {
    await act(f, "", { pinned: !f.pinned }, "PATCH");
  }

  async function toggleEnabled(f: Fact) {
    await act(f, "", { enabled: !f.enabled }, "PATCH");
  }

  async function openEvidence(f: Fact) {
    if (expandedId === f.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(f.id);
    if (evidence[f.id]) return;
    const res = await authFetch(`/api/household/facts/${f.id}/evidence`);
    if (res.ok) {
      const body = await res.json();
      setEvidence((prev) => ({ ...prev, [f.id]: body.refs ?? [] }));
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">Memory</h1>
          <p className="text-sm text-muted-foreground">
            What Nurby knows about your household — written by you, and what it
            has learned. Everything here is editable; nothing learned is hidden.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setFormOpen((v) => !v)}
          className="shrink-0 text-sm px-3 py-2 rounded border border-sky-500/50 bg-sky-500/15 text-sky-200 hover:bg-sky-500/25"
        >
          {formOpen ? "Close" : "Add a note"}
        </button>
      </div>

      {formOpen && (
        <NoteForm onDone={async () => { setFormOpen(false); await load(); }} authFetch={authFetch} toast={toast} />
      )}

      <div className="flex gap-1.5 mb-4 flex-wrap">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className={`text-xs px-2.5 py-1 rounded-full border ${
              filter === f.key
                ? "border-foreground/50 bg-foreground/10 text-foreground"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            {f.label}
            {f.key === "review" && facts?.some((x) => x.status === "candidate") ? " •" : ""}
          </button>
        ))}
        {entityFilter && (
          <button
            type="button"
            onClick={() => setEntityFilter(null)}
            className="text-xs px-2.5 py-1 rounded-full border border-sky-500/50 bg-sky-500/15 text-sky-200"
          >
            {entityFilter.kind === "household" ? "Household" : entityFilter.label ?? entityFilter.kind} ✕
          </button>
        )}
      </div>

      {facts === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : facts.length === 0 ? (
        <EmptyState
          title="Nothing here yet"
          body={
            filter === "review"
              ? "Nurby proposes facts here when it notices recurring patterns; accept or reject each one."
              : "Tell Nurby something about your household — from here, or just ask it in chat to remember something."
          }
        />
      ) : (
        <ul className="space-y-2">
          {facts.map((f) => (
            <FactCard
              key={f.id}
              fact={f}
              expanded={expandedId === f.id}
              evidence={evidence[f.id]}
              onEvidence={() => openEvidence(f)}
              onDecide={decide}
              onPin={togglePin}
              onEnabled={toggleEnabled}
              onSuppress={toggleSuppression}
              onDelete={remove}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function FactCard({
  fact: f,
  expanded,
  evidence,
  onEvidence,
  onDecide,
  onPin,
  onEnabled,
  onSuppress,
  onDelete,
}: {
  fact: Fact;
  expanded: boolean;
  evidence?: Evidence[];
  onEvidence: () => void;
  onDecide: (f: Fact, d: "accept" | "reject") => void;
  onPin: (f: Fact) => void;
  onEnabled: (f: Fact) => void;
  onSuppress: (f: Fact) => void;
  onDelete: (f: Fact) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(f.text);
  const { authFetch } = useAuth();

  async function saveEdit() {
    const text = editText.trim();
    if (!text) return;
    const res = await authFetch(`/api/household/facts/${f.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (res.ok) setEditing(false);
  }

  const entityBadge = f.entity_kind ? (
    <span className={`px-1.5 py-0.5 rounded border ${ENTITY_BADGES[f.entity_kind] ?? "border-border"}`}>
      {f.entity_kind === "household" ? "household" : f.entity_label ?? f.entity_kind}
    </span>
  ) : null;

  return (
    <li
      className={`rounded-lg border p-3 ${
        f.status === "established"
          ? "border-border bg-card/40"
          : f.status === "candidate"
            ? "border-amber-500/30 bg-amber-500/5"
            : "border-border/50 bg-card/20 opacity-70"
      }`}
    >
      {editing ? (
        <div className="flex gap-2">
          <input
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") saveEdit(); }}
            className="flex-1 text-sm bg-black/20 border border-border rounded px-2 py-1"
          />
          <button type="button" onClick={saveEdit} className="text-xs px-2 py-1 rounded border border-sky-500/50 text-sky-200">Save</button>
          <button type="button" onClick={() => { setEditing(false); setEditText(f.text); }} className="text-xs px-2 py-1 rounded border border-border text-muted-foreground">Cancel</button>
        </div>
      ) : (
        <>
          <div className="text-sm">{f.text}</div>
          <div className="mt-1.5 flex items-center gap-2 flex-wrap text-[10px]">
            <span className={`px-1.5 py-0.5 rounded border ${
              f.source === "user"
                ? "border-emerald-500/40 text-emerald-300"
                : "border-slate-500/40 text-slate-300"
            }`}>
              {f.source === "user" ? "you wrote" : "Nurby learned"}
            </span>
            {f.status === "candidate" && (
              <span className="px-1.5 py-0.5 rounded border border-amber-500/40 text-amber-300">needs review</span>
            )}
            {f.status === "archived" && (
              <span className="px-1.5 py-0.5 rounded border border-amber-500/40 text-amber-300">archived</span>
            )}
            {f.status === "rejected" && (
              <span className="px-1.5 py-0.5 rounded border border-rose-500/40 text-rose-300">rejected</span>
            )}
            {entityBadge}
            {f.schedule && (
              <span className="px-1.5 py-0.5 rounded border border-border text-muted-foreground">
                {f.schedule.summary}
              </span>
            )}
            {f.suppression_armed && (
              <span className="px-1.5 py-0.5 rounded border border-violet-500/40 text-violet-300">
                muting alerts{f.suppression_hit_count > 0 ? ` · ${f.suppression_hit_count} muted` : ""}
              </span>
            )}
            {f.evidence_count > 0 && (
              <button type="button" onClick={onEvidence} className="text-muted-foreground hover:text-foreground underline decoration-dotted">
                {f.evidence_count} evidence
              </button>
            )}
            {f.last_confirmed_at && (
              <span className="text-muted-foreground">confirmed {timeAgo(f.last_confirmed_at)}</span>
            )}
            {f.rejection_reason && (
              <span className="text-muted-foreground">reason: {f.rejection_reason}</span>
            )}
          </div>
          <div className="mt-2 flex items-center gap-2 flex-wrap text-xs">
            {f.status === "candidate" && (
              <>
                <button type="button" onClick={() => onDecide(f, "accept")} className="px-2 py-0.5 rounded border border-emerald-500/50 text-emerald-300 hover:bg-emerald-500/10">Accept</button>
                <button type="button" onClick={() => onDecide(f, "reject")} className="px-2 py-0.5 rounded border border-rose-500/50 text-rose-300 hover:bg-rose-500/10">Reject</button>
              </>
            )}
            {f.status !== "candidate" && f.status !== "rejected" && (
              <>
                <button type="button" onClick={() => setEditing(true)} className="text-muted-foreground hover:text-foreground">edit</button>
                <button type="button" onClick={() => onPin(f)} className="text-muted-foreground hover:text-foreground">{f.pinned ? "unpin" : "pin"}</button>
                {f.status === "archived" ? (
                  <button type="button" onClick={() => onEnabled(f)} className="text-muted-foreground hover:text-foreground">restore</button>
                ) : (
                  <button type="button" onClick={() => onEnabled(f)} className="text-muted-foreground hover:text-foreground">archive</button>
                )}
                {f.schedule && (
                  <button type="button" onClick={() => onSuppress(f)} className={
                    f.suppresses_alerts
                      ? "text-violet-300 hover:text-violet-200"
                      : "text-muted-foreground hover:text-foreground"
                  }>
                    {f.suppresses_alerts ? "stop muting alerts" : "mute alerts in this window"}
                  </button>
                )}
              </>
            )}
            <button type="button" onClick={() => onDelete(f)} className="ml-auto text-rose-300/80 hover:text-rose-300">delete</button>
          </div>
          {expanded && (
            <div className="mt-2 border-t border-border/50 pt-2 text-xs text-muted-foreground space-y-1">
              {evidence === undefined ? (
                <p>Loading evidence…</p>
              ) : evidence.length === 0 ? (
                <p>No stored evidence — {f.source === "user" ? "this note is the household speaking." : "the evidence rows are gone."}</p>
              ) : (
                evidence.map((e) => (
                  <div key={e.id} className="flex gap-2 flex-wrap">
                    {e.kind === "association" ? (
                      <span>
                        Pattern: <span className="text-foreground">{e.relation} {e.object_label}</span>
                        {" · "}{e.distinct_days} separate days
                        {e.usual_hours?.length ? ` · around ${e.usual_hours.map((h) => `${h}:00`).join(", ")}` : ""}
                        {e.last_seen_at ? ` · last seen ${timeAgo(e.last_seen_at)}` : ""}
                      </span>
                    ) : e.missing || e.unavailable ? (
                      <span>Reference no longer available ({e.kind})</span>
                    ) : (
                      <span>
                        {e.started_at ? `${timeAgo(e.started_at)} — ` : ""}{e.vlm_description ?? "observation"}
                      </span>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </>
      )}
    </li>
  );
}

function NoteForm({
  onDone,
  authFetch,
  toast,
}: {
  onDone: () => Promise<void>;
  authFetch: (url: string, init?: RequestInit) => Promise<Response>;
  toast: { success: (m: string) => void; error: (m: string) => void };
}) {
  const [text, setText] = useState("");
  const [attachKind, setAttachKind] = useState("household");
  const [attachKey, setAttachKey] = useState("");
  const [persons, setPersons] = useState<PickerItem[]>([]);
  const [vehicles, setVehicles] = useState<PickerItem[]>([]);
  const [cameras, setCameras] = useState<PickerItem[]>([]);
  const [scheduled, setScheduled] = useState(false);
  const [days, setDays] = useState<number[]>([]);
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("11:00");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const [p, v, c] = await Promise.all([
        authFetch("/api/persons"),
        authFetch("/api/vehicles"),
        authFetch("/api/cameras?limit=100"),
      ]);
      if (p.ok) setPersons(await p.json());
      if (v.ok) setVehicles(await v.json());
      if (c.ok) {
        const body = await c.json();
        setCameras(Array.isArray(body) ? body : (body.cameras ?? []));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submit() {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    if (scheduled && days.length === 0) {
      toast.error("Pick at least one weekday for the schedule.");
      return;
    }
    const body: Record<string, unknown> = { text: trimmed };
    if (attachKind !== "household") {
      if (!attachKey) {
        toast.error("Pick which one this note is about.");
        return;
      }
      body.entity_kind = attachKind;
      body.entity_key = attachKey;
    }
    if (scheduled) {
      const startMin = Number(start.split(":")[0]) * 60 + Number(start.split(":")[1]);
      const endMin = Number(end.split(":")[0]) * 60 + Number(end.split(":")[1]);
      if (endMin <= startMin) {
        toast.error("The window must end after it starts, within one day.");
        return;
      }
      body.schedule = { days, start_minute: startMin, end_minute: endMin };
    }
    setBusy(true);
    try {
      const res = await authFetch("/api/household/facts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        toast.success("Noted.");
        await onDone();
      } else {
        toast.error(extractApiError(await res.json().catch(() => null), "Could not add that note."));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-5 rounded-lg border border-border bg-card/30 p-3 space-y-3">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="e.g. The cleaner comes Thursdays and has a key. The side gate is always left open."
        rows={2}
        className="w-full text-sm bg-black/20 border border-border rounded px-3 py-2 outline-none focus:border-foreground/40"
      />
      <div className="flex gap-2 flex-wrap items-center text-xs">
        <span className="text-muted-foreground">Attach to</span>
        {(["household", "person", "vehicle", "camera"] as const).map((kind) => (
          <button
            key={kind}
            type="button"
            onClick={() => { setAttachKind(kind); setAttachKey(""); }}
            className={`px-2 py-0.5 rounded-full border ${
              attachKind === kind
                ? "border-foreground/50 bg-foreground/10"
                : "border-border text-muted-foreground"
            }`}
          >
            {kind}
          </button>
        ))}
        {attachKind === "person" && (
          <select value={attachKey} onChange={(e) => setAttachKey(e.target.value)} className="text-xs bg-black/20 border border-border rounded px-2 py-1">
            <option value="">Pick a person…</option>
            {persons.map((p) => <option key={p.id} value={p.id}>{p.display_name ?? p.name}</option>)}
          </select>
        )}
        {attachKind === "vehicle" && (
          <select value={attachKey} onChange={(e) => setAttachKey(e.target.value)} className="text-xs bg-black/20 border border-border rounded px-2 py-1">
            <option value="">Pick a vehicle…</option>
            {vehicles.map((v) => <option key={v.id} value={v.id}>{v.display_name ?? v.name}</option>)}
          </select>
        )}
        {attachKind === "camera" && (
          <select value={attachKey} onChange={(e) => setAttachKey(e.target.value)} className="text-xs bg-black/20 border border-border rounded px-2 py-1">
            <option value="">Pick a camera…</option>
            {cameras.map((c) => <option key={c.id} value={c.id}>{c.display_name ?? c.name}</option>)}
          </select>
        )}
      </div>
      <div className="flex gap-2 flex-wrap items-center text-xs">
        <label className="flex items-center gap-1.5 text-muted-foreground">
          <input type="checkbox" checked={scheduled} onChange={(e) => setScheduled(e.target.checked)} />
          Recurring schedule
        </label>
        {scheduled && (
          <>
            <span className="flex gap-1">
              {WEEKDAYS.map((name, i) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => setDays((d) => (d.includes(i) ? d.filter((x) => x !== i) : [...d, i].sort()))}
                  className={`px-1.5 py-0.5 rounded border ${
                    days.includes(i)
                      ? "border-sky-500/50 bg-sky-500/15 text-sky-200"
                      : "border-border text-muted-foreground"
                  }`}
                >
                  {name}
                </button>
              ))}
            </span>
            <input type="time" value={start} onChange={(e) => setStart(e.target.value)} className="bg-black/20 border border-border rounded px-2 py-1" />
            <span className="text-muted-foreground">to</span>
            <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} className="bg-black/20 border border-border rounded px-2 py-1" />
          </>
        )}
      </div>
      {scheduled && (
        <p className="text-[11px] text-muted-foreground">
          After saving you can have matching alerts muted during this window — the
          note&apos;s page shows the switch, and it stays reversible.
        </p>
      )}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={submit}
          disabled={busy || !text.trim()}
          className="text-sm px-3 py-1.5 rounded border border-sky-500/50 bg-sky-500/15 text-sky-200 hover:bg-sky-500/25 disabled:opacity-50"
        >
          Save note
        </button>
      </div>
    </div>
  );
}
