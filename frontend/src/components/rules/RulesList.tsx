"use client";

import { RuleCard, type RuleHealth } from "./RuleCard";
import { TemplateGallery } from "./TemplateGallery";
import { type Camera, type Person, type Rule, type TelegramChannelOption } from "./types";

export interface RulesListProps {
  rules: Rule[];
  cameras: Camera[];
  persons: Person[];
  selectedRuleId: string | null;
  lastFiredByRule: Record<string, string | null>;
  healthByRule?: Record<string, RuleHealth>;
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
  return (
    <section className="col-span-1 lg:col-span-8 space-y-3">
      {rules.map((r) => (
        <RuleCard
          key={r.id}
          rule={r}
          cameras={cameras}
          selected={selectedRuleId === r.id}
          lastFiredAt={lastFiredByRule[r.id] ?? null}
          health={healthByRule?.[r.id] ?? null}
          onSelect={() => onSelect(r)}
          onToggleEnabled={() => onToggleEnabled(r)}
          onEdit={() => onEdit(r)}
          onDuplicate={() => onDuplicate(r)}
          onDelete={() => onDelete(r.id)}
        />
      ))}
    </section>
  );
}
