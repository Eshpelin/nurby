"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

type BackupStatus = { last_success_at: string | null; archive: string | null; backup_path?: string };

export function BackupCard() {
  const { authFetch } = useAuth();
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [passphrase, setPassphrase] = useState("");
  const [includeRecordings, setIncludeRecordings] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await authFetch("/api/system/backup/status");
    if (res.ok) setStatus(await res.json());
  }, [authFetch]);
  useEffect(() => { void load(); }, [load]);

  const run = async () => {
    if (passphrase.length < 8) {
      setMessage("Use a passphrase of at least 8 characters.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const res = await authFetch("/api/system/backup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passphrase, include_recordings: includeRecordings }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `Backup failed (${res.status})`);
      setMessage(`Backup created: ${body.archive}`);
      setPassphrase("");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Backup failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div id="backups" className="rounded-lg border border-border bg-card scroll-mt-20">
      <div className="px-4 py-3.5 border-b border-border">
        <div className="text-sm font-medium">Backups</div>
        <div className="text-xs text-muted-foreground mt-0.5">Protect cameras, people, rules, settings, embeddings, and history.</div>
      </div>
      <div className="px-4 py-4 space-y-3">
        <div className="text-xs text-muted-foreground">
          {status?.last_success_at
            ? <>Last successful backup: <span className="text-foreground">{new Date(status.last_success_at).toLocaleString()}</span></>
            : "No successful backup yet."}
          {status?.backup_path && <span> · stored in {status.backup_path}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            aria-label="Backup passphrase"
            type="password"
            value={passphrase}
            onChange={(event) => setPassphrase(event.target.value)}
            placeholder="Passphrase (8+ characters)"
            className="min-w-[230px] flex-1 px-3 py-2 text-sm rounded-md border border-border bg-background"
          />
          <button type="button" onClick={run} disabled={busy} className="px-3 py-2 text-sm rounded-md bg-foreground text-background font-medium disabled:opacity-50">
            {busy ? "Backing up…" : "Back up now"}
          </button>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input type="checkbox" checked={includeRecordings} onChange={(event) => setIncludeRecordings(event.target.checked)} />
          Include recordings (can be very large)
        </label>
        {message && <p className={`text-xs ${message.startsWith("Backup created") ? "text-emerald-400" : "text-red-400"}`}>{message}</p>}
        <p className="text-[11px] text-muted-foreground">Restore is a documented command-line operation because it replaces the installation. See <code>docs/operations/backups.md</code>.</p>
      </div>
    </div>
  );
}

export default BackupCard;
