"use client";

// Single AgentRun rendering. Three stacked sections:
//   a. Plan strip (italic muted, top)
//   b. Trace panel (collapsible, default open while running)
//   c. Answer panel (streams once synthesis begins)
//
// Works in two modes: streaming (events array from useAgentRunStream)
// or replay (AgentRunDetail from /api/agent/runs/{id}). Both paths
// feed the same internal "view model" so the rendering is uniform.

import { useMemo, useState } from "react";
import type { AgentEvent } from "@/lib/agentWs";
import type { AgentRunDetail, Citation } from "./types";
import CitationChip from "./CitationChip";

interface TraceItem {
  call_id: string;
  kind: "tool" | "vlm";
  name: string;
  args_summary: string;
  args_full: unknown;
  result_summary: string;
  result_full: unknown;
  latency_ms: number | null;
  cached: boolean;
  done: boolean;
  error: string | null;
}

interface ViewModel {
  plan: string | null;
  trace: TraceItem[];
  answer: string;
  citations: Citation[];
  done: boolean;
  cancelled: boolean;
  budgetExhausted: boolean;
  failed: boolean;
  errorMessage: string | null;
  noEvidence: boolean;
}

function summarizeArgs(args: unknown): string {
  if (!args || typeof args !== "object") return "";
  const keys = Object.keys(args as Record<string, unknown>);
  if (keys.length === 0) return "(no args)";
  return keys
    .slice(0, 3)
    .map((k) => {
      const v = (args as Record<string, unknown>)[k];
      if (typeof v === "string") return `${k}=${v.length > 32 ? v.slice(0, 31) + "…" : v}`;
      if (typeof v === "number" || typeof v === "boolean") return `${k}=${v}`;
      if (Array.isArray(v)) return `${k}[${v.length}]`;
      return `${k}=…`;
    })
    .join(" ");
}

function summarizeResult(result: unknown): string {
  if (!result || typeof result !== "object") return "ok";
  const r = result as Record<string, unknown>;
  if (Array.isArray(r.results)) return `${(r.results as unknown[]).length} results`;
  if (typeof r.answer === "string") {
    const ans = r.answer as string;
    return ans.length > 80 ? ans.slice(0, 79) + "…" : ans;
  }
  if (typeof r.summary === "string") return r.summary as string;
  return "ok";
}

function buildFromEvents(events: AgentEvent[]): ViewModel {
  let plan: string | null = null;
  const traceMap = new Map<string, TraceItem>();
  let answer = "";
  let citations: Citation[] = [];
  let done = false;
  let cancelled = false;
  let budgetExhausted = false;
  let failed = false;
  let errorMessage: string | null = null;

  for (const ev of events) {
    switch (ev.type) {
      case "plan":
        plan = (ev.summary as string) ?? (ev.text as string) ?? plan;
        break;
      case "tool_start": {
        const call_id = String(ev.call_id ?? `t${traceMap.size}`);
        traceMap.set(call_id, {
          call_id,
          kind: "tool",
          name: String(ev.tool ?? ev.name ?? "tool"),
          args_summary: summarizeArgs(ev.params ?? ev.arguments),
          args_full: ev.params ?? ev.arguments ?? {},
          result_summary: "running.",
          result_full: null,
          latency_ms: null,
          cached: false,
          done: false,
          error: null,
        });
        break;
      }
      case "vlm_start": {
        const call_id = String(ev.call_id ?? `v${traceMap.size}`);
        traceMap.set(call_id, {
          call_id,
          kind: "vlm",
          name: "analyze_clip_with_vlm",
          args_summary: summarizeArgs({ target: ev.target, question: ev.question }),
          args_full: { target: ev.target, question: ev.question },
          result_summary: "analyzing.",
          result_full: null,
          latency_ms: null,
          cached: false,
          done: false,
          error: null,
        });
        break;
      }
      case "tool_result":
      case "vlm_result": {
        const call_id = String(ev.call_id ?? "");
        const existing = traceMap.get(call_id);
        if (existing) {
          existing.done = true;
          existing.result_summary = (ev.summary as string) ?? summarizeResult(ev.result ?? ev);
          existing.result_full = ev.result ?? ev.truncated_payload ?? ev;
          existing.latency_ms = (ev.latency_ms as number) ?? existing.latency_ms;
          existing.cached = Boolean(ev.cached ?? existing.cached);
          existing.error = (ev.error as string) ?? null;
        }
        break;
      }
      case "synthesis_token":
        answer += String(ev.delta ?? "");
        break;
      case "done":
        done = true;
        if (typeof ev.text === "string") answer = ev.text;
        if (Array.isArray(ev.citations)) citations = ev.citations as Citation[];
        break;
      case "cancelled":
        cancelled = true;
        done = true;
        break;
      case "error":
        failed = true;
        done = true;
        errorMessage = (ev.message as string) ?? "Agent failed.";
        if (ev.code === "budget_exhausted") budgetExhausted = true;
        break;
      case "budget_warning":
        // Surfaced via banner in parent; harmless here.
        break;
    }
  }

  const noEvidence = done && !cancelled && !failed && answer.trim() === "";
  return {
    plan,
    trace: Array.from(traceMap.values()),
    answer,
    citations,
    done,
    cancelled,
    budgetExhausted,
    failed,
    errorMessage,
    noEvidence,
  };
}

