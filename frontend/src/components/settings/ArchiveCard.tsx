// Archive tier (issue #270): keep recent footage on this machine and move
// older footage to an S3 bucket or FTP server instead of deleting it. Each
// camera's retention period is how long footage stays local; the archive
// has its own lifetime. Admin-only (the endpoints are too).

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import {
  AddLocationForm,
  STORAGE_CLASSES,
  locationLabel,
  type StorageProfile,
} from "@/components/storage/AddLocationForm";

interface ArchiveCamera {
  id: string;
  name: string;
  retention_mode: string;
  retention_days: number;
  retention_gb: number;
}

export interface ArchiveSettings {
  profile_id: string | null;
  profile_name: string | null;
  kind: string | null;
  storage_class: string | null;
  retention_days: number;
  active: boolean;
  broken: boolean;
  stats: { pending: number; failed: number; uploaded: number; uploaded_bytes: number };
  cameras: ArchiveCamera[];
}

const ARCHIVE_LIFETIMES = [
  { days: 0, label: "Forever" },
  { days: 90, label: "90 days" },
  { days: 180, label: "6 months" },
  { days: 365, label: "1 year" },
  { days: 730, label: "2 years" },
  { days: 1095, label: "3 years" },
];

function size(bytes: number): string {
  const gb = bytes / 1024 ** 3;
  if (gb >= 1024) return `${(gb / 1024).toFixed(1)} TB`;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

function lifetime(days: number): string {
  return ARCHIVE_LIFETIMES.find((l) => l.days === days)?.label.toLowerCase() ?? `${days} days`;
}

function localWindow(c: ArchiveCamera): string {
  if (c.retention_mode === "time") return `${c.retention_days} days`;
  if (c.retention_mode === "size") return `up to ${c.retention_gb} GB`;
  return "forever";
}

export function ArchiveCard() {
  const { authFetch } = useAuth();
  const [settings, setSettings] = useState<ArchiveSettings | null>(null);
  const [profiles, setProfiles] = useState<StorageProfile[]>([]);
  const [target, setTarget] = useState<string>("");
  const [days, setDays] = useState(0);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [failed, setFailed] = useState(false);
  const [localDays, setLocalDays] = useState(30);
  const [applying, setApplying] = useState(false);

  const load = useCallback(async () => {
    try {
      const [a, p] = await Promise.all([
        authFetch("/api/storage/archive"),
        authFetch("/api/storage-profiles"),
      ]);
      if (!a.ok || !p.ok) throw new Error();
      const raw = await a.json();
      const s: ArchiveSettings = {
        ...raw,
        profile_id: raw?.profile_id ?? null,
        retention_days: Number(raw?.retention_days) || 0,
        stats: { pending: 0, failed: 0, uploaded: 0, uploaded_bytes: 0, ...(raw?.stats ?? {}) },
        cameras: Array.isArray(raw?.cameras) ? raw.cameras : [],
      };
      setSettings(s);
      setTarget(s.profile_id ?? "");
      setDays(s.retention_days);
      const list: unknown = await p.json();
      setProfiles(
        Array.isArray(list)
          ? (list as StorageProfile[]).filter((x) => x.kind === "s3" || x.kind === "ftp")
          : [],
      );
    } catch {
      setFailed(true);
    }
  }, [authFetch]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (profileId: string, keepDays: number) => {
    setSaving(true);
    setError("");
    try {
      const res = await authFetch("/api/storage/archive", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile_id: profileId || null, retention_days: keepDays }),
      });
      const d = await res.json().catch(() => null);
      if (!res.ok) {
        setError(d?.detail || "Could not save the archive settings.");
        return;
      }
      await load();
    } finally {
      setSaving(false);
    }
  };

  // One click for the common case: every "keep forever" camera keeps
  // `localDays` here and then archives. Per-camera retention stays editable.
  const applyLocalWindow = async (ids: string[]) => {
    setApplying(true);
    setError("");
    try {
      const results = await Promise.all(
        ids.map((id) =>
          authFetch(`/api/cameras/${id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ retention_mode: "time", retention_days: localDays }),
          }),
        ),
      );
      if (results.some((r) => !r.ok)) setError("Some cameras could not be updated.");
      await load();
    } finally {
      setApplying(false);
    }
  };

  if (failed) {
    return <p className="text-xs text-muted-foreground">Could not load archive settings.</p>;
  }
  if (!settings) {
    return <p className="text-xs text-muted-foreground">Loading archive settings.</p>;
  }

  const dirty = target !== (settings.profile_id ?? "") || days !== settings.retention_days;
  const chosen = profiles.find((p) => p.id === target);
  const klass = STORAGE_CLASSES.find((c) => c.value === settings.storage_class);
  const needsRestore = settings.storage_class === "GLACIER" || settings.storage_class === "DEEP_ARCHIVE";
  const keepsForever = settings.cameras.filter((c) => c.retention_mode === "none");
  const archiving = settings.cameras.filter((c) => c.retention_mode !== "none");
  const { stats } = settings;

  return (
    <div className="space-y-3">
      <div>
        <div className="text-sm font-medium">Archive older recordings</div>
        <p className="text-xs text-muted-foreground mt-0.5">
          Keep recent footage on this machine and move older footage to a cloud bucket or
          FTP server instead of deleting it.
        </p>
      </div>

      {settings.broken && (
        <div className="rounded-md px-3 py-2 text-xs bg-red-500/10 border border-red-500/20 text-red-400">
          The archive destination is missing or disabled, so old recordings are being deleted
          instead of archived. Pick a destination below.
        </div>
      )}

      <div className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
        <label className="text-[11px] text-muted-foreground space-y-1">
          <span>Move old recordings to</span>
          <select
            value={adding ? "__add" : target}
            aria-label="Archive destination"
            onChange={(e) => {
              if (e.target.value === "__add") {
                setAdding(true);
              } else {
                setAdding(false);
                setTarget(e.target.value);
              }
            }}
            className="w-full text-xs bg-background border border-border rounded px-2 py-1.5 text-foreground"
          >
            <option value="">Nowhere. Delete them when they age out</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({locationLabel(p)})
              </option>
            ))}
            <option value="__add">+ Add an S3 bucket or FTP server</option>
          </select>
        </label>
        <label className="text-[11px] text-muted-foreground space-y-1">
          <span>Keep in the archive</span>
          <select
            value={days}
            aria-label="Keep in the archive"
            disabled={!target}
            onChange={(e) => setDays(Number(e.target.value))}
            className="w-full sm:w-32 text-xs bg-background border border-border rounded px-2 py-1.5 text-foreground disabled:opacity-50"
          >
            {ARCHIVE_LIFETIMES.map((l) => (
              <option key={l.days} value={l.days}>{l.label}</option>
            ))}
          </select>
        </label>
      </div>

      {adding && (
        <AddLocationForm
          kinds={["s3", "ftp"]}
          defaultStorageClass="GLACIER_IR"
          onCreated={(p) => {
            setProfiles((list) => [...list, p].sort((a, b) => a.name.localeCompare(b.name)));
            setTarget(p.id);
            setAdding(false);
          }}
          onCancel={() => setAdding(false)}
        />
      )}

      {dirty && !adding && (
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={saving}
            onClick={() => save(target, target ? days : 0)}
            className="px-3 py-1.5 text-xs rounded-md bg-accent text-black font-medium hover:bg-accent/90 transition-colors disabled:opacity-50"
          >
            {saving ? "Saving." : target ? `Archive to ${chosen?.name ?? "this location"}` : "Turn off archiving"}
          </button>
          <button
            type="button"
            onClick={() => {
              setTarget(settings.profile_id ?? "");
              setDays(settings.retention_days);
            }}
            className="text-[11px] text-muted-foreground hover:text-foreground"
          >
            Cancel
          </button>
        </div>
      )}
      {error && <p className="text-[11px] text-red-400">{error}</p>}

      {settings.active && !dirty && (
        <div className="rounded-md border border-border bg-muted/20 p-3 space-y-2 text-xs">
          <p className="text-foreground/90">
            Recordings stay on this machine for each camera&apos;s retention period, then move to{" "}
            <span className="font-medium">{settings.profile_name}</span>
            {klass ? ` (${klass.label})` : ""} and are{" "}
            {settings.retention_days ? `deleted after ${lifetime(settings.retention_days)}` : "kept forever"}.
          </p>
          {needsRestore && (
            <p className="text-[11px] text-amber-300">
              {klass?.label} needs a restore before playback. Opening an archived recording
              requests one, and it plays a few hours later.
            </p>
          )}
          <p className="text-[11px] text-muted-foreground">
            {stats.uploaded} archived{stats.uploaded ? ` (${size(stats.uploaded_bytes)})` : ""}
            {stats.pending ? ` · ${stats.pending} moving now` : ""}
          </p>
          {stats.failed > 0 && (
            <p className="text-[11px] text-red-400">
              {stats.failed} failed to upload and are still only on this machine. They are
              kept, not deleted. Check the destination with Test connection.
            </p>
          )}
          {archiving.length > 0 && (
            <ul className="space-y-0.5 text-[11px] text-muted-foreground">
              {archiving.map((c) => (
                <li key={c.id}>
                  <Link href={`/cameras/${c.id}`} className="hover:text-foreground">
                    {c.name}
                  </Link>
                  : {localWindow(c)} here, then archived
                </li>
              ))}
            </ul>
          )}
          {keepsForever.length > 0 && (
            <p className="text-[11px] text-amber-300">
              {keepsForever.length === 1 ? "1 camera keeps" : `${keepsForever.length} cameras keep`} everything
              on this machine, so nothing from {keepsForever.length === 1 ? "it" : "them"} is archived:{" "}
              {keepsForever.map((c, i) => (
                <span key={c.id}>
                  {i > 0 ? ", " : ""}
                  <Link href={`/cameras/${c.id}`} className="underline">
                    {c.name}
                  </Link>
                </span>
              ))}
              .
            </p>
          )}
          {keepsForever.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-[11px]">
              <span className="text-muted-foreground">Keep</span>
              <select
                value={localDays}
                aria-label="Days to keep on this machine"
                onChange={(e) => setLocalDays(Number(e.target.value))}
                className="text-xs bg-background border border-border rounded px-2 py-1"
              >
                {[7, 14, 30, 60, 90].map((d) => (
                  <option key={d} value={d}>{d} days</option>
                ))}
              </select>
              <span className="text-muted-foreground">on this machine, then archive</span>
              <button
                type="button"
                disabled={applying}
                onClick={() => applyLocalWindow(keepsForever.map((c) => c.id))}
                className="px-2.5 py-1 rounded-md border border-border hover:bg-muted transition-colors disabled:opacity-50"
              >
                {applying
                  ? "Applying."
                  : `Apply to ${keepsForever.length === 1 ? "this camera" : `these ${keepsForever.length} cameras`}`}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
