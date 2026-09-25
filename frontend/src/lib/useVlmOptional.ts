"use client";

// Tiny hook over the existing GET /api/providers/health signal. We only
// need its `configured` boolean here: is any VLM/LLM provider set up?
// Reachability and provider details are surfaced elsewhere (the navbar
// badge). Used to decide whether to show the "AI is optional" upsell.

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { PROVIDERS_CHANGED_EVENT } from "@/lib/providers-changed";

interface VlmOptionalState {
  configured: boolean;
  loading: boolean;
}

export function useVlmOptional(): VlmOptionalState {
  const { authFetch } = useAuth();
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await authFetch("/api/providers/health");
        if (res.ok) {
          const data = (await res.json()) as { configured?: boolean };
          if (!cancelled) setConfigured(Boolean(data.configured));
        }
      } catch {
        /* silent: a fetch failure should never block the dashboard */
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    const onChanged = () => {
      setLoading(true);
      void load();
    };
    window.addEventListener(PROVIDERS_CHANGED_EVENT, onChanged);
    return () => {
      cancelled = true;
      window.removeEventListener(PROVIDERS_CHANGED_EVENT, onChanged);
    };
  }, [authFetch]);

  return { configured, loading };
}
