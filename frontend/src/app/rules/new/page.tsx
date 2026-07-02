"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { RuleBuilder } from "@/components/rules/RuleBuilder";
import { useRuleRefData } from "@/components/rules/useRuleRefData";
import { findTemplate } from "@/lib/rule-templates";
import type { Rule } from "@/components/rules/types";

// sessionStorage key used to hand a synthetic (non-persisted) rule to
// the create page for the Duplicate and persona-template flows.
export const RULE_PREFILL_KEY = "nurby_rule_prefill";

export default function NewRulePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { cameras, persons, telegramChannels, telegramChannelsLoading, loading } = useRuleRefData();
  const [prefill, setPrefill] = useState<Rule | null>(null);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(RULE_PREFILL_KEY);
      if (raw) {
        setPrefill(JSON.parse(raw));
        sessionStorage.removeItem(RULE_PREFILL_KEY);
        return;
      }
    } catch {
      /* ignore malformed prefill */
    }
    // Deep link: /rules/new?template=<key>. Used by onboarding and the
    // setup checklist. sessionStorage prefill (above) takes precedence.
    const templateKey = searchParams.get("template");
    if (templateKey) {
      const template = findTemplate(templateKey);
      if (template) {
        setPrefill(template.build({ cameras, persons, telegramChannels }));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  if (loading) {
    return <div className="px-6 py-20 text-center text-sm text-muted-foreground">Loading.</div>;
  }

  return (
    <RuleBuilder
      editRule={null}
      prefillRule={prefill}
      cameras={cameras}
      persons={persons}
      telegramChannels={telegramChannels}
      telegramChannelsLoading={telegramChannelsLoading}
      onSaved={() => router.push("/rules")}
      onCancel={() => router.push("/rules")}
    />
  );
}
