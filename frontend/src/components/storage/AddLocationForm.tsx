// Shared "add a storage location" form (issues #251, #269, #270). Used by a
// camera's Recordings location section and by the Archive card in
// Settings, so a local folder, an FTP server and an S3 bucket are added the
// same way wherever the choice is offered. Every kind is checked before it
// can be saved: local folders are write-probed, FTP connects and logs in,
// S3 writes and deletes a tiny marker object.

import { useState } from "react";
import { useAuth } from "@/lib/auth";

export type LocationKind = "local" | "ftp" | "s3";

export interface StorageProfile {
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

/** How a profile reads in a dropdown or list. */
export function locationLabel(p: StorageProfile): string {
  if (p.kind === "ftp") return `ftp://${p.root}`;
  if (p.kind === "s3") {
    const bucket = (p.config?.bucket as string | undefined) ?? "bucket";
    const prefix = p.root && p.root !== "/" ? p.root : "";
    return `s3://${bucket}${prefix}`;
  }
  return p.root;
}

export const KIND_LABELS: Record<LocationKind, string> = {
  local: "Local folder",
  ftp: "FTP server",
  s3: "S3 bucket",
};

// Plain-language storage classes. Only AWS honours them; other providers
// store everything in their one class.
export const STORAGE_CLASSES = [
  { value: "STANDARD", label: "Standard", hint: "Instant playback. Highest storage price." },
  { value: "STANDARD_IA", label: "Infrequent Access", hint: "Instant playback. Cheaper to keep, small fee per view." },
  { value: "GLACIER_IR", label: "Glacier Instant Retrieval", hint: "Instant playback. About 80% cheaper than Standard. Best for an archive." },
  { value: "GLACIER", label: "Glacier Flexible Retrieval", hint: "Cheaper still. Playback needs a restore that takes 3 to 5 hours." },
  { value: "DEEP_ARCHIVE", label: "Glacier Deep Archive", hint: "Cheapest. Playback needs a restore that takes up to 12 hours." },
] as const;

type Provider = "aws" | "r2" | "b2" | "wasabi" | "other";

// `example` is only ever a placeholder: an endpoint is account- and
// region-specific, so nothing is prefilled that could be saved by accident.
const PROVIDERS: { value: Provider; label: string; example: string; region: string }[] = [
  { value: "aws", label: "Amazon S3", example: "", region: "us-east-1" },
  { value: "r2", label: "Cloudflare R2", example: "https://<account-id>.r2.cloudflarestorage.com", region: "auto" },
  { value: "b2", label: "Backblaze B2", example: "https://s3.us-west-004.backblazeb2.com", region: "us-west-004" },
  { value: "wasabi", label: "Wasabi", example: "https://s3.us-east-1.wasabisys.com", region: "us-east-1" },
  { value: "other", label: "MinIO or other", example: "https://minio.local:9000", region: "us-east-1" },
];

const inputCls = "text-xs bg-background border border-border rounded px-2 py-1.5";

interface AddLocationFormProps {
  kinds: LocationKind[];
  /** Storage class preselected for a new S3 bucket. */
  defaultStorageClass?: string;
  onCreated: (profile: StorageProfile) => void;
  onCancel: () => void;
}

export function AddLocationForm({
  kinds,
  defaultStorageClass = "STANDARD",
  onCreated,
  onCancel,
}: AddLocationFormProps) {
  const { authFetch } = useAuth();
  const [kind, setKind] = useState<LocationKind>(kinds[0]);
  const [name, setName] = useState("");
  const [root, setRoot] = useState("");
  // FTP
  const [host, setHost] = useState("");
  const [port, setPort] = useState("21");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [tls, setTls] = useState(false);
  const [passive, setPassive] = useState(true);
  // S3
  const [provider, setProvider] = useState<Provider>("aws");
  const [bucket, setBucket] = useState("");
  const [region, setRegion] = useState("us-east-1");
  const [endpoint, setEndpoint] = useState("");
  const [accessKey, setAccessKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [storageClass, setStorageClass] = useState(defaultStorageClass);

  const [msg, setMsg] = useState("");
  const [msgOk, setMsgOk] = useState(false);
  const [busy, setBusy] = useState(false);

  // Any edit invalidates a previous successful check.
  const dirty = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setMsg("");
    setMsgOk(false);
  };

  const remoteConfig = (): Record<string, unknown> =>
    kind === "ftp"
      ? { host: host.trim(), port: Number(port) || 21, username: username.trim(), password, tls, passive }
      : {
          bucket: bucket.trim(),
          region: region.trim(),
          endpoint_url: provider === "aws" ? "" : endpoint.trim(),
          access_key_id: accessKey.trim(),
          secret_access_key: secretKey,
          storage_class: provider === "aws" ? storageClass : "STANDARD",
        };

  const check = async () => {
    setMsg("Checking.");
    setMsgOk(false);
    setBusy(true);
    try {
      const res =
        kind === "local"
          ? await authFetch("/api/system/storage/validate", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ path: root.trim() }),
            })
          : await authFetch("/api/storage-profiles/validate-remote", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ kind, config: remoteConfig(), root: root.trim() || "/" }),
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
      const body: Record<string, unknown> = { name: name.trim(), kind, root: root.trim() || "/" };
      if (kind !== "local") body.config = remoteConfig();
      const res = await authFetch("/api/storage-profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        onCreated(await res.json());
      } else {
        const d = await res.json().catch(() => null);
        setMsg(d?.detail || "Could not create the location.");
        setMsgOk(false);
      }
    } finally {
      setBusy(false);
    }
  };

  const filled =
    kind === "local"
      ? Boolean(root.trim())
      : kind === "ftp"
        ? Boolean(host.trim())
        : Boolean(bucket.trim() && accessKey.trim() && secretKey && (provider === "aws" || endpoint.trim()));
  const canAdd = Boolean(name.trim()) && filled && msgOk;
  const selectedClass = STORAGE_CLASSES.find((c) => c.value === storageClass);

  return (
    <div className="rounded-md border border-border bg-muted/30 p-3 space-y-2">
      {kinds.length > 1 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] text-muted-foreground">Kind</span>
          {kinds.map((k) => (
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
              {KIND_LABELS[k]}
            </button>
          ))}
        </div>
      )}
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder={kind === "s3" ? "Name (e.g. Cloud archive)" : "Name (e.g. Basement NAS)"}
        aria-label="Location name"
        className={`w-44 ${inputCls}`}
      />

      {kind === "local" && (
        <input
          value={root}
          onChange={(e) => dirty(setRoot)(e.target.value)}
          placeholder="/mnt/recordings-b or D:\Nurby\recordings"
          aria-label="Folder path"
          className={`w-full font-mono ${inputCls}`}
        />
      )}

      {kind === "ftp" && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <input
              value={host}
              onChange={(e) => dirty(setHost)(e.target.value)}
              placeholder="ftp.example.com"
              aria-label="FTP host"
              className={`min-w-0 flex-1 font-mono ${inputCls}`}
            />
            <input
              value={port}
              onChange={(e) => dirty(setPort)(e.target.value.replace(/[^0-9]/g, ""))}
              className={`w-16 font-mono ${inputCls}`}
              title="Port"
              aria-label="FTP port"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              value={username}
              onChange={(e) => dirty(setUsername)(e.target.value)}
              placeholder="Username (or anonymous)"
              className={`min-w-0 flex-1 font-mono ${inputCls}`}
            />
            <input
              type="password"
              value={password}
              onChange={(e) => dirty(setPassword)(e.target.value)}
              placeholder="Password (optional)"
              className={`min-w-0 flex-1 font-mono ${inputCls}`}
            />
          </div>
          <input
            value={root}
            onChange={(e) => dirty(setRoot)(e.target.value)}
            placeholder="/nurby  (remote folder, created if missing)"
            className={`w-full font-mono ${inputCls}`}
          />
          <div className="flex items-center gap-4 text-[11px] text-muted-foreground">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={tls} onChange={(e) => dirty(setTls)(e.target.checked)} />
              FTPS (TLS)
            </label>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={passive} onChange={(e) => dirty(setPassive)(e.target.checked)} />
              Passive mode
            </label>
          </div>
        </div>
      )}

      {kind === "s3" && (
        <div className="space-y-2">
          <select
            value={provider}
            aria-label="S3 provider"
            onChange={(e) => {
              const p = PROVIDERS.find((x) => x.value === e.target.value)!;
              setProvider(p.value);
              setRegion(p.region);
              setEndpoint("");
              setMsg("");
              setMsgOk(false);
            }}
            className={`w-full ${inputCls}`}
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
          <div className="flex flex-wrap gap-2">
            <input
              value={bucket}
              onChange={(e) => dirty(setBucket)(e.target.value)}
              placeholder="Bucket name"
              aria-label="Bucket name"
              className={`min-w-0 flex-1 font-mono ${inputCls}`}
            />
            <input
              value={region}
              onChange={(e) => dirty(setRegion)(e.target.value)}
              placeholder="Region"
              aria-label="Region"
              className={`w-32 font-mono ${inputCls}`}
            />
          </div>
          {provider !== "aws" && (
            <input
              value={endpoint}
              onChange={(e) => dirty(setEndpoint)(e.target.value)}
              placeholder={PROVIDERS.find((p) => p.value === provider)?.example || "https://"}
              aria-label="Endpoint URL"
              className={`w-full font-mono ${inputCls}`}
            />
          )}
          <div className="flex flex-wrap gap-2">
            <input
              value={accessKey}
              onChange={(e) => dirty(setAccessKey)(e.target.value)}
              placeholder="Access key ID"
              aria-label="Access key ID"
              autoComplete="off"
              className={`min-w-0 flex-1 font-mono ${inputCls}`}
            />
            <input
              type="password"
              value={secretKey}
              onChange={(e) => dirty(setSecretKey)(e.target.value)}
              placeholder="Secret access key"
              aria-label="Secret access key"
              autoComplete="new-password"
              className={`min-w-0 flex-1 font-mono ${inputCls}`}
            />
          </div>
          <input
            value={root}
            onChange={(e) => dirty(setRoot)(e.target.value)}
            placeholder="Folder in the bucket (optional, e.g. nurby)"
            aria-label="Folder in the bucket"
            className={`w-full font-mono ${inputCls}`}
          />
          {provider === "aws" && (
            <div className="space-y-1">
              <select
                value={storageClass}
                aria-label="Storage class"
                onChange={(e) => setStorageClass(e.target.value)}
                className={`w-full ${inputCls}`}
              >
                {STORAGE_CLASSES.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
              {selectedClass && (
                <p className={`text-[10px] ${storageClass === "GLACIER" || storageClass === "DEEP_ARCHIVE" ? "text-amber-300" : "text-muted-foreground"}`}>
                  {selectedClass.hint}
                </p>
              )}
            </div>
          )}
          <p className="text-[10px] text-muted-foreground">
            The key needs permission to put, get and delete objects in this bucket. Keys are
            stored encrypted and never shown again.
          </p>
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={busy || !filled}
          onClick={check}
          className="px-2.5 py-1 text-[11px] rounded-md border border-border hover:bg-muted transition-colors disabled:opacity-50"
        >
          {busy ? "Checking." : kind === "local" ? "Check" : "Test connection"}
        </button>
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
          onClick={onCancel}
          className="text-[11px] text-muted-foreground hover:text-foreground"
        >
          Cancel
        </button>
      </div>
      {msg ? (
        <p className={`text-[11px] ${msgOk ? "text-emerald-400" : "text-red-400"}`} role="status">
          {msg}
        </p>
      ) : (
        filled && (
          <p className="text-[11px] text-muted-foreground">
            {kind === "local" ? "Check" : "Test the connection"} before adding the location.
          </p>
        )
      )}
    </div>
  );
}
