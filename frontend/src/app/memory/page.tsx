"use client";

/**
 * Memory tab (#286). What Nurby remembers about the household: facts you told
 * it (source=user) and facts it learned (source=agent). Read, add, edit,
 * disable, and prune. Disabling archives a fact so it stops feeding answers but
 * stays visible; the curator never rewrites a fact you authored.
 */

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useToast, useConfirm } from "@/lib/feedback";
import { EmptyState } from "@/components/EmptyState";
import { timeAgo } from "@/lib/time";

interface Fact {
  id: string;
  text: string;
  kind: string;
  source: string; // user | agent
  status: string;
  enabled: boolean;
  pinned: boolean;
  evidence_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export default function MemoryPage() {
  const { authFetch } = useAuth();
  const toast = useToast();
  const confirm = useConfirm();
  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  const load = useCallback(async () => {
    const res = await authFetch("/api/household/facts");
    if (res.ok) setFacts(await res.json());
    else setFacts([]);
  }, [authFetch]);

  useEffect(() => { load(); }, [load]);

  async function add() {
    const text = draft.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      const res = await authFetch("/api/household/facts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (res.ok) {
        setDraft("");
        await load();
        toast.success("Added to memory.");
      } else {
        toast.error("Could not add that fact.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function saveEdit(id: string) {
    const text = editText.trim();
    if (!text) return;
    const res = await authFetch(`/api/household/facts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (res.ok) {
      setEditingId(null);
      await load();
    } else {
      toast.error("Could not save the edit.");
    }
  }

  async function toggleEnabled(f: Fact) {
    const res = await authFetch(`/api/household/facts/${f.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !f.enabled }),
    });
    if (res.ok) await load();
  }

  async function remove(f: Fact) {
    const ok = await confirm({
      title: "Delete this memory?",
      danger: true,
      confirmLabel: "Delete",
    });
    if (!ok) return;
    const res = await authFetch(`/api/household/facts/${f.id}`, { method: "DELETE" });
    if (res.ok || res.status === 204) await load();
    else toast.error("Could not delete.");
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      <div className="mb-4">
        <h1 className="text-lg font-semibold">Memory</h1>
        <p className="text-sm text-muted-foreground">
          What Nurby remembers about your household. It uses these when answering.
        </p>
      </div>

      <div className="flex gap-2 mb-5">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") add(); }}
          placeholder="e.g. The kids get home around 3:30pm on weekdays"
          className="flex-1 text-sm bg-black/20 border border-border rounded px-3 py-2 outline-none focus:border-foreground/40"
        />
        <button
          type="button"
          onClick={add}
          disabled={busy || !draft.trim()}
          className="text-sm px-3 py-2 rounded border border-sky-500/50 bg-sky-500/15 text-sky-200 hover:bg-sky-500/25 disabled:opacity-50"
        >
          Remember
        </button>
      </div>

      {facts === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : facts.length === 0 ? (
        <EmptyState
          title="Nothing remembered yet"
          body="Tell Nurby something about your household and it will keep it here."
        />
      ) : (
        <ul className="space-y-2">
          {facts.map((f) => (
            <li
              key={f.id}
              className={`rounded-lg border p-3 ${
                f.enabled ? "border-border bg-card/40" : "border-border/50 bg-card/20 opacity-70"
              }`}
            >
              {editingId === f.id ? (
                <div className="flex gap-2">
                  <input
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    className="flex-1 text-sm bg-black/20 border border-border rounded px-2 py-1"
                  />
                  <button type="button" onClick={() => saveEdit(f.id)} className="text-xs px-2 py-1 rounded border border-sky-500/50 text-sky-200">Save</button>
                  <button type="button" onClick={() => setEditingId(null)} className="text-xs px-2 py-1 rounded border border-border text-muted-foreground">Cancel</button>
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
                      {f.source === "user" ? "told by you" : "learned"}
                    </span>
                    {!f.enabled && (
                      <span className="px-1.5 py-0.5 rounded border border-amber-500/40 text-amber-300">disabled</span>
                    )}
                    {f.updated_at && (
                      <span className="text-muted-foreground">updated {timeAgo(f.updated_at)}</span>
                    )}
                    <div className="ml-auto flex items-center gap-2">
                      <button type="button" onClick={() => { setEditingId(f.id); setEditText(f.text); }} className="text-muted-foreground hover:text-foreground">edit</button>
                      <button type="button" onClick={() => toggleEnabled(f)} className="text-muted-foreground hover:text-foreground">
                        {f.enabled ? "disable" : "enable"}
                      </button>
                      <button type="button" onClick={() => remove(f)} className="text-rose-300/80 hover:text-rose-300">delete</button>
                    </div>
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
