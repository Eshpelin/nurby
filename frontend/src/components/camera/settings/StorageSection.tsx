// Per-camera storage location (issues #251/#269). Lets one camera record
// under a different root — a local folder on another drive, or a native
// FTP server (segments buffer locally first and upload via the ingestion
// worker; see docs/storage-architecture.md). The selected value lives in
// the camera page state so the SaveBar persists it with the rest of the
// settings; the profile list is fetched here.

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { FieldRow, Section } from "./primitives";

interface StorageProfile {
  id: string;
  name: string;
  kind: string;
  root: string;
  enabled: boolean;
  config?: Record<string, unknown> | null;
  has_password?: boolean;
  stats?: {
    pending: number;
    failed: number;
    uploaded: number;
    uploaded_bytes: number;
    last_upload_at: string | null;
  } | null;
}

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

const inputCls = "text-xs bg-background border border-border rounded px-2 py-1.5";

export function StorageSection({
  storageProfileId,
  setStorageProfileId,
}: StorageSectionProps) {
  const { authFetch } = useAuth();
  const [profiles, setProfiles] = useState<StorageProfile[]>([]);
  const [globalRoot, setGlobalRoot] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState<"local" | "ftp">("local");
  const [name, setName] = useState("");
  const [root, setRoot] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("21");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [tls, setTls] = useState(false);
  const [passive, setPassive] = useState(true);
  const [msg, setMsg] = useState("");
  const [msgOk, setMsgOk] = useState(false);
  const [busy, setBusy] = useState(false);
  // The assignment the page hydrated with (#278): switching affects new
  // segments only, so say so while a changed (unsaved) choice is selected.
  const initialProfileRef = useRef<string | null>(storageProfileId);
  const locationChanged = storageProfileId !== initialProfileRef.current;

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

  const resetForm = () => {
    setAdding(false);
    setName("");
    setRoot("");
    setHost("");
    setPort("21");
    setUsername("");
    setPassword("");
    setTls(false);
    setPassive(true);
    setMsg("");
    setMsgOk(false);
  };

  const testConnection = async () => {
    setMsg("Testing…");
    setMsgOk(false);
    setBusy(true);
    try {
      const res = await authFetch("/api/storage-profiles/validate-ftp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          config: {
            host: host.trim(),
            port: Number(port) || 21,
            username: username.trim(),
            password,
            tls,
            passive,
          },
          root: root.trim() || "/",
        }),
      });
      const d = await res.json();
      setMsg(d.detail || (d.ok ? "Connected." : "Connection failed."));
      setMsgOk(Boolean(d.ok));
    } catch {
      setMsg("Check failed.");
    } finally {
      setBusy(false);
    }
  };

  const checkLocal = async () => {
    setMsg("");
    setMsgOk(false);
    if (!root.trim()) return;
    setBusy(true);
    try {
      const res = await authFetch("/api/system/storage/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: root.trim() }),
      });
      const d = await res.json();
      setMsg(d.detail || (d.ok ? "Ready." : "Not usable."));
      setMsgOk(Boolean(d.ok));
    } catch {
      setMsg("Check failed.");
    } finally {
      setBusy(false);
    }
  };

  const add = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = { name: name.trim(), kind };
      if (kind === "local") {
        body.root = root.trim();
      } else {
        body.root = root.trim() || "/";
        body.config = {
          host: host.trim(),
          port: Number(port) || 21,
          username: username.trim(),
          password,
          tls,
          passive,
        };
      }
      const res = await authFetch("/api/storage-profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const created = await res.json();
        setProfiles((p) => [...p, created].sort((a, b) => a.name.localeCompare(b.name)));
        setStorageProfileId(created.id);
        resetForm();
      } else {
        const d = await res.json().catch(() => null);
        setMsg(d?.detail || "Could not create the location.");
        setMsgOk(false);
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
  const canAdd =
    kind === "local"
      ? Boolean(name.trim() && root.trim() && msgOk)
      : Boolean(name.trim() && host.trim() && msgOk);

  return (
    <Section
      title="Recordings location"
      description="Where this camera's recordings are written. Default keeps them with everything else; FTP locations upload segments to your own server (buffered locally first, so an outage never loses footage)."
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
              {p.name} — {p.kind === "ftp" ? `ftp://${p.root}` : p.root}
            </option>
          ))}
        </select>
      </FieldRow>

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
          {selected.kind === "ftp"
            ? "New segments upload to the FTP server after they are written; until then they buffer in the default location. Recordings made before this change stay where they are."
            : `New segments land under ${selected.root}. Recordings made before this change stay in the previous location.`}
        </p>
      )}

      {selected?.kind === "ftp" && selected.stats && (selected.stats.pending > 0 || selected.stats.failed > 0 || selected.stats.uploaded > 0) && (
        <div className="text-[11px] text-muted-foreground flex items-center gap-3">
          <span>{selected.stats.uploaded} on FTP</span>
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
          <div className="rounded-md border border-border bg-muted/30 p-3 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-muted-foreground">Kind</span>
              {(["local", "ftp"] as const).map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => {
                    setKind(k);
                    setMsg("");
                    setMsgOk(false);
                  }}
                  className={`px-2 py-1 text-[11px] rounded-md border transition-colors ${
                    kind === k ? "border-accent text-accent" : "border-border text-muted-foreground"
                  }`}
                >
                  {k === "local" ? "Local folder" : "FTP server"}
                </button>
              ))}
            </div>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name (e.g. Basement NAS)"
              className={`w-44 ${inputCls}`}
            />

            {kind === "local" ? (
              <input
                value={root}
                onChange={(e) => {
                  setRoot(e.target.value);
                  setMsg("");
                  setMsgOk(false);
                }}
                placeholder="/mnt/recordings-b or D:\Nurby\recordings"
                className={`w-full font-mono ${inputCls}`}
              />
            ) : (
              <div className="space-y-2">
                <div className="flex gap-2">
                  <input
                    value={host}
                    onChange={(e) => {
                      setHost(e.target.value);
                      setMsg("");
                      setMsgOk(false);
                    }}
                    placeholder="ftp.example.com"
                    className={`flex-1 font-mono ${inputCls}`}
                  />
                  <input
                    value={port}
                    onChange={(e) => setPort(e.target.value.replace(/[^0-9]/g, ""))}
                    className={`w-16 font-mono ${inputCls}`}
                    title="Port"
                  />
                </div>
                <div className="flex gap-2">
                  <input
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="Username (or anonymous)"
                    className={`flex-1 font-mono ${inputCls}`}
                  />
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Password (optional)"
                    className={`flex-1 font-mono ${inputCls}`}
                  />
                </div>
                <input
                  value={root}
                  onChange={(e) => {
                    setRoot(e.target.value);
                    setMsg("");
                    setMsgOk(false);
                  }}
                  placeholder="/nurby  (remote folder — created if missing)"
                  className={`w-full font-mono ${inputCls}`}
                />
                <div className="flex items-center gap-4 text-[11px] text-muted-foreground">
                  <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={tls} onChange={(e) => setTls(e.target.checked)} />
                    FTPS (TLS)
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={passive} onChange={(e) => setPassive(e.target.checked)} />
                    Passive mode
                  </label>
                </div>
                <p className="text-[10px] text-muted-foreground">
                  Segments upload after they are written and are removed from
                  the local buffer once the server confirms them.
                </p>
              </div>
            )}

            <div className="flex items-center gap-2">
              {kind === "ftp" && (
                <button
                  type="button"
                  disabled={busy || !host.trim()}
                  onClick={testConnection}
                  className="px-2.5 py-1 text-[11px] rounded-md border border-border hover:bg-muted transition-colors disabled:opacity-50"
                >
                  Test connection
                </button>
              )}
              {kind === "local" && (
                <button
                  type="button"
                  disabled={busy || !root.trim()}
                  onClick={checkLocal}
                  className="px-2.5 py-1 text-[11px] rounded-md border border-border hover:bg-muted transition-colors disabled:opacity-50"
                >
                  Check
                </button>
              )}
              <button
                type="button"
                disabled={busy || !canAdd}
                onClick={add}
                className="px-2.5 py-1 text-[11px] rounded-md bg-accent text-black font-medium hover:bg-accent/90 transition-colors disabled:opacity-50"
              >
                Add location
              </button>
              <button
                type="button"
                onClick={resetForm}
                className="text-[11px] text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
            </div>
            {msg && (
              <p className={`text-[11px] ${msgOk ? "text-emerald-400" : "text-red-400"}`}>
                {msg}
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
                {p.name}:{" "}
                <code className="bg-background px-1 rounded">
                  {p.kind === "ftp" ? `ftp://${p.root}` : p.root}
                </code>
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
