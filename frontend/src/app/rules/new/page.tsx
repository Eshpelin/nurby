"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { RuleBuilder } from "@/components/rules/RuleBuilder";
import { useRuleRefData } from "@/components/rules/useRuleRefData";
import { findTemplate } from "@/lib/rule-templates";
import { useAuth } from "@/lib/auth";
import type { Rule } from "@/components/rules/types";

// sessionStorage key used to hand a synthetic (non-persisted) rule to
// the create page for the Duplicate and persona-template flows.
export const RULE_PREFILL_KEY = "nurby_rule_prefill";

export default function NewRulePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { authFetch } = useAuth();
  const { cameras, persons, devices, telegramChannels, telegramChannelsLoading, loading } = useRuleRefData();
  const [prefill, setPrefill] = useState<Rule | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  // The generate call costs an LLM round-trip, so make sure the effect's
  // re-runs (strict-mode double mount, the loading flip) fire it once.
  const draftStarted = useRef(false);

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
        return;
      }
    }
    // Deep link: /rules/new?describe=<plain-English request>. Used by
    // Ask Nurby when the user asks the chat to create a rule: the AI
    // drafts the rule from the description and the builder opens
    // pre-filled for review. Falls back to a blank builder on failure.
    const describe = searchParams.get("describe")?.trim();
    if (describe && !draftStarted.current) {
      draftStarted.current = true;
      setDrafting(true);
      (async () => {
        try {
          const res = await authFetch("/api/rules/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt: describe }),
          });
          const j = await res.json().catch(() => ({}));
          if (res.ok && j.rule) {
            setPrefill({ id: "", created_at: new Date().toISOString(), ...j.rule });
          } else {
            setDraftError(
              "Could not draft a rule from your description automatically. Build it below instead.",
            );
          }
        } catch {
          setDraftError(
            "Could not draft a rule from your description automatically. Build it below instead.",
          );
        } finally {
          setDrafting(false);
        }
      })();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  if (loading || drafting) {
    return (
      <div className="px-6 py-20 text-center text-sm text-muted-foreground">
        {drafting ? "Drafting your rule." : "Loading."}
      </div>
    );
  }

  return (
    <>
      {draftError && (
        <div className="mx-6 mt-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-400">
          {draftError}
        </div>
      )}
      <RuleBuilder
        editRule={null}
        prefillRule={prefill}
        cameras={cameras}
        persons={persons}
        devices={devices}
        telegramChannels={telegramChannels}
        telegramChannelsLoading={telegramChannelsLoading}
        onSaved={() => router.push("/rules")}
        onCancel={() => router.push("/rules")}
      />
    </>
  );
}