function buildFromDetail(detail: AgentRunDetail): ViewModel {
  const trace: TraceItem[] = [];
  for (const t of detail.tool_calls) {
    trace.push({
      call_id: t.id,
      kind: "tool",
      name: t.tool_name,
      args_summary: summarizeArgs(t.arguments),
      args_full: t.arguments,
      result_summary: t.error_message ? `error: ${t.error_message}` : summarizeResult(t.result),
      result_full: t.result,
      latency_ms: t.latency_ms,
      cached: Boolean(t.cached),
      done: true,
      error: t.error_message,
    });
  }
  for (const v of detail.vlm_calls) {
    trace.push({
      call_id: v.id,
      kind: "vlm",
      name: "analyze_clip_with_vlm",
      args_summary: summarizeArgs({
        observation_id: v.observation_id,
        recording_id: v.recording_id,
        question: v.question,
      }),
      args_full: v,
      result_summary: v.response
        ? `${(v.response as Record<string, unknown>).answer ?? "ok"} (conf ${v.confidence ?? "?"})`
        : "no response",
      result_full: v.response,
      latency_ms: null,
      cached: v.cached,
      done: true,
      error: null,
    });
  }
  return {
    plan: detail.plan,
    trace,
    answer: detail.final_answer ?? "",
    citations: detail.citations ?? [],
    done: detail.status !== "running",
    cancelled: detail.status === "cancelled",
    budgetExhausted: detail.status === "budget_exhausted",
    failed: detail.status === "failed",
    errorMessage: detail.error_message,
    noEvidence: detail.status === "completed" && !(detail.final_answer ?? "").trim(),
  };
}

interface AgentResponseCardProps {
  question: string;
  events?: AgentEvent[];
  detail?: AgentRunDetail;
  isStreaming?: boolean;
}

