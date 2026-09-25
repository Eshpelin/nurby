// Per-camera storage location (issues #251/#269/#270). Lets one camera
// record under a different root: a local folder on another drive, or a
// native FTP server or S3 bucket (segments buffer locally first and upload
// via the ingestion worker; see docs/storage-architecture.md). The selected value lives in
// the camera page state so the SaveBar persists it with the rest of the
// settings; the profile list is fetched here.

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import {
  AddLocationForm,
  locationLabel,
  type StorageProfile,
} from "@/components/storage/AddLocationForm";
import { FieldRow, Section } from "./primitives";

function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 90) return "just now";
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

interface StorageSectionProps {
  storageProfileId: string | null;
  setStorageProfileId: (id: string | null) => void;
}

interface StorageLocationInfo {
  key: string;
  path: string;
}

export function StorageSection({
  storageProfileId,
  setStorageProfileId,
}: StorageSectionProps) {
  const { authFetch } = useAuth();
  const [profiles, setProfiles] = useState<StorageProfile[]>([]);
  const [globalRoot, setGlobalRoot] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  // The assignment the page hydrated with (#278): switching affects new
  // segments only, so say so while a changed (unsaved) choice is selected.
  const initialProfileRef = useRef<string | null>(storageProfileId);
  const locationChanged = storageProfileId !== initialProfileRef.current;

  // Stale assignment (issue #280): the assigned profile was deleted (the DB
  // already NULLed the camera via ON DELETE SET NULL) while this page held
  // the old id in state. Clear it so Save doesn't 400, and say why.
  const [staleNotice, setStaleNotice] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/storage-profiles");
      if (!res.ok) return; // non-admin: leave page state untouched
      const list: StorageProfile[] = await res.json();
      setProfiles(list);
      if (storageProfileId && !list.some((p) => p.id === storageProfileId)) {
        setStaleNotice(true);
        setStorageProfileId(null);
      }
    } catch {
      /* ignore */
    }
  }, [authFetch, storageProfileId, setStorageProfileId]);

  const loadGlobal = useCallback(async () => {
    // Where "Default" records to, so the choice is readable without shell
    // access (issue #266). Admin-only endpoint; camera settings are too.
    try {
      const res = await authFetch("/api/system/storage");
      if (res.ok) {
        const d = await res.json();
        const rec = (d.locations as StorageLocationInfo[]).find(
          (l) => l.key === "recordings"
        );
        setGlobalRoot(rec?.path ?? null);
      }
    } catch {
      /* ignore */
    }
  }, [authFetch]);

  useEffect(() => {
    load();
    loadGlobal();
  }, [load, loadGlobal]);

  const onCreated = (created: StorageProfile) => {
    setProfiles((p) => [...p, created].sort((a, b) => a.name.localeCompare(b.name)));
    setStorageProfileId(created.id);
    setAdding(false);
  };

  const remove = async (id: string) => {
    if (!window.confirm("Delete this location? Cameras using it fall back to the default.")) return;
    setBusy(true);
    try {
      const res = await authFetch(`/api/storage-profiles/${id}`, { method: "DELETE" });
      if (res.ok || res.status === 404) {
        setProfiles((p) => p.filter((x) => x.id !== id));
        if (storageProfileId === id) setStorageProfileId(null);
      } else {
        const d = await res.json().catch(() => null);
        window.alert(d?.detail || "Could not delete this location.");
      }
    } finally {
      setBusy(false);
    }
  };

  const selected = profiles.find((p) => p.id === storageProfileId);
  const remoteName = selected?.kind === "s3" ? "S3" : "FTP";

  return (
    <Section
      title="Recordings location"
      description="Where this camera's recordings are written. Default keeps them with everything else; FTP and S3 locations upload segments to your own server or bucket (buffered locally first, so an outage never loses footage). To move only older footage off this machine, use Archive in Settings, Storage."
    >
      <FieldRow label="Record to">
        <div className="min-w-0 flex-1">
          <select
            value={storageProfileId ?? ""}
            onChange={(e) => setStorageProfileId(e.target.value || null)}
            className="w-full max-w-full text-xs bg-background border border-border rounded px-2 py-1.5"
          >
            <option value="">
              {globalRoot ? `Default — ${globalRoot}` : "Default (global location)"}
            </option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {locationLabel(p)}
              </option>
            ))}
          </select>
        </div>
      </FieldRow>

      {staleNotice && (
        <p className="text-[11px] text-amber-300" role="status">
          The previously selected storage location was deleted. New recordings
          will use the default location unless you choose another one.
        </p>
      )}

      {locationChanged && (
        <p className="text-[11px] text-amber-300">
          Switching affects new segments only — recordings already written
          stay in the previous location and won&apos;t play until moved.{" "}
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

      {selected && (
        <p className="text-[11px] text-muted-foreground">
          {selected.kind === "ftp" || selected.kind === "s3"
            ? `New segments upload to ${remoteName} after they are written; until then they buffer in the default location. Recordings made before this change stay where they are.`
            : `New segments land under ${selected.root}. Recordings made before this change stay in the previous location.`}
        </p>
      )}

      {(selected?.kind === "ftp" || selected?.kind === "s3") && selected.stats && (selected.stats.pending > 0 || selected.stats.failed > 0 || selected.stats.uploaded > 0) && (
        <div className="text-[11px] text-muted-foreground flex items-center gap-3">
          <span>{selected.stats.uploaded} on {remoteName}</span>
          {selected.stats.pending > 0 && (
            <span className="text-amber-300">{selected.stats.pending} waiting to upload</span>
          )}
          {selected.stats.failed > 0 && (
            <span className="text-red-400">{selected.stats.failed} failed — kept locally</span>
          )}
          {selected.stats.last_upload_at && <span>last upload {ago(selected.stats.last_upload_at)}</span>}
        </div>
      )}

      <div className="space-y-2 pt-1">
        {!adding ? (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="text-[11px] text-accent hover:underline"
          >
            + New location
          </button>
        ) : (
          <AddLocationForm
            kinds={["local", "ftp", "s3"]}
            onCreated={onCreated}
            onCancel={() => setAdding(false)}
          />
        )}
      </div>

      {profiles.length > 0 && (
        <div className="space-y-1">
          {profiles.map((p) => (
            <div key={p.id} className="flex items-center justify-between text-[11px] text-muted-foreground">
              <span>
                {p.name}:{" "}
                <code className="bg-background px-1 rounded">{locationLabel(p)}</code>
              </span>
              <button
                type="button"
                disabled={busy}
                onClick={() => remove(p.id)}
                className="text-muted-foreground hover:text-red-400 disabled:opacity-50"
                aria-label={`Delete location ${p.name}`}
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}
