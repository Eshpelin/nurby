// Per-camera storage location (issue #251). Lets one camera record under
// a different root (a second drive, or a mount of an FTP/SMB/S3 remote)
// while everything else keeps the global location. The selected value
// lives in the camera page state so the SaveBar persists it with the rest
// of the settings; the profile list is fetched here.

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { FieldRow, Section } from "./primitives";

interface StorageProfile {
  id: string;
  name: string;
  kind: string;
  root: string;
  enabled: boolean;
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
  const [name, setName] = useState("");
  const [root, setRoot] = useState("");
  const [checkMsg, setCheckMsg] = useState("");
  const [checkOk, setCheckOk] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/storage-profiles");
      if (res.ok) setProfiles(await res.json());
    } catch {
      /* ignore */
    }
  }, [authFetch]);

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

  const check = async () => {
    setCheckMsg("");
    setCheckOk(false);
    if (!root.trim()) return;
    setBusy(true);
    try {
      const res = await authFetch("/api/system/storage/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: root.trim() }),
      });
      const d = await res.json();
      setCheckMsg(d.detail || (d.ok ? "Ready." : "Not usable."));
      setCheckOk(Boolean(d.ok));
    } catch {
      setCheckMsg("Check failed.");
    } finally {
      setBusy(false);
    }
  };

  const add = async () => {
    if (!name.trim() || !root.trim() || !checkOk) return;
    setBusy(true);
    try {
      const res = await authFetch("/api/storage-profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), root: root.trim() }),
      });
      if (res.ok) {
        const created = await res.json();
        setProfiles((p) => [...p, created].sort((a, b) => a.name.localeCompare(b.name)));
        setStorageProfileId(created.id);
        setAdding(false);
        setName("");
        setRoot("");
        setCheckMsg("");
        setCheckOk(false);
      } else {
        const d = await res.json().catch(() => null);
        setCheckMsg(d?.detail || "Could not create the location.");
        setCheckOk(false);
      }
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm("Delete this location? Cameras using it fall back to the default.")) return;
    setBusy(true);
    try {
      const res = await authFetch(`/api/storage-profiles/${id}`, { method: "DELETE" });
      if (res.ok || res.status === 404) {
        setProfiles((p) => p.filter((x) => x.id !== id));
        if (storageProfileId === id) setStorageProfileId(null);
      }
    } finally {
      setBusy(false);
    }
  };

  const selected = profiles.find((p) => p.id === storageProfileId);

  return (
    <Section
      title="Storage Location"
      description="Where this camera's recordings are written. Default keeps them with everything else; a custom location can be another drive or a mounted remote (FTP/SMB/S3 via mount)."
    >
      <FieldRow label="Record to">
        <select
          value={storageProfileId ?? ""}
          onChange={(e) => setStorageProfileId(e.target.value || null)}
          className="text-xs bg-background border border-border rounded px-2 py-1.5 min-w-52"
        >
          <option value="">
            {globalRoot ? `Default — ${globalRoot}` : "Default (global location)"}
          </option>
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} — {p.root}
            </option>
          ))}
        </select>
      </FieldRow>

      {selected && (
        <p className="text-[11px] text-muted-foreground">
          New segments land under <code className="bg-background px-1 rounded">{selected.root}</code>.
          Recordings made before this change stay in the previous location.
        </p>
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
          <div className="rounded-md border border-border bg-muted/30 p-3 space-y-2">
            <div className="flex gap-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Name (e.g. Second drive)"
                className="w-44 text-xs bg-background border border-border rounded px-2 py-1.5"
              />
              <input
                value={root}
                onChange={(e) => {
                  setRoot(e.target.value);
                  setCheckMsg("");
                  setCheckOk(false);
                }}
                placeholder="/mnt/recordings-b or D:\Nurby\recordings"
                className="flex-1 text-xs font-mono bg-background border border-border rounded px-2 py-1.5"
              />
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={busy || !name.trim() || !root.trim()}
                onClick={check}
                className="px-2.5 py-1 text-[11px] rounded-md border border-border hover:bg-muted transition-colors disabled:opacity-50"
              >
                {busy ? "Working…" : "Check"}
              </button>
              <button
                type="button"
                disabled={busy || !checkOk}
                onClick={add}
                className="px-2.5 py-1 text-[11px] rounded-md bg-accent text-black font-medium hover:bg-accent/90 transition-colors disabled:opacity-50"
              >
                Add location
              </button>
              <button
                type="button"
                onClick={() => {
                  setAdding(false);
                  setCheckMsg("");
                }}
                className="text-[11px] text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
            </div>
            {checkMsg && (
              <p className={`text-[11px] ${checkOk ? "text-emerald-400" : "text-red-400"}`}>
                {checkMsg}
              </p>
            )}
          </div>
        )}
      </div>

      {profiles.length > 0 && (
        <div className="space-y-1">
          {profiles.map((p) => (
            <div key={p.id} className="flex items-center justify-between text-[11px] text-muted-foreground">
              <span>
                {p.name}: <code className="bg-background px-1 rounded">{p.root}</code>
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
