"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

type SpendRow = { name: string; cost_cents: number; calls: number; tokens_in: number; tokens_out: number };
type UsageReport = {
  days: number;
  estimated: boolean;
  pricing_note: string;
  totals: SpendRow;
  by_camera: SpendRow[];
  by_provider: SpendRow[];
  by_workload: SpendRow[];
  by_rule: SpendRow[];
  attribution_note: string;
  perception_budget: {
    stage: "normal" | "warn" | "blocked";
    allowed: boolean;
    reason: string;
    used_cost_cents: number;
    used_tokens: number;
    cost_limit_cents: number;
    token_limit: number;
  };
};

function dollars(cents: number) {
  return `$${(cents / 100).toFixed(2)}`;
}

export function CostUsageCard() {
  const { authFetch, user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const [report, setReport] = useState<UsageReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [budget, setBudget] = useState({ cameraCents: 0, ruleCents: 0, cameraTokens: 0, ruleTokens: 0 });
  const [budgetSaving, setBudgetSaving] = useState(false);
  const [budgetSaved, setBudgetSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      authFetch("/api/agent/usage/report?days=7"),
      authFetch("/api/system/settings"),
    ])
      .then(async ([reportResponse, settingsResponse]) => {
        const nextReport = reportResponse.ok ? await reportResponse.json() as UsageReport : null;
        if (!cancelled) setReport(nextReport);
        if (settingsResponse.ok) {
          const settings = await settingsResponse.json();
          if (!cancelled) setBudget({
            cameraCents: Number(settings.perception_daily_cost_budget_cents || 0),
            ruleCents: Number(settings.perception_daily_cost_budget_cents_per_rule || 0),
            cameraTokens: Number(settings.perception_daily_token_budget || 0),
            ruleTokens: Number(settings.perception_daily_token_budget_per_rule || 0),
          });
        }
      })
      .catch(() => { if (!cancelled) setReport(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [authFetch]);

  const saveBudget = async () => {
    if (user?.role !== "admin" || budgetSaving) return;
    setBudgetSaving(true);
    try {
      const response = await authFetch("/api/system/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          perception_daily_cost_budget_cents: Math.max(0, budget.cameraCents),
          perception_daily_cost_budget_cents_per_rule: Math.max(0, budget.ruleCents),
          perception_daily_token_budget: Math.max(0, budget.cameraTokens),
          perception_daily_token_budget_per_rule: Math.max(0, budget.ruleTokens),
        }),
      });
      if (response.ok) {
        setBudgetSaved(true);
        window.setTimeout(() => setBudgetSaved(false), 1800);
      }
    } finally {
      setBudgetSaving(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="px-4 py-3.5 flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">{t("cost.ai_usage")}</div>
          <div className="text-xs text-muted-foreground mt-0.5">{t("cost.estimated_spend_7_days")}</div>
        </div>
        <span className="text-xs text-muted-foreground">{loading ? t("cost.loading") : report ? dollars(report.totals.cost_cents) : t("cost.unavailable")}</span>
      </div>
      {report && (
        <div className="border-t border-border px-4 py-3 space-y-3">
          {report.perception_budget.stage !== "normal" && (
            <div className={`rounded border px-3 py-2 text-xs ${report.perception_budget.stage === "blocked" ? "border-red-500/40 bg-red-500/10 text-red-200" : "border-amber-500/40 bg-amber-500/10 text-amber-200"}`}>
              <div className="font-medium">{t("cost.camera_budget", { stage: report.perception_budget.stage })}</div>
              <div className="mt-0.5">{report.perception_budget.reason || t("cost.budget_approaching")}</div>
            </div>
          )}
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div><div className="text-muted-foreground">{t("cost.calls")}</div><div className="font-medium">{report.totals.calls}</div></div>
            <div><div className="text-muted-foreground">{t("cost.input_tokens")}</div><div className="font-medium">{report.totals.tokens_in.toLocaleString()}</div></div>
            <div><div className="text-muted-foreground">{t("cost.output_tokens")}</div><div className="font-medium">{report.totals.tokens_out.toLocaleString()}</div></div>
          </div>
          {report.by_camera.length > 0 && (
            <div>
              <div className="text-xs font-medium mb-1">{t("cost.by_camera_workload")}</div>
              <div className="space-y-1">
                {report.by_camera.slice(0, 5).map((row) => (
                  <div key={row.name} className="flex justify-between text-xs text-muted-foreground"><span>{row.name}</span><span>{dollars(row.cost_cents)} · {row.calls} {t("cost.calls_lower")}</span></div>
                ))}
              </div>
            </div>
          )}
          {report.by_workload.length > 0 && (
            <div>
              <div className="text-xs font-medium mb-1">{t("cost.by_workload")}</div>
              <div className="space-y-1">
                {report.by_workload.slice(0, 6).map((row) => (
                  <div key={row.name} className="flex justify-between text-xs text-muted-foreground"><span>{row.name}</span><span>{dollars(row.cost_cents)} · {row.calls} {t("cost.calls_lower")}</span></div>
                ))}
              </div>
            </div>
          )}
          {report.by_rule.length > 0 && (
            <div>
              <div className="text-xs font-medium mb-1">{t("cost.by_rule")}</div>
              <div className="space-y-1">
                {report.by_rule.slice(0, 6).map((row) => (
                  <div key={row.name} className="flex justify-between text-xs text-muted-foreground"><span>{row.name}</span><span>{dollars(row.cost_cents)} · {row.calls} {t("cost.calls_lower")}</span></div>
                ))}
              </div>
            </div>
          )}
          {user?.role === "admin" && (
            <div className="border-t border-border pt-3 space-y-2">
              <div className="text-xs font-medium">{t("cost.guardrails")}</div>
              <p className="text-[11px] text-muted-foreground">{t("cost.guardrails_help")}</p>
              <div className="grid grid-cols-2 gap-2">
                {([
                  ["cameraCents", t("cost.camera_cents_day")],
                  ["ruleCents", t("cost.rule_cents_day")],
                  ["cameraTokens", t("cost.camera_tokens_day")],
                  ["ruleTokens", t("cost.rule_tokens_day")],
                ] as const).map(([key, label]) => (
                  <label key={key} className="text-[11px] text-muted-foreground">
                    {label}
                    <input
                      type="number"
                      min={0}
                      value={budget[key]}
                      onChange={(event) => setBudget((current) => ({ ...current, [key]: Number(event.target.value) || 0 }))}
                      className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-xs text-foreground"
                    />
                  </label>
                ))}
              </div>
              <button type="button" onClick={saveBudget} disabled={budgetSaving} className="rounded border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50">
                {budgetSaved ? t("cost.saved") : budgetSaving ? t("cost.saving") : t("cost.save_guardrails")}
              </button>
            </div>
          )}
          <p className="text-[11px] text-muted-foreground">{report.pricing_note} {report.attribution_note}</p>
        </div>
      )}
    </div>
  );
}
