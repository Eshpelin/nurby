"use client";

// Media storage location (issue #251). Shared form used by the first-run
// onboarding wizard (the "where do recordings live?" moment) and the
// Settings page. Validates a directory server-side (exists / writable /
// free space) before saving the storage_recordings_dir override; the
// backend applies it process-wide for NEW recordings.

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

interface StorageStatus {
  recordings_path: string;
  source: "default" | "custom";
  docker: boolean;
  free_bytes: number | null;
}

interface StorageValidation {
  ok: boolean;
  path: string;
  created: boolean;
  writable: boolean;
  free_bytes: number | null;
  detail: string;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "unknown";
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB free`;
  const mb = bytes / 1024 ** 2;
  return `${Math.max(0, mb).toFixed(0)} MB free`;
}

export function StorageLocationForm({
  onSaved,
  compact = false,
}: {
  onSaved?: () => void;
  compact?: boolean;
}) {
  const { authFetch } = useAuth();
  const [status, setStatus] = useState<StorageStatus | null>(null);
  const [path, setPath] = useState("");
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validation, setValidation] = useState<StorageValidation | null>(null);
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/system/storage");
      if (res.ok) {
        const d: StorageStatus = await res.json();
        setStatus(d);
        setPath((p) => p || d.recordings_path);
      }
    } catch {
      /* ignore */
    }
  }, [authFetch]);

  useEffect(() => {
    load();
  }, [load]);

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
          load();
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
    [authFetch, load, onSaved],
  );

  const saveInput = useCallback(async () => {
    const candidate = path.trim();
    const result = validation?.path === candidate ? validation : await validate(candidate);
    if (result?.ok) await save(candidate);
  }, [path, save, validate, validation]);

  const resetToDefault = useCallback(async () => {
    if (await save(null)) {
      setValidation(null);
      if (status) setPath(status.recordings_path);
    }
  }, [save, status]);

  return (
    <div className="space-y-2.5">
      <div>
        <label
          htmlFor="storage-recordings-dir"
          className="text-sm font-medium text-foreground"
        >
          Where should recordings be stored?
        </label>
        {!compact && (
          <p className="text-xs text-muted-foreground mt-0.5">
            New recordings, clips, and their caches land here. Existing files
            stay in the previous location — pick this before adding cameras.
          </p>
        )}
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

      {status && (
        <p className="text-[11px] text-muted-foreground">
          Current: <code className="bg-background px-1 rounded">{status.recordings_path}</code>
          {" · "}
          {formatBytes(status.free_bytes)}
          {status.source === "custom" ? " · custom location" : ""}
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
          disabled={saving || checking || (!dirty && status?.source !== "custom")}
          onClick={saveInput}
          className="px-3 py-1.5 text-xs rounded-md bg-accent text-black font-medium hover:bg-accent/90 transition-colors disabled:opacity-50"
        >
          {saving ? "Saving…" : "Use this location"}
        </button>
        {status?.source === "custom" && (
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

export function StorageLocationCard() {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3.5 space-y-3">
      <div>
        <div className="text-sm font-medium mb-1">Storage location</div>
        <p className="text-xs text-muted-foreground">
          Choose the drive and folder where Nurby keeps recordings.
        </p>
      </div>
      <StorageLocationForm compact />
    </div>
  );
}
