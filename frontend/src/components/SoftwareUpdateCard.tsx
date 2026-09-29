"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate, type Locale } from "@/lib/i18n";

interface VersionInfo {
  current: string;
  build: string;
  latest: string | null;
  release_url: string | null;
  update_available: boolean;
  self_update_enabled: boolean;
  repo: string;
  error: string | null;
}

// Shows the running version, checks GitHub for a newer release, and
// offers an update path. One-click when the optional updater sidecar is
// enabled, otherwise the manual command.
export function SoftwareUpdateCard() {
  const { authFetch, user } = useAuth();
  const locale = (user?.locale as Locale) || "en";
  const t = (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [updateMsg, setUpdateMsg] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authFetch("/api/system/version");
      if (r.ok) setInfo(await r.json());
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    load();
  }, [load]);

  const triggerUpdate = async () => {
    setUpdating(true);
    setUpdateMsg("");
    try {
      const r = await authFetch("/api/system/update", { method: "POST" });
      if (r.status === 403) {
        setUpdateMsg(t("software_update.admin_required"));
        return;
      }
      const j = await r.json().catch(() => ({}));
      setUpdateMsg(j.message || t("software_update.requested"));
    } catch {
      setUpdateMsg(t("software_update.server_unreachable"));
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{t("software_update.title")}</h2>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            {loading
              ? t("software_update.checking")
              : info
              ? t("software_update.version", { version: info.current, build: info.build ? ` (${info.build.slice(0, 7)})` : "" })
              : t("software_update.version_unknown")}
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="text-[11px] px-2 py-1 rounded border border-border hover:bg-muted text-muted-foreground disabled:opacity-50"
        >
          {t("software_update.check_again")}
        </button>
      </div>

      {info && (
        <div className="mt-3 space-y-2">
          {info.error && (
            <div className="text-[11px] text-amber-300/90">{info.error}</div>
          )}

          {!info.error && !info.update_available && info.latest && (
            <div className="text-[11px] text-emerald-300/90">
              {t("software_update.latest")}
            </div>
          )}

          {info.update_available && (
            <div className="rounded-md border border-accent/30 bg-accent/5 px-3 py-2.5 space-y-2">
              <div className="text-xs">
                <span className="font-medium text-accent">{t("software_update.available")}</span>{" "}
                {info.current} {"->"} {info.latest}
                {info.release_url && (
                  <>
                    {" . "}
                    <a
                      href={info.release_url}
                      target="_blank"
                      rel="noreferrer"
                      className="underline text-accent"
                    >
                      {t("software_update.release_notes")}
                    </a>
                  </>
                )}
              </div>

              {info.self_update_enabled ? (
                <button
                  type="button"
                  onClick={triggerUpdate}
                  disabled={updating}
                  className="px-3 py-1.5 text-xs rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50"
                >
                  {updating ? t("software_update.starting") : t("software_update.update_now")}
                </button>
              ) : (
                <div className="text-[11px] text-muted-foreground">
                  {t("software_update.manual_prefix")}
                  <pre className="mt-1 px-2 py-1.5 rounded bg-background border border-border font-mono text-[11px] overflow-x-auto">
                    ./scripts/update.sh
                  </pre>
                  {t("software_update.manual_suffix")}
                </div>
              )}

              {updateMsg && (
                <div className="text-[11px] text-muted-foreground">{updateMsg}</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default SoftwareUpdateCard;
