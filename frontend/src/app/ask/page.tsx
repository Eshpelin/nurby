"use client";

// Top-level "Ask Nurby" surface. Three columns on desktop (history,
// conversation, sidebar omitted in v1), single column with drawer on
// mobile. The page owns the active run lifecycle: send -> POST
// /api/agent/ask -> WS stream -> archive into pastRuns on done.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useAgentRunStream } from "@/lib/agentWs";
import ChatHistory from "@/components/ask/ChatHistory";
import ChatComposer from "@/components/ask/ChatComposer";
import Conversation from "@/components/ask/Conversation";
import EmptyState from "@/components/ask/EmptyState";
import OnboardingModal from "@/components/ask/OnboardingModal";
import type {
  AgentRunDetail,
  ProviderModel,
  UsageToday,
} from "@/components/ask/types";

const LS_MODEL_KEY = "nurby:agent-last-model";
const LS_ONBOARDED_KEY = "nurby:agent-onboarded";

export default function AskPage() {
  const { authFetch, token, user } = useAuth();
  const search = useSearchParams();

  const [providers, setProviders] = useState<ProviderModel[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [providersMissing, setProvidersMissing] = useState(false);
  const [model, setModel] = useState<ProviderModel | null>(null);
  const [usage, setUsage] = useState<UsageToday | null>(null);
  const [usageLoading, setUsageLoading] = useState(true);

  const [text, setText] = useState("");
  const [activeQuestion, setActiveQuestion] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [parentRunId, setParentRunId] = useState<string | null>(null);
  const [pastRuns, setPastRuns] = useState<AgentRunDetail[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [composerFocusKey, setComposerFocusKey] = useState(0);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const stream = useAgentRunStream(activeRunId, token);
  const isStreaming = activeRunId !== null && stream.status !== "closed" && stream.status !== "error";
  const lastTurnFinishedAt = useRef<number>(0);

  // ----- bootstrap providers + restore last model + onboarding gate
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setProvidersLoading(true);
      try {
        const res = await authFetch("/api/agent/providers");
        if (res.status === 404) {
          if (!cancelled) { setProvidersMissing(true); setProviders([]); }
          return;
        }
        if (res.ok) {
          const data = await res.json();
          // The endpoint returns one object per provider, each carrying a
          // nested `models` array. Flatten to the per-model rows the
          // selector renders, threading the supports_tools flag so we can
          // warn on local models that cannot drive the agent's tool loop.
          const provObjs: Array<{
            provider_id: string;
            kind: string;
            label: string;
            models?: Array<{ name: string; label?: string; recommended?: boolean; supports_tools?: boolean }>;
            suggested_tool_model?: string | null;
          }> = Array.isArray(data) ? data : [];
          const flat: ProviderModel[] = [];
          for (const pr of provObjs) {
            for (const m of pr.models ?? []) {
              flat.push({
                id: m.name,
                name: m.label || m.name,
                kind: pr.kind,
                provider_id: pr.provider_id,
                provider_name: pr.label,
                recommended: m.recommended,
                supports_tools: m.supports_tools !== false,
                suggested_tool_model: pr.suggested_tool_model ?? null,
              });
            }
          }
          if (!cancelled) setProviders(flat);
        }
      } catch {/* ignore */}
      finally { if (!cancelled) setProvidersLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [authFetch]);

  useEffect(() => {
    if (providersLoading || providers.length === 0) return;
    try {
      const raw = localStorage.getItem(LS_MODEL_KEY);
      if (raw) {
        const saved = JSON.parse(raw) as { provider_id: string; id: string };
        const found = providers.find((p) => p.provider_id === saved.provider_id && p.id === saved.id);
        if (found) { setModel(found); return; }
      }
    } catch {/* ignore */}
    // Not picked yet. Show onboarding once.
    const onboarded = localStorage.getItem(LS_ONBOARDED_KEY);
    if (!onboarded) setShowOnboarding(true);
  }, [providersLoading, providers]);

  const persistModel = useCallback((m: ProviderModel) => {
    setModel(m);
    try {
      localStorage.setItem(LS_MODEL_KEY, JSON.stringify({ provider_id: m.provider_id, id: m.id }));
    } catch {/* ignore */}
  }, []);

  // ----- usage poll
  const refreshUsage = useCallback(async () => {
    try {
      const res = await authFetch("/api/agent/usage/today");
      if (res.status === 404) { setUsage({ cost_cents: 0, cost_cents_cap: 500, tokens: 0, tokens_cap: 500000, runs: 0 }); return; }
      if (res.ok) setUsage(await res.json());
    } catch {/* ignore */}
    finally { setUsageLoading(false); }
  }, [authFetch]);
  useEffect(() => {
    refreshUsage();
    const t = setInterval(refreshUsage, 15000);
    return () => clearInterval(t);
  }, [refreshUsage]);

  // ----- archive completed run into pastRuns
  const finalizeRun = useCallback(async (runId: string) => {
    try {
      const res = await authFetch(`/api/agent/runs/${runId}`);
      if (res.ok) {
        const detail = (await res.json()) as AgentRunDetail;
        setPastRuns((prev) => [...prev, detail]);
      }
    } catch {/* ignore */}
    setActiveQuestion(null);
    setActiveRunId(null);
    setParentRunId(runId);
    setHistoryRefresh((k) => k + 1);
    refreshUsage();
    lastTurnFinishedAt.current = Date.now();
  }, [authFetch, refreshUsage]);

  useEffect(() => {
    if (!activeRunId) return;
    if (stream.status === "closed" || stream.status === "error") {
      finalizeRun(activeRunId);
    }
  }, [stream.status, activeRunId, finalizeRun]);

  // ----- send
  const sendQuestion = useCallback(async (questionText: string) => {
    if (!model || !questionText.trim()) return;
    setSubmitError(null);
    setText("");
    // Parent run only inherits within 5 min idle window.
    const recent = Date.now() - lastTurnFinishedAt.current < 5 * 60 * 1000;
    const parent = recent ? parentRunId : null;
    setActiveQuestion(questionText);
    try {
      const res = await authFetch("/api/agent/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: questionText,
          provider_id: model.provider_id,
          model: model.id,
          parent_run_id: parent,
        }),
      });
      if (res.status === 404) {
        setSubmitError("Agent backend not yet deployed. /api/agent/ask returned 404.");
        setActiveQuestion(null);
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setSubmitError(body?.detail ?? `Send failed (${res.status}).`);
        setActiveQuestion(null);
        return;
      }
      const data = await res.json();
      const runId = data.run_id ?? data.id;
      if (!runId) {
        setSubmitError("Backend response missing run_id.");
        setActiveQuestion(null);
        return;
      }
      setActiveRunId(runId);
      setHistoryRefresh((k) => k + 1);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "Network error.");
      setActiveQuestion(null);
    }
  }, [authFetch, model, parentRunId]);

  const cancelActive = useCallback(async () => {
    if (!activeRunId) return;
    try {
      await authFetch(`/api/agent/runs/${activeRunId}/cancel`, { method: "POST" });
    } catch {/* ignore; stream will see cancelled */}
  }, [authFetch, activeRunId]);

  // ----- open a past run
  const loadRun = useCallback(async (runId: string) => {
    try {
      const res = await authFetch(`/api/agent/runs/${runId}`);
      if (res.ok) {
        const detail = (await res.json()) as AgentRunDetail;
        setPastRuns([detail]);
        setActiveQuestion(null);
        setActiveRunId(null);
        setParentRunId(runId);
      }
    } catch {/* ignore */}
  }, [authFetch]);

  const newChat = useCallback(() => {
    setPastRuns([]);
    setActiveQuestion(null);
    setActiveRunId(null);
    setParentRunId(null);
    setText("");
    setComposerFocusKey((k) => k + 1);
    stream.reset();
  }, [stream]);

  // ----- deep-link via ?run=
  useEffect(() => {
    const r = search.get("run");
    if (r) loadRun(r);
  }, [search, loadRun]);

  // ----- deep-link via ?q= (e.g. the dashboard "try asking" chips).
  // Auto-sends the prefilled question once a model is selected so a
  // brand-new user gets a real answer in one click. Runs at most once.
  const askedQ = useRef(false);
  useEffect(() => {
    if (askedQ.current) return;
    const q = search.get("q");
    if (!q || !model) return;
    askedQ.current = true;
    sendQuestion(q);
  }, [search, model, sendQuestion]);

  // ----- global keyboard. Cmd/Ctrl+K focuses composer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setComposerFocusKey((k) => k + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const showEmpty = useMemo(
    () => pastRuns.length === 0 && !activeQuestion,
    [pastRuns.length, activeQuestion],
  );

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      {/* History rail. Drawer on mobile. */}
      <div className={`fixed inset-y-14 left-0 z-40 transform transition-transform md:static md:translate-x-0 ${drawerOpen ? "translate-x-0" : "-translate-x-full"}`}>
        <ChatHistory
          selectedRunId={pastRuns[0]?.id ?? activeRunId ?? null}
          onSelect={(id) => { loadRun(id); setDrawerOpen(false); }}
          onNewChat={() => { newChat(); setDrawerOpen(false); }}
          refreshKey={historyRefresh}
        />
      </div>
      {drawerOpen && (
        <div className="fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setDrawerOpen(false)} />
      )}

      <main className="flex-1 flex flex-col min-w-0">
        <div className="md:hidden border-b border-border px-4 py-2 flex items-center justify-between">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open chat history"
            className="text-xs px-2 py-1 rounded border border-border"
          >
            ☰ History
          </button>
          {user?.role === "admin" && (
            <a href="/ask/admin" className="text-xs text-muted-foreground hover:text-foreground">Admin</a>
          )}
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-4 py-6">
            {providersMissing && (
              <div className="mb-4 text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded p-2">
                Agent backend not yet deployed. The /api/agent endpoints returned 404. The UI is ready; come back once Wave 2A lands.
              </div>
            )}
            {submitError && (
              <div className="mb-4 text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded p-2">
                {submitError}
              </div>
            )}
            {showEmpty ? (
              <EmptyState onPersonaClick={(q) => sendQuestion(q)} />
            ) : (
              <Conversation
                pastRuns={pastRuns}
                activeQuestion={activeQuestion}
                activeEvents={stream.events}
                isStreaming={isStreaming}
              />
            )}
          </div>
        </div>

        <ChatComposer
          value={text}
          onChange={setText}
          onSend={() => sendQuestion(text)}
          onCancel={cancelActive}
          inFlight={isStreaming}
          model={model}
          onModelChange={persistModel}
          providers={providers}
          providersLoading={providersLoading}
          usage={usage}
          usageLoading={usageLoading}
          focusKey={composerFocusKey}
        />
      </main>

      <OnboardingModal
        open={showOnboarding}
        providers={providers}
        onPick={(m) => {
          persistModel(m);
          localStorage.setItem(LS_ONBOARDED_KEY, "1");
          setShowOnboarding(false);
        }}
        onClose={() => {
          localStorage.setItem(LS_ONBOARDED_KEY, "1");
          setShowOnboarding(false);
        }}
      />
    </div>
  );
}
