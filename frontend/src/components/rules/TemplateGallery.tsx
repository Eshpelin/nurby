"use client";

// Starter-template gallery. Rendered as the rules empty state and from
// the persistent "Templates" button on the rules page. Cards offer a
// light camera/person picker; "Use template" builds a synthetic Rule
// and hands it to the caller's prefill flow (RuleBuilder does the rest).

import { useState } from "react";
import {
  CATEGORY_LABELS,
  RULE_TEMPLATES,
  type RuleTemplate,
  type TemplateContext,
  type TemplateParamName,
} from "@/lib/rule-templates";
import { DescribeRuleBox } from "./DescribeRuleBox";
import { StyledSelect } from "./StyledSelect";
import type { Camera, Person, Rule, TelegramChannelOption } from "./types";

export interface TemplateGalleryProps {
  cameras: Camera[];
  persons: Person[];
  telegramChannels: TelegramChannelOption[];
  onUseTemplate: (rule: Rule) => void;
  onCreateBlank?: () => void;
  // Compact mode drops the header (for embedding in a modal).
  compact?: boolean;
}

function TemplateCard({
  template,
  ctx,
  onUse,
}: {
  template: RuleTemplate;
  ctx: TemplateContext;
  onUse: (rule: Rule) => void;
}) {
  const [picked, setPicked] = useState<Partial<Record<TemplateParamName, string>>>({});

  // Only show a picker when there is actually something to pick.
  const visibleParams = template.params.filter((p) =>
    p.name === "camera_id" ? ctx.cameras.length > 1 : ctx.persons.length > 0,
  );

  return (
    <div className="text-left rounded-lg border border-border bg-card p-4 hover:border-accent transition-colors flex flex-col gap-2">
      <div>
        <div className="text-2xl mb-1">{template.icon}</div>
        <div className="font-medium text-sm">{template.title}</div>
        <div className="text-[11px] text-muted-foreground mt-1">{template.blurb}</div>
      </div>
      {visibleParams.map((param) => (
        <StyledSelect
          key={param.name}
          value={picked[param.name] || ""}
          placeholder={param.label}
          options={
            param.name === "camera_id"
              ? ctx.cameras.map((c) => ({ value: c.id, label: c.name }))
              : ctx.persons.map((p) => ({ value: p.id, label: p.display_name }))
          }
          onChange={(v) => setPicked((prev) => ({ ...prev, [param.name]: v }))}
        />
      ))}
      <button
        type="button"
        onClick={() => onUse(template.build(ctx, picked))}
        className="mt-auto self-start px-3 py-1.5 text-xs rounded-md bg-foreground text-background font-medium hover:opacity-90"
      >
        Use template
      </button>
    </div>
  );
}

export function TemplateGallery({
  cameras,
  persons,
  telegramChannels,
  onUseTemplate,
  onCreateBlank,
  compact = false,
}: TemplateGalleryProps) {
  const ctx: TemplateContext = { cameras, persons, telegramChannels };
  const categories = Object.keys(CATEGORY_LABELS) as (keyof typeof CATEGORY_LABELS)[];

  return (
    <div className={compact ? "" : "py-6"}>
      {!compact && (
        <div className="text-center mb-6">
          <h2 className="text-lg font-semibold">Start from a template</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Pick a recipe to prefill the rule builder. Tweak anything before you save.
          </p>
        </div>
      )}
      <div className="max-w-4xl mx-auto mb-6">
        <DescribeRuleBox onGenerated={onUseTemplate} />
      </div>
      <div className="space-y-6 max-w-4xl mx-auto">
        {categories.map((cat) => {
          const templates = RULE_TEMPLATES.filter((t) => t.category === cat);
          if (!templates.length) return null;
          return (
            <div key={cat}>
              <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">
                {CATEGORY_LABELS[cat]}
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {templates.map((t) => (
                  <TemplateCard key={t.key} template={t} ctx={ctx} onUse={onUseTemplate} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      {onCreateBlank && (
        <div className="mt-6 text-center">
          <button
            type="button"
            onClick={onCreateBlank}
            className="text-xs text-muted-foreground hover:text-foreground underline"
          >
            Or start from scratch
          </button>
        </div>
      )}
    </div>
  );
}
