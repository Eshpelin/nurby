"use client";

import { RuleCard, type RuleHealth } from "./RuleCard";
import type { HouseholdMode } from "@/lib/household-mode";
import { TemplateGallery } from "./TemplateGallery";
import { type Camera, type Person, type Rule, type TelegramChannelOption } from "./types";

export interface RulesListProps {
  rules: Rule[];
  cameras: Camera[];
  persons: Person[];
  selectedRuleId: string | null;
  lastFiredByRule: Record<string, string | null>;
  healthByRule?: Record<string, RuleHealth>;
  householdMode?: HouseholdMode | null;
  telegramChannels: TelegramChannelOption[];
  onSelect: (rule: Rule) => void;
  onToggleEnabled: (rule: Rule) => void;
  onEdit: (rule: Rule) => void;
  onDuplicate: (rule: Rule) => void;
  onDelete: (ruleId: string) => void;
  // Triggered by empty-state UX. callers open the modal with the
  // synthesized prefill rule.
  onPrefillFromPersona: (rule: Rule) => void;
  onCreateBlank: () => void;
}

export function RulesList({
  rules,
  cameras,
  persons,
  selectedRuleId,
  lastFiredByRule,
  healthByRule,
  householdMode,
  telegramChannels,
  onSelect,
  onToggleEnabled,
  onEdit,
  onDuplicate,
  onDelete,
  onPrefillFromPersona,
  onCreateBlank,
}: RulesListProps) {
  if (rules.length === 0) {
    return (
      <div className="col-span-1 lg:col-span-12">
        <TemplateGallery
          cameras={cameras}
          persons={persons}
          telegramChannels={telegramChannels}
          onUseTemplate={onPrefillFromPersona}
          onCreateBlank={onCreateBlank}
        />
      </div>
    );
  }
  const householdRules = rules.filter((r) => !r.is_system);
  const systemRules = rules.filter((r) => r.is_system);
  const renderRule = (r: Rule) => (
        <RuleCard
          key={r.id}
          rule={r}
          cameras={cameras}
          selected={selectedRuleId === r.id}
          lastFiredAt={lastFiredByRule[r.id] ?? null}
          health={healthByRule?.[r.id] ?? null}
          householdMode={householdMode}
          onSelect={() => onSelect(r)}
          onToggleEnabled={() => onToggleEnabled(r)}
          onEdit={() => onEdit(r)}
          onDuplicate={() => onDuplicate(r)}
          onDelete={() => onDelete(r.id)}
        />
  );
  return (
    <section className="col-span-1 lg:col-span-8 space-y-3">
      {householdRules.map(renderRule)}
      {systemRules.length > 0 && (
        <details className="rounded-lg border border-border bg-card/40">
          <summary className="cursor-pointer px-4 py-3 text-sm text-muted-foreground">System rules ({systemRules.length})</summary>
          <div className="space-y-3 border-t border-border p-3">{systemRules.map(renderRule)}</div>
        </details>
      )}
    </section>
  );
}
