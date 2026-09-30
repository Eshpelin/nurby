"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

type BackupStatus = { last_success_at: string | null; archive: string | null; backup_path?: string };

export function BackupCard() {
  const { authFetch, user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [passphrase, setPassphrase] = useState("");
  const [includeRecordings, setIncludeRecordings] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [messageOk, setMessageOk] = useState(false);

  const load = useCallback(async () => {
    const res = await authFetch("/api/system/backup/status");
    if (res.ok) setStatus(await res.json());
  }, [authFetch]);
  useEffect(() => { void load(); }, [load]);

  const run = async () => {
    if (passphrase.length < 8) {
      setMessageOk(false);
      setMessage(t("backup.passphrase_short"));
      return;
    }
    setBusy(true);
    setMessage(null);
    setMessageOk(false);
    try {
      const res = await authFetch("/api/system/backup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passphrase, include_recordings: includeRecordings }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `Backup failed (${res.status})`);
      setMessageOk(true);
      setMessage(t("backup.created", { archive: body.archive }));
      setPassphrase("");
      await load();
    } catch (error) {
      setMessageOk(false);
      setMessage(error instanceof Error ? error.message : t("backup.failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div id="backups" className="rounded-lg border border-border bg-card scroll-mt-20">
      <div className="px-4 py-3.5 border-b border-border">
        <div className="text-sm font-medium">{t("backup.title")}</div>
        <div className="text-xs text-muted-foreground mt-0.5">{t("backup.subtitle")}</div>
      </div>
      <div className="px-4 py-4 space-y-3">
        <div className="text-xs text-muted-foreground">
          {status?.last_success_at
            ? <>{t("backup.last_success")}: <span className="text-foreground">{new Date(status.last_success_at).toLocaleString(user?.locale || undefined)}</span></>
            : t("backup.none_yet")}
          {status?.backup_path && <span> · {t("backup.stored_in")} {status.backup_path}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            aria-label={t("backup.passphrase")}
            type="password"
            value={passphrase}
            onChange={(event) => setPassphrase(event.target.value)}
            placeholder={t("backup.passphrase_placeholder")}
            className="min-w-[230px] flex-1 px-3 py-2 text-sm rounded-md border border-border bg-background"
          />
          <button type="button" onClick={run} disabled={busy} className="px-3 py-2 text-sm rounded-md bg-foreground text-background font-medium disabled:opacity-50">
            {busy ? t("backup.in_progress") : t("backup.back_up_now")}
          </button>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input type="checkbox" checked={includeRecordings} onChange={(event) => setIncludeRecordings(event.target.checked)} />
          {t("backup.include_recordings")}
        </label>
        {message && <p className={`text-xs ${messageOk ? "text-emerald-400" : "text-red-400"}`}>{message}</p>}
        <p className="text-[11px] text-muted-foreground">{t("backup.restore_help")} <code>docs/operations/backups.md</code>.</p>
      </div>
    </div>
  );
}

export default BackupCard;
