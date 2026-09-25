"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

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
  const { authFetch } = useAuth();
  const [report, setReport] = useState<UsageReport | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    authFetch("/api/agent/usage/report?days=7")
      .then(async (response) => response.ok ? await response.json() as UsageReport : null)
      .then((value) => { if (!cancelled) setReport(value); })
      .catch(() => { if (!cancelled) setReport(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [authFetch]);

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="px-4 py-3.5 flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">AI usage</div>
          <div className="text-xs text-muted-foreground mt-0.5">Estimated spend over the last 7 days</div>
        </div>
        <span className="text-xs text-muted-foreground">{loading ? "Loading." : report ? dollars(report.totals.cost_cents) : "Unavailable"}</span>
      </div>
      {report && (
        <div className="border-t border-border px-4 py-3 space-y-3">
          {report.perception_budget.stage !== "normal" && (
            <div className={`rounded border px-3 py-2 text-xs ${report.perception_budget.stage === "blocked" ? "border-red-500/40 bg-red-500/10 text-red-200" : "border-amber-500/40 bg-amber-500/10 text-amber-200"}`}>
              <div className="font-medium">Camera AI budget {report.perception_budget.stage}</div>
              <div className="mt-0.5">{report.perception_budget.reason || "Perception usage is approaching its configured limit."}</div>
            </div>
          )}
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div><div className="text-muted-foreground">Calls</div><div className="font-medium">{report.totals.calls}</div></div>
            <div><div className="text-muted-foreground">Input tokens</div><div className="font-medium">{report.totals.tokens_in.toLocaleString()}</div></div>
            <div><div className="text-muted-foreground">Output tokens</div><div className="font-medium">{report.totals.tokens_out.toLocaleString()}</div></div>
          </div>
          {report.by_camera.length > 0 && (
            <div>
              <div className="text-xs font-medium mb-1">By camera / workload</div>
              <div className="space-y-1">
                {report.by_camera.slice(0, 5).map((row) => (
                  <div key={row.name} className="flex justify-between text-xs text-muted-foreground"><span>{row.name}</span><span>{dollars(row.cost_cents)} · {row.calls} calls</span></div>
                ))}
              </div>
            </div>
          )}
          {report.by_workload.length > 0 && (
            <div>
              <div className="text-xs font-medium mb-1">By workload</div>
              <div className="space-y-1">
                {report.by_workload.slice(0, 6).map((row) => (
                  <div key={row.name} className="flex justify-between text-xs text-muted-foreground"><span>{row.name}</span><span>{dollars(row.cost_cents)} · {row.calls} calls</span></div>
                ))}
              </div>
            </div>
          )}
          {report.by_rule.length > 0 && (
            <div>
              <div className="text-xs font-medium mb-1">By rule</div>
              <div className="space-y-1">
                {report.by_rule.slice(0, 6).map((row) => (
                  <div key={row.name} className="flex justify-between text-xs text-muted-foreground"><span>{row.name}</span><span>{dollars(row.cost_cents)} · {row.calls} calls</span></div>
                ))}
              </div>
            </div>
          )}
          <p className="text-[11px] text-muted-foreground">{report.pricing_note} {report.attribution_note}</p>
        </div>
      )}
    </div>
  );
}
