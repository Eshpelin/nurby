"use client";

/**
 * Scheduled reports. Saved Ask-Nurby questions on a clock: "what was
 * Simon doing all day, every night at 7 PM", delivered in-app and by
 * email. Distinct from the morning digest (one fixed household recap):
 * each report is any question, optionally focused on one person.
 */

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useToast, useConfirm } from "@/lib/feedback";
import { EmptyState } from "@/components/EmptyState";
import { timeAgo, formatWith } from "@/lib/time";
import { translate } from "@/lib/i18n";

interface PersonOption {
  id: string;
  display_name: string;
  nickname?: string | null;
}

interface TelegramChannelOption {
  id: string;
  label: string;
  pairing_status: string;
}

interface ScheduledReport {
  id: string;
  name: string;
  prompt: string;
  person_id: string | null;
  hour: number;
  minute: number;
  days: string[] | null;
  delivery: { notify?: boolean; email?: string; telegram_channel_id?: string; webhook?: string } | null;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
  last_output: string | null;
  created_at: string;
}

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

function fmtTime(hour: number, minute: number): string {
  const d = new Date();
  d.setHours(hour, minute, 0, 0);
  return formatWith(d, { hour: "numeric", minute: "2-digit" });
}

export default function ReportsPage() {
  const { authFetch, user } = useAuth();
  const t = useCallback((key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values), [user?.locale]);
  const toast = useToast();
  const confirm = useConfirm();
  const [reports, setReports] = useState<ScheduledReport[]>([]);
  const [persons, setPersons] = useState<PersonOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Form state.
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [personId, setPersonId] = useState("");
  const [time, setTime] = useState("19:00");
  const [days, setDays] = useState<string[]>([]);
  const [email, setEmail] = useState("");
  const [tgChannels, setTgChannels] = useState<TelegramChannelOption[]>([]);
  const [tgChannelId, setTgChannelId] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/reports");
      if (!res.ok) throw new Error(`${t("reports.load_failed")} (${res.status})`);
      setReports(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : t("reports.load_failed"));
    } finally {
      setLoading(false);
    }
  }, [authFetch, t]);

  useEffect(() => {
    load();
    (async () => {
      try {
        const res = await authFetch("/api/persons");
        if (res.ok) setPersons(await res.json());
      } catch {
        /* person picker degrades to none */
      }
      try {
        const res = await authFetch("/api/telegram/channels");
        if (res.ok) {
          const list: TelegramChannelOption[] = await res.json();
          setTgChannels(list.filter((c) => c.pairing_status === "paired"));
        }
      } catch {
        /* telegram picker degrades to none */
      }
    })();
  }, [authFetch, load]);

  const create = useCallback(async () => {
    if (!name.trim() || !prompt.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const [h, m] = time.split(":").map((v) => parseInt(v, 10));
      const res = await authFetch("/api/reports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          prompt: prompt.trim(),
          person_id: personId || null,
          hour: h,
          minute: m,
          days: days.length > 0 && days.length < 7 ? days : null,
          delivery: {
            notify: true,
            email: email.trim() || null,
            telegram_channel_id: tgChannelId || null,
            webhook: webhookUrl.trim() || null,
          },
        }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => null);
        throw new Error(j?.detail || `${t("reports.create_failed")} (${res.status})`);
      }
      setName("");
      setPrompt("");
      setPersonId("");
      setEmail("");
      setTgChannelId("");
      setWebhookUrl("");
      setDays([]);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("reports.create_failed"));
    } finally {
      setSaving(false);
    }
  }, [authFetch, name, prompt, personId, time, days, email, tgChannelId, webhookUrl, load, t]);

  const runNow = useCallback(
    async (id: string) => {
      setRunningId(id);
      setError(null);
      try {
        const res = await authFetch(`/api/reports/${id}/run`, { method: "POST" });
        if (!res.ok) {
          const j = await res.json().catch(() => null);
          throw new Error(j?.detail || `${t("reports.run_failed")} (${res.status})`);
        }
        const updated: ScheduledReport = await res.json();
        setReports((prev) => prev.map((r) => (r.id === id ? updated : r)));
        setExpandedId(id);
      } catch (e) {
        setError(e instanceof Error ? e.message : t("reports.run_failed"));
      } finally {
        setRunningId(null);
      }
    },
    [authFetch, t]
  );

  const toggleEnabled = useCallback(
    async (r: ScheduledReport) => {
      try {
        const res = await authFetch(`/api/reports/${r.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: !r.enabled }),
        });
        if (res.ok) {
          const updated: ScheduledReport = await res.json();
          setReports((prev) => prev.map((x) => (x.id === r.id ? updated : x)));
        }
      } catch {
        /* row stays as-is */
      }
    },
    [authFetch]
  );

  const remove = useCallback(
    async (id: string) => {
      const report = reports.find((r) => r.id === id);
      const ok = await confirm({
        title: t("reports.delete_confirm_title", { suffix: report ? t("reports.delete_confirm_suffix", { name: report.name }) : "" }),
        body: t("reports.delete_confirm_body"),
        danger: true,
      });
      if (!ok) return;
      try {
        const res = await authFetch(`/api/reports/${id}`, { method: "DELETE" });
        if (res.ok || res.status === 204) {
          setReports((prev) => prev.filter((r) => r.id !== id));
          toast.success(t("reports.deleted"));
        } else {
          toast.error(t("reports.delete_failed"));
        }
      } catch {
        toast.error(t("reports.delete_failed"));
      }
    },
    [authFetch, reports, confirm, toast, t]
  );

  const inputClass =
    "w-full px-3 py-2 text-sm rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-accent";

  return (
    <div className="max-w-4xl mx-auto p-6">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("reports.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {t("reports.help")}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90"
        >
          {showForm ? t("reports.close") : t("reports.new")}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {showForm && (
        <div className="mb-6 rounded-lg border border-border bg-card p-5 space-y-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">{t("reports.name")}</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("reports.name_placeholder")}
              className={inputClass}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">{t("reports.question")}</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={t("reports.question_placeholder")}
              rows={2}
              className={inputClass}
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-muted-foreground block mb-1">
                {t("reports.focus")}
              </label>
              <select
                value={personId}
                onChange={(e) => setPersonId(e.target.value)}
                className={inputClass}
              >
                <option value="">{t("reports.household")}</option>
                {persons.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.nickname || p.display_name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">{t("reports.deliver_at")}</label>
              <input
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                className={inputClass}
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">
                {t("reports.email")}
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className={inputClass}
              />
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground block mb-1">
                {t("reports.telegram")}
              </label>
              <select
                value={tgChannelId}
                onChange={(e) => setTgChannelId(e.target.value)}
                className={inputClass}
              >
                <option value="">{t("reports.no_telegram")}</option>
                {tgChannels.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
              {tgChannels.length === 0 && (
                <p className="text-[11px] text-muted-foreground mt-1">
                  {t("reports.telegram_help")}
                </p>
              )}
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">
                {t("reports.webhook")}
              </label>
              <input
                type="url"
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
                placeholder="https://n8n.local/webhook/nightly-report"
                className={inputClass}
              />
              <p className="text-[11px] text-muted-foreground mt-1">
                {t("reports.webhook_help")}
              </p>
            </div>
          </div>
                    <div>
            <label className="text-xs text-muted-foreground block mb-1">
              {t("reports.days")}
            </label>
            <div className="flex gap-1.5 flex-wrap">
              {DAYS.map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() =>
                    setDays((prev) =>
                      prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]
                    )
                  }
                  className={`px-2.5 py-1 text-xs rounded-md border capitalize transition-colors ${
                    days.includes(d)
                      ? "border-accent bg-accent/10 text-foreground"
                      : "border-border text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {d}
                </button>
              ))}
            </div>
          </div>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={create}
              disabled={saving || !name.trim() || !prompt.trim()}
              className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50"
            >
              {saving ? t("reports.saving") : t("reports.create")}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground py-12 text-center">{t("reports.loading")}</p>
      ) : reports.length === 0 && !showForm ? (
        <EmptyState
          title={t("reports.empty_title")}
          body={t("reports.empty_body")}
          actionLabel={t("reports.new")}
          onAction={() => setShowForm(true)}
        />
      ) : (
        <div className="space-y-2">
          {reports.map((r) => {
            const expanded = expandedId === r.id;
            return (
              <div key={r.id} className="rounded-md border border-border bg-card p-4">
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      r.enabled ? "bg-green-500" : "bg-muted-foreground/40"
                    }`}
                  />
                  <span className="text-sm font-medium">{r.name}</span>
                  <span className="px-1.5 py-0.5 text-[10px] rounded bg-muted text-muted-foreground font-mono">
                    {fmtTime(r.hour, r.minute)}
                    {r.days && r.days.length > 0 && r.days.length < 7
                      ? ` · ${r.days.join(", ")}`
                      : ` · ${t("reports.daily")}`}
                  </span>
                  {r.delivery?.email && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-muted text-muted-foreground">
                      ✉ {r.delivery.email}
                    </span>
                  )}
                  {r.delivery?.telegram_channel_id && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-muted text-muted-foreground">
                      Telegram
                    </span>
                  )}
                  {r.delivery?.webhook && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-muted text-muted-foreground">
                      Webhook
                    </span>
                  )}
                  {r.last_status === "failed" && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-red-500/15 text-red-400 border border-red-500/30">
                      {t("reports.last_failed")}
                    </span>
                  )}
                  <div className="ml-auto flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => runNow(r.id)}
                      disabled={runningId === r.id}
                      className="px-2 py-1 text-[11px] rounded-md border border-border text-muted-foreground hover:text-foreground hover:border-muted-foreground/40 transition-colors disabled:opacity-50"
                      title={t("reports.run_now_help")}
                    >
                      {runningId === r.id ? t("reports.running") : t("reports.run_now")}
                    </button>
                    <button
                      type="button"
                      onClick={() => toggleEnabled(r)}
                      className="px-2 py-1 text-[11px] rounded-md border border-border text-muted-foreground hover:text-foreground hover:border-muted-foreground/40 transition-colors"
                    >
                      {r.enabled ? t("reports.pause") : t("reports.resume")}
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(r.id)}
                      className="px-2 py-1 text-[11px] rounded-md border border-border text-muted-foreground hover:text-red-400 hover:border-red-500/40 transition-colors"
                    >
                      {t("reports.delete")}
                    </button>
                  </div>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{r.prompt}</div>
                {r.last_output && (
                  <button
                    type="button"
                    onClick={() => setExpandedId(expanded ? null : r.id)}
                    className="mt-2 text-[11px] text-muted-foreground hover:text-foreground"
                  >
                    {expanded ? t("reports.hide_last") : t("reports.show_last", { time: timeAgo(r.last_run_at) })}
                  </button>
                )}
                {expanded && r.last_output && (
                  <div className="mt-2 rounded-md bg-muted/40 border border-border p-3 text-sm whitespace-pre-wrap">
                    {r.last_output}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
