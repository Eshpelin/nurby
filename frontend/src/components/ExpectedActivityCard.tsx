"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

type Person = { id: string; display_name: string; nickname?: string | null };
type Camera = { id: string; name: string };
type Expectation = {
  id: string;
  name: string;
  subject_person_id: string | null;
  subject_key: string | null;
  camera_ids: string[];
  weekdays: number[];
  start_time: string;
  end_time: string;
  grace_minutes: number;
  enabled: boolean;
  last_status: string | null;
};

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function ExpectedActivityCard() {
  const { authFetch } = useAuth();
  const [people, setPeople] = useState<Person[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [items, setItems] = useState<Expectation[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [personId, setPersonId] = useState("");
  const [cameraIds, setCameraIds] = useState<string[]>([]);
  const [weekdays, setWeekdays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [startTime, setStartTime] = useState("08:00");
  const [endTime, setEndTime] = useState("18:00");
  const [graceMinutes, setGraceMinutes] = useState("30");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [expectations, peopleResponse, camerasResponse] = await Promise.all([
        authFetch("/api/expected-activity"),
        authFetch("/api/persons"),
        authFetch("/api/cameras"),
      ]);
      if (!expectations.ok) throw new Error(`Expected activity unavailable (${expectations.status})`);
      setItems(await expectations.json());
      if (peopleResponse.ok) setPeople(await peopleResponse.json());
      if (camerasResponse.ok) setCameras(await camerasResponse.json());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Expected activity unavailable");
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => { void load(); }, [load]);

  const create = async () => {
    if (!name.trim() || !personId || weekdays.length === 0) {
      setError("Choose a person, name this expectation, and select at least one day.");
      return;
    }
    setSaving(true);
    try {
      const response = await authFetch("/api/expected-activity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          subject_kind: "person",
          subject_person_id: personId,
          camera_ids: cameraIds,
          weekdays,
          start_time: startTime,
          end_time: endTime,
          grace_minutes: Number(graceMinutes) || 0,
          enabled: true,
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(typeof body?.detail === "string" ? body.detail : `Could not save expectation (${response.status})`);
      }
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save expectation");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    const response = await authFetch(`/api/expected-activity/${id}`, { method: "DELETE" });
    if (response.ok) setItems((current) => current.filter((item) => item.id !== id));
    else setError(`Could not remove expectation (${response.status})`);
  };

  const personLabel = (id: string | null, fallback: string | null) => {
    const person = people.find((candidate) => candidate.id === id);
    return person ? person.nickname || person.display_name : fallback || "Unknown person";
  };

  return (
    <section id="expected-activity" className="rounded-lg border border-border bg-card px-4 py-3.5 scroll-mt-24">
      <div className="mb-3">
        <div className="text-sm font-medium">Expected activity</div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Choose a person by identity, not by typed name. These reminders never grant access or change alert rules.
        </p>
      </div>
      {error && <p role="alert" className="mb-3 rounded border border-red-500/30 bg-red-500/10 px-2 py-1.5 text-xs text-red-300">{error}</p>}
      <div className="grid gap-2 sm:grid-cols-2">
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Expectation name, e.g. Simon arrives" className="rounded border border-border bg-background px-2.5 py-2 text-sm" />
        <select aria-label="Expected person" value={personId} onChange={(event) => setPersonId(event.target.value)} className="rounded border border-border bg-background px-2.5 py-2 text-sm">
          <option value="">Choose a person…</option>
          {people.map((person) => <option key={person.id} value={person.id}>{person.nickname || person.display_name}</option>)}
        </select>
        <label className="text-xs text-muted-foreground">From <input type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} className="ml-1 rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground" /></label>
        <label className="text-xs text-muted-foreground">Until <input type="time" value={endTime} onChange={(event) => setEndTime(event.target.value)} className="ml-1 rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground" /></label>
      </div>
      <div className="mt-2">
        <div className="mb-1 text-[11px] text-muted-foreground">Days</div>
        <div className="flex flex-wrap gap-1.5">
          {DAYS.map((day, index) => {
            const selected = weekdays.includes(index);
            return <button key={day} type="button" onClick={() => setWeekdays((current) => selected ? current.filter((value) => value !== index) : [...current, index].sort())} className={`rounded border px-2 py-1 text-xs ${selected ? "border-accent bg-accent/10 text-accent" : "border-border text-muted-foreground"}`}>{day}</button>;
          })}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-end gap-3">
        <label className="text-xs text-muted-foreground">Grace minutes <input type="number" min="0" max="1440" value={graceMinutes} onChange={(event) => setGraceMinutes(event.target.value)} className="ml-1 w-20 rounded border border-border bg-background px-2 py-1.5 text-sm text-foreground" /></label>
        <div className="min-w-52 flex-1">
          <div className="mb-1 text-[11px] text-muted-foreground">Cameras (empty means any camera)</div>
          <div className="flex flex-wrap gap-1.5">
            {cameras.map((camera) => {
              const selected = cameraIds.includes(camera.id);
              return <button key={camera.id} type="button" onClick={() => setCameraIds((current) => selected ? current.filter((id) => id !== camera.id) : [...current, camera.id])} className={`rounded border px-2 py-1 text-xs ${selected ? "border-accent bg-accent/10 text-accent" : "border-border text-muted-foreground"}`}>{camera.name}</button>;
            })}
          </div>
        </div>
        <button type="button" disabled={saving || loading} onClick={() => void create()} className="rounded border border-accent px-3 py-1.5 text-xs text-accent hover:bg-accent/10 disabled:opacity-50">{saving ? "Saving…" : "Add expectation"}</button>
      </div>
      {loading ? <p className="mt-3 text-xs text-muted-foreground">Loading expectations…</p> : items.length > 0 && (
        <div className="mt-4 space-y-2 border-t border-border pt-3">
          {items.map((item) => <div key={item.id} className="flex items-center justify-between gap-3 rounded border border-border/70 px-2.5 py-2 text-xs">
            <div className="min-w-0"><div className="truncate font-medium">{item.name}</div><div className="text-[11px] text-muted-foreground">{personLabel(item.subject_person_id, item.subject_key)} · {item.start_time}–{item.end_time} · {item.enabled ? "enabled" : "paused"}</div></div>
            <button type="button" onClick={() => void remove(item.id)} className="shrink-0 text-[11px] text-muted-foreground hover:text-red-300">Remove</button>
          </div>)}
        </div>
      )}
    </section>
  );
}
