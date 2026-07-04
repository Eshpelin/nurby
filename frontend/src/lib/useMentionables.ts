"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

// Household entities the @-autocomplete can resolve, from
// GET /api/mentions. Cached per page load (module-level), same pattern
// as useRuleSchema.

export type MentionKind = "person" | "camera" | "telegram_channel" | "device";

export interface Mentionable {
  kind: MentionKind;
  id: string;
  name: string;
  hint: string | null;
}

// The shape sent to the backend alongside a question/prompt.
export interface MentionRef {
  kind: MentionKind;
  id: string;
  name: string;
}

let cached: Mentionable[] | null = null;
let inflight: Promise<Mentionable[] | null> | null = null;

export function useMentionables(): { mentionables: Mentionable[]; loading: boolean } {
  const { authFetch } = useAuth();
  const [items, setItems] = useState<Mentionable[]>(cached ?? []);
  const [loading, setLoading] = useState(cached === null);

  useEffect(() => {
    if (cached) return;
    if (!inflight) {
      inflight = authFetch("/api/mentions")
        .then(async (res) => {
          if (!res.ok) return null;
          cached = (await res.json()) as Mentionable[];
          return cached;
        })
        .catch(() => null);
    }
    let alive = true;
    inflight.then((list) => {
      if (!alive) return;
      setItems(list ?? []);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [authFetch]);

  return { mentionables: items, loading };
}
