"use client";

import { useCallback, useEffect, useState } from "react";
import { Locale, translate } from "@/lib/i18n";
import { formatDateTime, getDisplayLocale } from "@/lib/time";

type Lifecycle = {
  id: string;
  state: "delivered" | "waiting" | "gone";
  started_at: string;
  last_present_at: string | null;
  gone_at: string | null;
  removal_kind: "picked_up_by_person" | "removed_unobserved" | null;
  absent_checks: number;
  last_observation_id: string | null;
  evidence: {
    present?: boolean;
    confidence?: number | null;
    observation_id?: string | null;
    remover_person_id?: string | null;
    last_present_observation_id?: string | null;
  } | null;
  updated_at: string | null;
};

type Props = {
  cameraId: string;
  token: string | null;
  authFetch: (url: string, init?: RequestInit) => Promise<Response>;
  locale?: Locale;
};

function stateCopy(item: Lifecycle, t: (key: string, values?: Record<string, string | number>) => string) {
  if (item.state === "delivered") return t("package.delivered");
  if (item.state === "waiting") return t("package.waiting");
  if (item.removal_kind === "picked_up_by_person") return t("package.picked_up");
  return t("package.gone");
}

export function PackageLifecycleCard({ cameraId, token, authFetch, locale: requestedLocale }: Props) {
  const locale = requestedLocale || (getDisplayLocale() as Locale) || "en";
  const t = (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
  const [items, setItems] = useState<Lifecycle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const load = useCallback(async () => {
    try {
      const response = await authFetch(`/api/cameras/${cameraId}/package-lifecycle`);
      if (!response.ok) throw new Error("Unable to load package history");
      const data = await response.json();
      setItems(Array.isArray(data.items) ? data.items : []);
      setError(null);
    } catch {
      setError("Package status is temporarily unavailable.");
    } finally {
      setLoading(false);
    }
  }, [authFetch, cameraId]);

  useEffect(() => { void load(); }, [load]);

  const current = items[0];
  const evidenceObservationId = (item: Lifecycle) =>
    item.last_observation_id || item.evidence?.observation_id || null;
  const evidenceHref = (observationId: string) =>
    `/api/observations/${observationId}/thumbnail${token ? `?token=${encodeURIComponent(token)}` : ""}`;
  const recordingsHref = (item: Lifecycle) => {
    const start = new Date(item.started_at).getTime() - 2 * 60 * 1000;
    const endSource = item.gone_at || item.last_present_at || item.updated_at || item.started_at;
    const end = new Date(endSource).getTime() + 2 * 60 * 1000;
    return `/recordings?camera_id=${encodeURIComponent(cameraId)}&from=${encodeURIComponent(new Date(start).toISOString())}&to=${encodeURIComponent(new Date(end).toISOString())}`;
  };
  const evidenceLabel = (item: Lifecycle) => {
    if (item.state !== "gone") return item.last_present_at ? t("package.last_presence_frame") : t("package.delivery_frame");
    if (item.removal_kind === "picked_up_by_person") return t("package.pickup_frame");
    return t("package.removal_frame");
  };
  const evidenceLinks = (item: Lifecycle) => {
    const currentId = evidenceObservationId(item);
    const beforeId = item.state === "gone" ? item.evidence?.last_present_observation_id : null;
    const links: { id: string; label: string }[] = [];
    if (beforeId && beforeId !== currentId) links.push({ id: beforeId, label: "Before disappearance" });
    if (currentId) links.push({ id: currentId, label: evidenceLabel(item) });
    return links;
  };
  return (
    <section className="rounded-lg border border-border bg-card px-4 py-3.5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-medium">{t("package.activity")}</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("package.help")}
          </p>
        </div>
        {current && (
          <span className={`rounded-full px-2 py-1 text-[11px] ${current.state === "gone" && current.removal_kind !== "picked_up_by_person" ? "bg-amber-500/15 text-amber-400" : "bg-emerald-500/15 text-emerald-400"}`}>
            {stateCopy(current, t)}
          </span>
        )}
      </div>
      {loading ? (
        <div className="mt-3 text-xs text-muted-foreground">{t("package.loading")}</div>
      ) : error ? (
        <div className="mt-3 text-xs text-amber-400">{t("package.unavailable")}</div>
      ) : !current ? (
        <div className="mt-3 rounded-md border border-dashed border-border px-3 py-3 text-xs text-muted-foreground">
          {t("package.empty")}
        </div>
      ) : (
        <div className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
          <div><span className="block text-[11px] uppercase tracking-wide">{t("package.started")}</span>{formatDateTime(current.started_at)}</div>
          <div><span className="block text-[11px] uppercase tracking-wide">{t("package.last_seen")}</span>{current.last_present_at ? formatDateTime(current.last_present_at) : "—"}</div>
          <div>
            <span className="block text-[11px] uppercase tracking-wide">{t("package.evidence")}</span>
            {evidenceLinks(current).length ? (
              <span className="flex flex-col items-start gap-1">
                {evidenceLinks(current).map((link) => (
                  <a
                    key={link.id}
                    className="text-foreground underline decoration-border underline-offset-2 hover:decoration-foreground"
                    href={evidenceHref(link.id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {link.label}
                  </a>
                ))}
              </span>
            ) : t("package.pending")}
            <a
              className="mt-1 inline-block text-muted-foreground underline decoration-border underline-offset-2 hover:text-foreground"
              href={recordingsHref(current)}
            >
              {t("package.recording_context")}
            </a>
          </div>
        </div>
      )}
      {items.length > 1 && !loading && !error && (
        <div className="mt-4 border-t border-border pt-3">
          <button
            type="button"
            className="text-xs text-muted-foreground underline decoration-border underline-offset-2 hover:text-foreground"
            onClick={() => setShowHistory((open) => !open)}
            aria-expanded={showHistory}
          >
            {showHistory ? t("package.hide_history") : t("package.show_history", { count: items.length - 1 })}
          </button>
          {showHistory && (
            <ol className="mt-3 space-y-2">
              {items.slice(1).map((item) => {
                const observationId = evidenceObservationId(item);
                return (
                  <li key={item.id} className="flex items-center justify-between gap-3 rounded-md border border-border/70 px-3 py-2 text-xs">
                    <div>
                      <div className="text-foreground">{stateCopy(item, t)}</div>
                      <div className="text-muted-foreground">{formatDateTime(item.started_at)}</div>
                    </div>
                    {observationId && (
                      <span className="flex shrink-0 flex-col items-end gap-1">
                        <a
                          className="text-muted-foreground underline decoration-border underline-offset-2 hover:text-foreground"
                          href={evidenceHref(observationId)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {t("package.view_evidence")}
                        </a>
                        <a
                          className="text-muted-foreground underline decoration-border underline-offset-2 hover:text-foreground"
                          href={recordingsHref(item)}
                        >
                          {t("package.recording_context")}
                        </a>
                      </span>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      )}
    </section>
  );
}
