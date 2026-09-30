"use client";

import { useState } from "react";
import { buildRuleSummary, describeTrigger, type Camera, type Rule } from "./types";
import {
  modeGateLabel,
  modePausedLabel,
  ruleActiveIn,
  type HouseholdMode,
} from "@/lib/household-mode";
import { translate } from "@/lib/i18n";
import { useAuth } from "@/lib/auth";

export interface RuleHealth {
  last_fired_at: string | null;
  fires_7d: number;
  last_action_status: string | null;
  last_action_error: string | null;
  // 7-day "completed work" counts, same window as fires_7d.
  acted_7d?: number;
  clips_7d?: number;
  indexed_7d?: number;
  stale_refs: string[];
}

export interface RuleCardProps {
  rule: Rule;
  cameras: Camera[];
  selected: boolean;
  // Last-fired-at timestamp (ISO). Null/undefined renders "Never fired".
  lastFiredAt?: string | null;
  // Aggregate from GET /api/rules/health (action failures, stale refs).
  health?: RuleHealth | null;
  // Current household mode (#184). A rule gated on a different mode is
  // enabled but quiet, which otherwise looks identical to broken.
  householdMode?: HouseholdMode | null;
  onSelect: () => void;
  onToggleEnabled: () => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}

function formatRelative(iso: string, t: (key: string, values?: Record<string, string | number>) => string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diffMs = now - then;
  if (diffMs < 60_000) return t("rules.card.just_now");
  const mins = Math.round(diffMs / 60_000);
  if (mins < 60) return t("rules.card.minutes_ago", { count: mins });
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return t("rules.card.hours_ago", { count: hrs });
  const days = Math.round(hrs / 24);
  return t("rules.card.days_ago", { count: days });
}

