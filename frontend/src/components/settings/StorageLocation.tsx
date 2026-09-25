"use client";

// Media storage (issues #251/#266). Shared pieces:
//   StorageLocationForm  — pick/validate/save the recordings root (used by
//                          the onboarding wizard and the settings overview)
//   StorageOverviewBlock — the full overview: every media root with
//                          writable status + capacity, low-space warnings,
//                          copyable Docker remediation, and the form
//
// Embedded in the existing settings "Storage" card (usage bars + retention
// live there too, from GET /api/storage) so location, usage, and retention
// read as one surface, not three.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { ArchiveCard } from "@/components/settings/ArchiveCard";

interface StorageLocationInfo {
  key: string; // recordings | thumbnails | audio
  path: string;
  source: string; // default | custom
  exists: boolean;
  writable: boolean;
  free_bytes: number | null;
  total_bytes: number | null;
}

interface StorageStatus {
  locations: StorageLocationInfo[];
  docker: boolean;
  low_space: boolean;
  warnings: string[];
}

interface StorageValidation {
  ok: boolean;
  path: string;
  created: boolean;
  writable: boolean;
  free_bytes: number | null;
  detail: string;
}

interface StorageProfileSummary {
  id: string;
  name: string;
  kind: string;
  stats?: { uploaded_bytes?: number } | null;
}

