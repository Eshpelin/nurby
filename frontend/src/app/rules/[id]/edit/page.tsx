"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";
import { RuleBuilder } from "@/components/rules/RuleBuilder";
import { useRuleRefData } from "@/components/rules/useRuleRefData";
import type { Rule } from "@/components/rules/types";

export default function EditRulePage() {
  const router = useRouter();
  const params = useParams();
  const id = String(params?.id || "");
  const { authFetch, user } = useAuth();
  const t = (key: string) => translate(user?.locale, key);
  const { cameras, persons, devices, telegramChannels, telegramChannelsLoading, loading } = useRuleRefData();

  const [rule, setRule] = useState<Rule | null>(null);
  const [ruleLoading, setRuleLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setRuleLoading(true);
    authFetch(`/api/rules/${id}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: Rule) => {
        if (!cancelled) setRule(data);
      })
      .catch(() => {
        if (!cancelled) setNotFound(true);
      })
      .finally(() => {
        if (!cancelled) setRuleLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id, authFetch]);

  if (loading || ruleLoading) {
    return <div className="px-6 py-20 text-center text-sm text-muted-foreground">{t("rules.loading")}</div>;
  }
  if (notFound || !rule) {
    return (
      <div className="px-6 py-20 text-center text-sm text-muted-foreground">
        {t("rules.not_found")} {" "}
        <button onClick={() => router.push("/rules")} className="text-accent hover:underline">
          {t("rules.back")}
        </button>
      </div>
    );
  }

  return (
    <RuleBuilder
      editRule={rule}
      cameras={cameras}
      persons={persons}
      devices={devices}
      telegramChannels={telegramChannels}
      telegramChannelsLoading={telegramChannelsLoading}
      onSaved={() => router.push("/rules")}
      onCancel={() => router.push("/rules")}
    />
  );
}
