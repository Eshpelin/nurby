"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";
import { DependantAvatar } from "@/components/guardian-avatar";
import { GuardianNotifications } from "@/components/guardian-notifications";
import { GuardianTelegram } from "@/components/guardian-telegram";
import { Dependant, DependantStatus, stateColor, timeAgo } from "@/lib/guardian";

// The 10-second check. One calm status card per dependant. Most sessions end
// here. Free tier shows a "as of 30 min ago" note; nothing is invented.
export default function GuardianPage() {
  const { user, authFetch } = useAuth();
  const t = useCallback((key: string) => translate(user?.locale, key), [user?.locale]);
  const [dependants, setDependants] = useState<Dependant[]>([]);
  const [statuses, setStatuses] = useState<Record<string, DependantStatus>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/guardian/me");
      if (!res.ok) throw new Error(t("guardian.load_failed"));
      const data = await res.json();
      const deps: Dependant[] = data.dependants || [];
      setDependants(deps);
      // Pull a status for each active dependant.
      const entries = await Promise.all(
        deps
          .filter((d) => d.active)
          .map(async (d) => {
            try {
              const r = await authFetch(`/api/guardian/links/${d.link_id}/status`);
              if (!r.ok) return null;
              return [d.link_id, (await r.json()) as DependantStatus] as const;
            } catch {
              return null;
            }
          })
      );
      const map: Record<string, DependantStatus> = {};
      for (const e of entries) if (e) map[e[0]] = e[1];
      setStatuses(map);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("guardian.generic_error"));
    } finally {
      setLoading(false);
    }
  }, [authFetch, t]);

  useEffect(() => {
    load();
    // Poll only while the tab is visible. A backgrounded phone tab should
    // not burn data every 30s; refresh immediately on return instead.
    const t = setInterval(() => {
      if (!document.hidden) load();
    }, 30000);
    const onVisible = () => {
      if (!document.hidden) load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load]);

  if (loading) {
    return <div className="p-8 text-muted-foreground">{t("guardian.loading")}</div>;
  }

  return (
    <div className="max-w-3xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("guardian.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {t("guardian.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <GuardianNotifications />
          {user?.role === "admin" && (
            <Link
              href="/guardian/admin"
              className="px-3 py-1.5 rounded-md border border-border text-sm hover:bg-muted transition-colors"
            >
              {t("guardian.manage_access")}
            </Link>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-900/50 bg-red-950/30 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {dependants.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-8 text-center">
          <p className="text-muted-foreground">
            {t("guardian.empty")}
          </p>
          {user?.role === "admin" && (
            <p className="text-sm text-muted-foreground mt-2">
              Use{" "}
              <Link href="/guardian/admin" className="text-emerald-400 hover:underline">
                {t("guardian.manage_access")}
              </Link>{" "}
              to bind a guardian to a person.
            </p>
          )}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {dependants.map((d) => (
            <DependantCard key={d.link_id} dependant={d} status={statuses[d.link_id]} locale={user?.locale} />
          ))}
        </div>
      )}

      {dependants.length > 0 && (
        <div className="mt-6">
          <GuardianTelegram />
        </div>
      )}
    </div>
  );
}

function DependantCard({
  dependant,
  status,
  locale,
}: {
  dependant: Dependant;
  status?: DependantStatus;
  locale?: string;
}) {
  const t = (key: string) => translate(locale, key);
  if (!dependant.active) {
    return (
      <div className="rounded-lg border border-border bg-card p-5 opacity-60">
        <div className="font-medium">{dependant.display_name}</div>
        <div className="text-sm text-muted-foreground mt-1">{t("guardian.access_ended")}</div>
      </div>
    );
  }
  const st = status?.state || "unknown";
  const c = stateColor(st);
  return (
    <Link
      href={`/guardian/${dependant.link_id}`}
      className="block rounded-lg border border-border bg-card p-5 hover:border-zinc-600 transition-colors"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <DependantAvatar photoUrl={dependant.photo_url} name={dependant.display_name} size={40} />
          <div className="min-w-0">
            <div className="font-medium truncate">{dependant.display_name}</div>
            {dependant.relationship_label && (
              <div className="text-xs text-muted-foreground capitalize">
                {dependant.relationship_label}
              </div>
            )}
          </div>
        </div>
        <span className="flex items-center gap-1.5 text-xs shrink-0">
          <span className={`h-2 w-2 rounded-full ${c.dot}`} />
          <span className={c.text}>{t(`guardian.state_${st}`)}</span>
        </span>
      </div>
      <div className="mt-4 text-sm">
        {st === "unknown" ? (
          <span className="text-muted-foreground">{t("guardian.no_recent_sighting")}</span>
        ) : (
          <span>
            {status?.zone ? (
              <span className="text-foreground">{status.zone}</span>
            ) : (
              <span className="text-muted-foreground">{t("guardian.location_unknown")}</span>
            )}
            <span className="text-muted-foreground">
              {" "}· {t("guardian.seen")} {timeAgo(status?.last_seen_at || null)}
            </span>
          </span>
        )}
      </div>
      {status?.delayed && (
        <div className="mt-3 text-[11px] text-amber-400/80">
          {t("guardian.delayed_presence")}
        </div>
      )}
    </Link>
  );
}