export function useStorageOverview(enabled: boolean, pollMs?: number) {
  // One overview fetch (GET /api/system/storage, admin-only) shared by the
  // settings card, the dashboard low-space banner and the forms. `enabled`
  // lets non-admins and unmounted surfaces skip the 403 entirely.
  const { authFetch } = useAuth();
  const [overview, setOverview] = useState<StorageStatus | null>(null);

  const reload = useCallback(async () => {
    if (!enabled) return;
    try {
      const res = await authFetch("/api/system/storage");
      setOverview(res.ok ? await res.json() : null);
    } catch {
      setOverview(null);
    }
  }, [authFetch, enabled]);

  useEffect(() => {
    if (!enabled) return;
    reload();
    if (!pollMs) return;
    const t = setInterval(reload, pollMs);
    return () => clearInterval(t);
  }, [reload, enabled, pollMs]);

  return { overview, reload };
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "unknown";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB free`;
  const mb = bytes / 1024 ** 2;
  return `${Math.max(0, mb).toFixed(0)} MB free`;
}

const LOCATION_LABELS: Record<string, string> = {
  recordings: "Recordings",
  thumbnails: "Thumbnails",
  audio: "Audio",
};

// ── Location form (change the recordings root) ───────────────────────

export function StorageLocationForm({
  onSaved,
  showCurrent = true,
}: {
  onSaved?: () => void;
  showCurrent?: boolean;
}) {
  const { authFetch, user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { overview: status, reload: refreshStatus } = useStorageOverview(isAdmin);
  const [path, setPath] = useState("");
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validation, setValidation] = useState<StorageValidation | null>(null);
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Prefill once the overview arrives (without clobbering user input).
  useEffect(() => {
    if (status) {
      setPath((p) => p || status.locations.find((l) => l.key === "recordings")?.path || "");
    }
  }, [status]);

  const validate = useCallback(
    async (target?: string): Promise<StorageValidation | null> => {
      const candidate = (target ?? path).trim();
      if (!candidate) return null;
      setChecking(true);
      setValidation(null);
      try {
        const res = await authFetch("/api/system/storage/validate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: candidate }),
        });
        const d: StorageValidation = await res.json();
        setValidation(d);
        return d;
      } catch {
        return null;
      } finally {
        setChecking(false);
      }
    },
    [authFetch, path],
  );

  const save = useCallback(
    async (value: string | null) => {
      setSaving(true);
      setSaved(false);
      try {
        const res = await authFetch("/api/system/settings", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ storage_recordings_dir: value }),
        });
        if (res.ok) {
          setSaved(true);
          setDirty(false);
          onSaved?.();
          refreshStatus();
          return true;
        }
        const body = await res.json().catch(() => null);
        setValidation({
          ok: false,
          path: value ?? "",
          created: false,
          writable: false,
          free_bytes: null,
          detail: body?.detail ? String(body.detail) : "Could not save the location.",
        });
        return false;
      } finally {
        setSaving(false);
      }
    },
    [authFetch, refreshStatus, onSaved],
  );

  const saveInput = useCallback(async () => {
    const candidate = path.trim();
    const result = validation?.path === candidate ? validation : await validate(candidate);
    if (result?.ok) await save(candidate);
  }, [path, save, validate, validation]);

  const resetToDefault = useCallback(async () => {
    if (await save(null)) {
      setValidation(null);
      const rec = status?.locations.find((l) => l.key === "recordings");
      if (rec) setPath(rec.path);
    }
  }, [save, status]);

  const recordings = status?.locations.find((l) => l.key === "recordings");
  const isCustom = recordings?.source === "custom";

  return (
    <div className="space-y-2.5">
      <div>
        <label
          htmlFor="storage-recordings-dir"
          className="text-sm font-medium text-foreground"
        >
          Where should recordings be stored?
        </label>
        <p className="text-xs text-muted-foreground mt-0.5">
          New recordings, clips, and their caches land here. Existing files
          stay in the previous location — pick this before adding cameras.
        </p>
      </div>

      <div className="flex gap-2">
        <input
          id="storage-recordings-dir"
          value={path}
          onChange={(e) => {
            setPath(e.target.value);
            setDirty(true);
            setSaved(false);
          }}
          placeholder="D:\Nurby\recordings or /srv/nurby/recordings"
          className="flex-1 text-xs font-mono bg-background border border-border rounded px-2 py-1.5"
        />
        <button
          type="button"
          disabled={checking || !path.trim() || !dirty}
          onClick={() => validate()}
          className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted transition-colors disabled:opacity-50 whitespace-nowrap"
        >
          {checking ? "Checking…" : "Check"}
        </button>
      </div>

      {showCurrent && recordings && (
        <p className="text-[11px] text-muted-foreground">
          Current: <code className="bg-background px-1 rounded">{recordings.path}</code>
          {" · "}
          {recordings.writable ? "writable" : "not writable"}
          {recordings.free_bytes !== null ? ` · ${formatBytes(recordings.free_bytes)}` : ""}
          {isCustom ? " · custom location" : ""}
        </p>
      )}

      {dirty && recordings && path.trim() !== recordings.path && (
        <p className="text-[11px] text-amber-300">
          Heads-up: recordings already written stay in the previous location
          and won&apos;t play until moved. New recordings use the new
          location immediately.{" "}
          <a
            href="https://github.com/Eshpelin/nurby/blob/main/docs/operations/storage-location.md"
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            Migration notes
          </a>
        </p>
      )}

      {status?.docker && (
        <p className="text-[11px] text-amber-300">
          Nurby is running in Docker: enter a path inside the container (the
          default maps to your host volume). To use another host drive, set{" "}
          <code className="bg-background px-1 rounded">NURBY_RECORDINGS_VOLUME</code>{" "}
          in <code className="bg-background px-1 rounded">.env</code> — see{" "}
          <code className="bg-background px-1 rounded">docs/operations/storage-location.md</code>.
        </p>
      )}

      {validation && (
        <p
          className={`text-[11px] ${validation.ok ? "text-emerald-400" : "text-red-400"}`}
        >
          {validation.detail}
          {validation.ok && validation.free_bytes !== null
            ? ` (${formatBytes(validation.free_bytes)})`
            : ""}
        </p>
      )}
      {saved && (
        <p className="text-[11px] text-emerald-400">
          Saved — new recordings will use this location.
        </p>
      )}

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={saving || checking || !dirty}
          onClick={saveInput}
          className="px-3 py-1.5 text-xs rounded-md bg-accent text-black font-medium hover:bg-accent/90 transition-colors disabled:opacity-50"
        >
          {saving ? "Saving…" : "Use this location"}
        </button>
        {isCustom && (
          <button
            type="button"
            disabled={saving}
            onClick={resetToDefault}
            className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted transition-colors disabled:opacity-50"
          >
            Reset to default
          </button>
        )}
      </div>
    </div>
  );
}

// ── Full overview (embeds the form) ──────────────────────────────────

function CopyableEnvBlock({ docker }: { docker: boolean }) {
  const [copied, setCopied] = useState(false);
  const text = [
    "# .env — store media on another host drive (Docker)",
    "NURBY_RECORDINGS_VOLUME=D:/Nurby/recordings",
    "NURBY_THUMBNAILS_VOLUME=D:/Nurby/thumbnails",
    "NURBY_AUDIO_VOLUME=D:/Nurby/audio",
  ].join("\n");
  if (!docker) return null;
  return (
    <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 space-y-1.5">
      <p className="text-[11px] text-amber-300">
        Nurby is running in Docker. Paths above are container paths — they map
        to host drives through compose volumes. Changing the UI field picks a
        container path; to use a different host drive, put this in your{" "}
        <code className="bg-background px-1 rounded">.env</code> and restart:
      </p>
      <pre className="text-[10px] font-mono bg-background rounded p-2 overflow-x-auto">
        {text}
      </pre>
      <button
        type="button"
        onClick={() => {
          navigator.clipboard?.writeText(text).then(
            () => {
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            },
            () => undefined,
          );
        }}
        className="text-[11px] text-accent hover:underline"
      >
        {copied ? "Copied" : "Copy .env block"}
      </button>
    </div>
  );
}

export function StorageOverviewBlock() {
  const { user, authFetch } = useAuth();
  const { overview: status } = useStorageOverview(user?.role === "admin");
  const [profiles, setProfiles] = useState<StorageProfileSummary[]>([]);

  useEffect(() => {
    if (user?.role !== "admin") return;
    authFetch("/api/storage-profiles")
      .then(async (res) => (res.ok ? res.json() : []))
      .then((data) => setProfiles(Array.isArray(data) ? data : []))
      .catch(() => setProfiles([]));
  }, [authFetch, user?.role]);

  return (
    <div className="space-y-4">
      {status?.warnings.map((w) => (
        <div
          key={w}
          className={`rounded-md px-3 py-2 text-xs ${
            status.low_space
              ? "bg-red-500/10 border border-red-500/20 text-red-400"
              : "bg-amber-500/10 border border-amber-500/20 text-amber-300"
          }`}
        >
          {w}
        </div>
      ))}

      <div className="space-y-1.5">
        {(status?.locations ?? []).map((loc) => (
          <div
            key={loc.key}
            className="flex items-center justify-between gap-3 text-xs"
          >
            <div className="flex items-center gap-2 min-w-0">
              <span
                className={`w-2 h-2 rounded-full flex-shrink-0 ${
                  !loc.exists
                    ? "bg-muted-foreground/40"
                    : loc.writable
                      ? "bg-green-500"
                      : "bg-red-500"
                }`}
                title={!loc.exists ? "Missing" : loc.writable ? "Writable" : "Not writable"}
              />
              <span className="text-muted-foreground w-20 flex-shrink-0">
                {LOCATION_LABELS[loc.key] ?? loc.key}
              </span>
              <code className="bg-background px-1 rounded truncate">{loc.path}</code>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              {loc.source === "custom" && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent/10 text-accent">
                  custom
                </span>
              )}
              <span className="text-[11px] text-muted-foreground">
                {formatBytes(loc.free_bytes)}
              </span>
            </div>
          </div>
        ))}
        {!status && (
          <p className="text-xs text-muted-foreground">Loading locations…</p>
        )}
      </div>

      {profiles.some((p) => p.kind === "ftp") && (
        <div className="space-y-1.5">
          <div className="text-xs font-medium">FTP locations</div>
          {profiles.filter((p) => p.kind === "ftp").map((profile) => (
            <div key={profile.id} className="flex items-center justify-between gap-3 text-xs">
              <span className="text-muted-foreground truncate">{profile.name}</span>
              <span className="text-[11px] text-muted-foreground flex-shrink-0">
                {profile.stats?.uploaded_bytes
                  ? `${formatBytesStored(profile.stats.uploaded_bytes)} stored`
                  : "0 bytes stored"}
              </span>
            </div>
          ))}
          <p className="text-[11px] text-muted-foreground">
            Usage reflects recordings confirmed uploaded to each FTP server; FTP capacity is not queried.
          </p>
        </div>
      )}

      <CopyableEnvBlock docker={Boolean(status?.docker)} />

      <div className="border-t border-border pt-3">
        <StorageLocationForm showCurrent={false} />
      </div>

      <div className="border-t border-border pt-3">
        <ArchiveCard />
      </div>

      <p className="text-[11px] text-muted-foreground">
        How long footage stays on this machine is set per camera (Retention
        in each camera&apos;s settings), and a camera can record to its own
        folder, FTP server or S3 bucket (Recordings location in camera
        settings). Recordings already written stay where they are when
        locations change.
      </p>
    </div>
  );
}

function formatBytesStored(bytes: number): string {
  if (bytes < 1024 ** 2) return `${Math.max(0, bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

export function StorageLowSpaceBanner() {
  // Dashboard mirror of the storage warnings (#274): the settings card is
  // collapsed by default, so low disk / unwritable roots must surface on
  // the monitoring view. Admin-only; quiet 60s poll.
  const { user } = useAuth();
  const { overview } = useStorageOverview(user?.role === "admin", 60_000);

  if (user?.role !== "admin" || !overview?.low_space) return null;
  const rec = overview.locations.find((l) => l.key === "recordings");
  return (
    <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 flex items-start justify-between gap-3">
      <div className="text-xs text-red-400">
        <span className="font-medium">Low disk space. </span>
        {rec?.free_bytes != null
          ? `Only ${formatBytes(rec.free_bytes)} at ${rec.path}. `
          : ""}
        {overview.warnings[0] ?? ""}
      </div>
      <Link
        href="/settings#storage"
        className="text-xs text-red-300 hover:text-red-200 underline whitespace-nowrap"
      >
        Review storage
      </Link>
    </div>
  );
}

export function StorageLocationCard() {
  // Location endpoints are admin-only (issue #279): non-admins get a clear
  // note instead of an endless loading state. Usage bars in the parent card
  // remain visible to everyone (GET /api/storage is not admin-only).
  const { user } = useAuth();
  if (user?.role !== "admin") {
    return (
      <p className="text-xs text-muted-foreground">
        Only admins can change the storage location.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <div>
        <div className="text-sm font-medium mb-1">Recordings location</div>
        <p className="text-xs text-muted-foreground">
          The drives and folders Nurby writes media to.
        </p>
      </div>
      <StorageOverviewBlock />
    </div>
  );
}
