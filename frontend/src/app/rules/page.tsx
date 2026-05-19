"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import {
  cameraLookup,
  personLookup,
  type Camera,
  type EventEntry,
  type Person,
  type Rule,
  type TelegramChannelOption,
} from "@/components/rules/types";
import { RulesList } from "@/components/rules/RulesList";
import { RuleEventsPanel } from "@/components/rules/RuleEventsPanel";
import { RuleModal } from "@/components/rules/RuleModal";

const LAST_FIRED_CACHE_MS = 30_000;

export default function RulesPage() {
  const { authFetch } = useAuth();
  const [rules, setRules] = useState<Rule[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editRule, setEditRule] = useState<Rule | null>(null);
  // Pre-filled, non-persisted Rule used for persona templates + the
  // Duplicate flow. RuleModal treats it as a new rule (POST on save).
  const [prefillRule, setPrefillRule] = useState<Rule | null>(null);
  const [selectedRule, setSelectedRule] = useState<Rule | null>(null);

  const [telegramChannels, setTelegramChannels] = useState<TelegramChannelOption[]>([]);
  const [telegramChannelsLoading, setTelegramChannelsLoading] = useState(false);

  // Most-recent event timestamp per rule. Computed from a single
  // /api/events fetch on mount + after each save. Cached for 30s.
  const [lastFiredByRule, setLastFiredByRule] = useState<Record<string, string | null>>({});
  const lastFiredFetchedAt = useRef<number>(0);

  const fetchRules = useCallback(async () => {
    try {
      const res = await authFetch("/api/rules");
      if (res.ok) setRules(await res.json());
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  const fetchCameras = useCallback(async () => {
    try {
      const res = await authFetch("/api/cameras");
      if (res.ok) {
        const list = await res.json();
        setCameras(list);
        cameraLookup.clear();
        for (const c of list) cameraLookup.set(c.id, c.name);
      }
    } catch {
      /* silent */
    }
  }, [authFetch]);

  const fetchPersons = useCallback(async () => {
    try {
      const res = await authFetch("/api/persons");
      if (res.ok) {
        const list = await res.json();
        setPersons(list);
        personLookup.clear();
        for (const p of list) personLookup.set(p.id, p.display_name);
      }
    } catch {
      /* silent */
    }
  }, [authFetch]);

  const fetchTelegramChannels = useCallback(async () => {
    setTelegramChannelsLoading(true);
    try {
      const res = await authFetch("/api/telegram/channels");
      if (res.ok) {
        const list: TelegramChannelOption[] = await res.json();
        setTelegramChannels(list);
      }
    } catch {
      /* silent */
    } finally {
      setTelegramChannelsLoading(false);
    }
  }, [authFetch]);

  // Aggregate "last fired" timestamps from the events feed. The
  // backend exposes no per-rule last_fired_at field today, so we
  // reduce the recent event history client-side. Refreshed on save.
  const fetchLastFired = useCallback(async (force = false) => {
    const now = Date.now();
    if (!force && now - lastFiredFetchedAt.current < LAST_FIRED_CACHE_MS) return;
    lastFiredFetchedAt.current = now;
    try {
      const res = await authFetch("/api/events?limit=200");
      if (!res.ok) return;
      const list = (await res.json()) as EventEntry[];
      const map: Record<string, string | null> = {};
      for (const e of list) {
        if (!e.rule_id) continue;
        const existing = map[e.rule_id];
        if (!existing || new Date(e.fired_at) > new Date(existing)) {
          map[e.rule_id] = e.fired_at;
        }
      }
      setLastFiredByRule(map);
    } catch {
      /* silent */
    }
  }, [authFetch]);

  useEffect(() => {
    fetchRules();
    fetchCameras();
    fetchPersons();
    fetchTelegramChannels();
    fetchLastFired(true);
  }, [fetchRules, fetchCameras, fetchPersons, fetchTelegramChannels, fetchLastFired]);

  const refreshAfterSave = useCallback(() => {
    fetchRules();
    fetchLastFired(true);
  }, [fetchRules, fetchLastFired]);

  const openCreate = () => {
    setEditRule(null);
    setPrefillRule(null);
    setShowModal(true);
  };

  const openEdit = (r: Rule) => {
    setEditRule(r);
    setPrefillRule(null);
    setShowModal(true);
  };

  const openDuplicate = (r: Rule) => {
    // Duplicate flow. clone the rule, suffix name, force disabled so
    // the copy doesn't fire silently. The id is cleared so RuleModal
    // POSTs a new rule on save.
    const copy: Rule = {
      ...r,
      id: "",
      name: `${r.name} (copy)`,
      enabled: false,
    };
    setEditRule(null);
    setPrefillRule(copy);
    setShowModal(true);
  };

  const openPersona = (synth: Rule) => {
    setEditRule(null);
    setPrefillRule(synth);
    setShowModal(true);
  };

  const handleDelete = async (id: string) => {
    try {
      await authFetch(`/api/rules/${id}`, { method: "DELETE" });
      if (selectedRule?.id === id) setSelectedRule(null);
      fetchRules();
    } catch {
      /* silent */
    }
  };

  const handleToggle = async (rule: Rule) => {
    // Optimistic update so the card switches visually before the
    // round-trip lands.
    setRules((prev) =>
      prev.map((r) => (r.id === rule.id ? { ...r, enabled: !rule.enabled } : r)),
    );
    try {
      await authFetch(`/api/rules/${rule.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...rule, enabled: !rule.enabled }),
      });
      fetchRules();
    } catch {
      /* silent. revert handled on next fetchRules */
      fetchRules();
    }
  };

  const ruleCount = useMemo(() => rules.length, [rules]);

  return (
    <div className="px-6 py-6">
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Rules</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {ruleCount} rule{ruleCount !== 1 ? "s" : ""} configured
          </p>
        </div>
        <button
          onClick={openCreate}
          className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90"
        >
          + Create rule
        </button>
      </div>

      {loading ? (
        <div className="text-sm text-muted-foreground py-20 text-center">
          Loading.
        </div>
      ) : (
        <div className="grid grid-cols-12 gap-6">
          <RulesList
            rules={rules}
            cameras={cameras}
            selectedRuleId={selectedRule?.id ?? null}
            lastFiredByRule={lastFiredByRule}
            telegramChannels={telegramChannels}
            onSelect={setSelectedRule}
            onToggleEnabled={handleToggle}
            onEdit={openEdit}
            onDuplicate={openDuplicate}
            onDelete={handleDelete}
            onPrefillFromPersona={openPersona}
            onCreateBlank={openCreate}
          />
          {rules.length > 0 && (
            <RuleEventsPanel selectedRule={selectedRule} cameras={cameras} />
          )}
        </div>
      )}

      <RuleModal
        open={showModal}
        onClose={() => setShowModal(false)}
        editRule={editRule}
        prefillRule={prefillRule}
        cameras={cameras}
        persons={persons}
        telegramChannels={telegramChannels}
        telegramChannelsLoading={telegramChannelsLoading}
        onSaved={refreshAfterSave}
      />
    </div>
  );
}