export function RuleCard({
  rule,
  cameras,
  selected,
  lastFiredAt,
  health,
  householdMode,
  onSelect,
  onToggleEnabled,
  onEdit,
  onDuplicate,
  onDelete,
}: RuleCardProps) {
  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const [menuOpen, setMenuOpen] = useState(false);

  // Color the badge red-ish if Never AND rule older than 24h. Likely
  // a broken rule. Callers can investigate.
  const createdMs = rule.created_at ? new Date(rule.created_at).getTime() : 0;
  const olderThan24h = createdMs > 0 && Date.now() - createdMs > 24 * 3600 * 1000;
  const neverFired = !lastFiredAt;
  // Household mode (#184). "Paused" is deliberately a different colour
  // from the amber problem badges: a mode-gated rule is working exactly
  // as written, it is just not this mode's turn.
  const modeGate = modeGateLabel(rule.conditions as Record<string, unknown> | null);
  const silencedByMode =
    householdMode != null && !ruleActiveIn(rule.conditions as Record<string, unknown> | null, householdMode);

  const badgeClass = neverFired
    ? olderThan24h
      ? "border-red-800 bg-red-900/30 text-red-400"
      : "border-border bg-muted/40 text-muted-foreground"
    : "border-border bg-muted/40 text-muted-foreground";

  // Health badges: latest action failed, references pointing nowhere, or
  // an enabled rule that has matched nothing in 14 days (distinct from
  // "Never fired": it HAS a history, just a dead recent window).
  const actionFailing = health?.last_action_status === "failed";
  const staleRefs = health?.stale_refs?.length ? health.stale_refs : null;
  const olderThan14d = createdMs > 0 && Date.now() - createdMs > 14 * 24 * 3600 * 1000;
  const quiet14d =
    rule.enabled && olderThan14d && !neverFired && health != null && health.fires_7d === 0 &&
    !!health.last_fired_at && Date.now() - new Date(health.last_fired_at).getTime() > 14 * 24 * 3600 * 1000;

  // "Completed work" strip: what the rule actually did this week, from the
  // health aggregate. Every number is a real count, so the strip only shows
  // when the rule has fires to describe.
  const fires = health?.fires_7d ?? 0;
  const work =
    health && fires > 0
      ? [
          { label: t("rules.card.acted"), count: health.acted_7d ?? 0, title: t("rules.card.acted_help") },
          { label: t("rules.card.logged"), count: fires, title: t("rules.card.logged_help") },
          { label: t("rules.card.clips_saved"), count: health.clips_7d ?? 0, title: t("rules.card.clips_saved_help") },
          { label: t("rules.card.searchable"), count: health.indexed_7d ?? 0, title: t("rules.card.searchable_help") },
        ]
      : null;

  return (
    <div
      onClick={onSelect}
      className={`rounded-lg border p-4 cursor-pointer transition-colors ${
        selected
          ? "border-accent bg-card"
          : "border-border bg-card hover:border-muted-foreground/30"
      } ${rule.enabled ? "" : "opacity-60"}`}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onToggleEnabled();
            }}
            className={`w-8 h-5 rounded-full relative transition-colors ${
              rule.enabled ? "bg-green-500" : "bg-muted"
            }`}
          >
            <span
              className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                rule.enabled ? "left-3.5" : "left-0.5"
              }`}
            />
          </button>
          <div>
            <div className="font-medium flex items-center gap-2">
              <span>{rule.name}</span>
              {rule.is_system && (
                <span className="text-[10px] px-1.5 py-0.5 rounded border border-sky-700 bg-sky-900/20 text-sky-300" title={t("rules.card.system_help")}>
                  {t("rules.card.system")}
                </span>
              )}
              {rule.is_system && (
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded border border-sky-800 bg-sky-900/30 text-sky-300"
                  title={t("rules.card.system_help")}
                >
                  {t("rules.card.system")}
                </span>
              )}
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded border font-mono ${badgeClass}`}
                title={lastFiredAt ? t("rules.card.last_fired", { time: lastFiredAt }) : t("rules.card.no_events")}
              >
                {neverFired ? t("rules.card.never_fired") : t("rules.card.fired", { time: formatRelative(lastFiredAt!, t) })}
              </span>
              {actionFailing && (
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded border border-red-800 bg-red-900/30 text-red-400"
                  title={health?.last_action_error || t("rules.card.action_failed_help")}
                >
                  {t("rules.card.action_failing")}
                </span>
              )}
              {staleRefs && (
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded border border-amber-700 bg-amber-900/30 text-amber-400"
                  title={staleRefs.join("\n")}
                >
                  {t("rules.card.broken_reference")}
                </span>
              )}
              {quiet14d && !actionFailing && !staleRefs && (
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded border border-amber-700 bg-amber-900/30 text-amber-400"
                  title={t("rules.card.no_matches_help")}
                >
                  {t("rules.card.no_matches")}
                </span>
              )}
              {!rule.enabled && (
                <span className="text-[10px] px-1.5 py-0.5 rounded border border-border text-muted-foreground">
                  {t("rules.card.disabled")}
                </span>
              )}
              {rule.enabled && modeGate && (
                <span
                  className={`text-[10px] px-1.5 py-0.5 rounded border ${
                    silencedByMode
                      ? "border-sky-700 bg-sky-900/30 text-sky-300"
                      : "border-border text-muted-foreground"
                  }`}
                  title={
                    silencedByMode
                      ? t("rules.card.mode_quiet", { mode: modeGate })
                      : modeGate
                  }
                >
                  {silencedByMode ? modePausedLabel(rule.conditions as Record<string, unknown> | null) : modeGate}
                </span>
              )}
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {describeTrigger(rule.trigger_pattern)}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1 relative">
          {rule.is_system ? (
            <span
              className="text-[11px] text-muted-foreground pr-1"
              title={t("rules.card.managed_help")}
            >
              {t("rules.card.managed")}
            </span>
          ) : (
            <>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onEdit();
                }}
                className="px-2 py-1 text-xs rounded border border-border hover:bg-muted transition-colors"
              >
                {t("rules.card.edit")}
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setMenuOpen((v) => !v);
                }}
                className="px-2 py-1 text-xs rounded border border-border hover:bg-muted transition-colors"
                title={t("rules.card.more_actions")}
              >
                ⋯
              </button>
              {menuOpen && (
                <div
                  className="absolute right-0 top-full mt-1 bg-card border border-border rounded shadow-lg z-10 min-w-[140px]"
                  onClick={(e) => e.stopPropagation()}
                  onMouseLeave={() => setMenuOpen(false)}
                >
                  <button
                    onClick={() => {
                      setMenuOpen(false);
                      onDuplicate();
                    }}
                    className="block w-full text-left px-3 py-1.5 text-xs hover:bg-muted"
                  >
                    {t("rules.card.duplicate")}
                  </button>
                  <button
                    onClick={() => {
                      setMenuOpen(false);
                      onToggleEnabled();
                    }}
                    className="block w-full text-left px-3 py-1.5 text-xs hover:bg-muted"
                  >
                    {rule.enabled ? t("rules.card.disable") : t("rules.card.enable")}
                  </button>
                  <button
                    onClick={() => {
                      setMenuOpen(false);
                      // The page-level handler shows the styled confirm dialog.
                      onDelete();
                    }}
                    className="block w-full text-left px-3 py-1.5 text-xs hover:bg-red-900/30 text-red-400"
                  >
                    {t("rules.card.delete")}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      <div className="mt-2 text-xs italic text-muted-foreground/80 leading-relaxed">
        {buildRuleSummary(rule, cameras)}
      </div>
      {work && (
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
          <span className="text-muted-foreground/60">{t("rules.card.last_7_days")}:</span>
          {work.map((w, i) => (
            <span key={w.label} className="flex items-center gap-2">
              {i > 0 && <span className="text-muted-foreground/30">·</span>}
              <span
                className={w.count > 0 ? "text-muted-foreground" : "text-muted-foreground/40"}
                title={w.title}
              >
                <span className="font-mono">{w.count}</span> {w.label}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
