"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

// Backend rules vocabulary from GET /api/rules/schema
// (shared/rule_schema.py). Callers fall back to the hardcoded enums in
// types.tsx when `schema` is null (fetch failed or still loading).

export interface RuleSchemaField {
  name: string;
  type: string;
  required: boolean;
  enum?: string[];
  default?: unknown;
  ref?: "camera" | "person" | "telegram_channel";
  description?: string;
}

export interface RuleSchemaEntry {
  type: string;
  label: string;
  description: string;
  group: string;
  fields: RuleSchemaField[];
}

export interface RuleSchema {
  triggers: RuleSchemaEntry[];
  actions: RuleSchemaEntry[];
  conditions: RuleSchemaField[];
  sequence: {
    description: string;
    fields: RuleSchemaField[];
    step_fields: RuleSchemaField[];
  };
}

// Module-level cache: the schema is static per backend version, so one
// fetch per page load is plenty. `null` after a failed fetch keeps us
// from hammering a broken endpoint.
let cached: RuleSchema | null = null;
let inflight: Promise<RuleSchema | null> | null = null;

export function useRuleSchema(): { schema: RuleSchema | null; loading: boolean } {
  const { authFetch } = useAuth();
  const [schema, setSchema] = useState<RuleSchema | null>(cached);
  const [loading, setLoading] = useState(cached === null && inflight !== null);

  useEffect(() => {
    if (cached) return;
    if (!inflight) {
      setLoading(true);
      inflight = authFetch("/api/rules/schema")
        .then(async (res) => {
          if (!res.ok) return null;
          cached = (await res.json()) as RuleSchema;
          return cached;
        })
        .catch(() => null);
    }
    let alive = true;
    inflight.then((s) => {
      if (!alive) return;
      setSchema(s);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [authFetch]);

  return { schema, loading };
}