export default function AgentResponseCard({
  question,
  events,
  detail,
  isStreaming,
}: AgentResponseCardProps) {
  const vm = useMemo<ViewModel>(() => {
    if (detail) return buildFromDetail(detail);
    return buildFromEvents(events ?? []);
  }, [events, detail]);

  const [traceOpen, setTraceOpen] = useState<boolean>(!vm.done);
  const [inspectCallId, setInspectCallId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const copyQuestion = async () => {
    try {
      await navigator.clipboard.writeText(question);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {/* ignore */}
  };

  const inspected = inspectCallId
    ? vm.trace.find((t) => t.call_id === inspectCallId) ?? null
    : null;

  return (
    <div className="border border-border bg-card rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">You asked</div>
          <div className="text-sm font-medium">{question}</div>
        </div>
        <button
          type="button"
          onClick={copyQuestion}
          aria-label="Copy question to clipboard"
          className="text-[10px] text-muted-foreground hover:text-foreground px-2 py-1 rounded border border-border"
        >
          {copied ? "copied" : "copy"}
        </button>
      </div>

      {vm.plan && (
        <div className="px-4 py-2 border-b border-border bg-background/40">
          <div className="text-[11px] italic text-muted-foreground">
            <span className="font-mono uppercase mr-1.5">plan</span>
            {vm.plan}
          </div>
        </div>
      )}

      {vm.trace.length > 0 && (
        <div className="border-b border-border">
          <button
            type="button"
            onClick={() => setTraceOpen((o) => !o)}
            className="w-full px-4 py-2 flex items-center justify-between text-xs text-muted-foreground hover:bg-muted/40"
          >
            <span>
              Trace · {vm.trace.length} step{vm.trace.length !== 1 ? "s" : ""}
              {isStreaming && !vm.done && " · live"}
            </span>
            <span>{traceOpen ? "−" : "+"}</span>
          </button>
          {traceOpen && (
            <div className="px-4 pb-3 space-y-2">
              {vm.trace.map((t) => (
                <button
                  key={t.call_id}
                  type="button"
                  onClick={() => setInspectCallId(t.call_id)}
                  aria-label={`Inspect ${t.name}`}
                  className="w-full text-left border border-border/60 rounded p-2 bg-background hover:bg-muted/40 transition-colors"
                >
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-base leading-none">{t.kind === "vlm" ? "🔍" : "🛠"}</span>
                    <span className="font-mono font-medium">{t.name}</span>
                    {t.cached && (
                      <span className="text-[9px] px-1 py-px rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                        cached
                      </span>
                    )}
                    {!t.done && (
                      <span className="text-[9px] px-1 py-px rounded bg-blue-500/20 text-blue-300 border border-blue-500/30">
                        running
                      </span>
                    )}
                    {t.error && (
                      <span className="text-[9px] px-1 py-px rounded bg-red-500/20 text-red-300 border border-red-500/30">
                        error
                      </span>
                    )}
                    {typeof t.latency_ms === "number" && (
                      <span className="ml-auto text-[10px] text-muted-foreground font-mono">{t.latency_ms}ms</span>
                    )}
                  </div>
                  <div className="mt-1 text-[11px] text-muted-foreground font-mono truncate">
                    {t.args_summary}
                  </div>
                  <div className="text-[11px] mt-0.5 truncate">{t.result_summary}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="p-4 space-y-3">
        {vm.budgetExhausted && (
          <div className="text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded p-2">
            You&apos;ve used your daily AI budget. Resets at midnight household time. Admins can raise your limit in Settings.
          </div>
        )}
        {vm.cancelled && (
          <div className="text-xs text-zinc-300 bg-zinc-500/10 border border-zinc-500/30 rounded p-2">
            Cancelled by you. Partial findings below.
          </div>
        )}
        {vm.failed && vm.errorMessage && !vm.budgetExhausted && (
          <div className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded p-2">
            {vm.errorMessage}
          </div>
        )}

        {vm.answer ? (
          <div className="text-sm whitespace-pre-wrap leading-relaxed">{vm.answer}</div>
        ) : vm.done ? (
          vm.noEvidence ? (
            <div className="text-sm text-muted-foreground italic">
              No evidence found in the inspected footage.
            </div>
          ) : null
        ) : (
          <div className="text-sm text-muted-foreground italic">Investigating.</div>
        )}

        {vm.citations.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-2 border-t border-border/60">
            <span className="text-[10px] uppercase text-muted-foreground mr-1">Citations</span>
            {vm.citations.map((c, i) => (
              <CitationChip key={`${c.kind}:${c.id}:${i}`} citation={c} />
            ))}
          </div>
        )}

        {vm.done && vm.answer && (
          <div className="text-[10px] text-muted-foreground italic border-t border-border/60 pt-2">
            Nurby answers from camera evidence and can be wrong. Do not rely on Nurby for safety-critical monitoring.
          </div>
        )}
      </div>

      {inspected && (
        <div
          className="fixed inset-0 z-[100] bg-black/70 flex items-center justify-center p-6"
          onClick={() => setInspectCallId(null)}
        >
          <div
            className="bg-card border border-border rounded-lg max-w-3xl w-full max-h-[85vh] overflow-auto p-4 space-y-3"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold font-mono">{inspected.name}</div>
              <button
                onClick={() => setInspectCallId(null)}
                aria-label="Close inspector"
                className="text-muted-foreground hover:text-foreground"
              >
                ✕
              </button>
            </div>
            <div>
              <div className="text-[10px] uppercase text-muted-foreground mb-1">Arguments</div>
              <pre className="text-[11px] font-mono bg-background border border-border rounded p-2 overflow-x-auto max-h-72">
                {JSON.stringify(inspected.args_full, null, 2)}
              </pre>
            </div>
            <div>
              <div className="text-[10px] uppercase text-muted-foreground mb-1">Result</div>
              <pre className="text-[11px] font-mono bg-background border border-border rounded p-2 overflow-x-auto max-h-72">
                {JSON.stringify(inspected.result_full, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
