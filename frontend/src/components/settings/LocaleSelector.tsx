"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { supportedLocales, translate, type Locale } from "@/lib/i18n";
import { setDisplayLocale } from "@/lib/time";

export function LocaleSelector() {
  const { user, authFetch } = useAuth();
  const [locale, setLocale] = useState<Locale>((user?.locale as Locale) || "en");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setDisplayLocale((user?.locale as Locale) || "en");
    if (typeof document !== "undefined") document.documentElement.lang = (user?.locale as Locale) || "en";
  }, [user?.locale]);

  const change = async (next: Locale) => {
    setLocale(next);
    setDisplayLocale(next);
    if (typeof document !== "undefined") document.documentElement.lang = next;
    setSaving(true);
    setSaved(false);
    try {
      const response = await authFetch("/api/auth/me/locale", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ locale: next }),
      });
      if (response.ok) setSaved(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="mb-6 rounded-lg border border-border bg-card p-4" aria-label="Language">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-sm font-medium">{translate(locale, "settings.language")}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{translate(locale, "settings.language_help")}</p>
        </div>
        <select value={locale} disabled={saving} onChange={(event) => void change(event.target.value as Locale)} className="rounded border border-border bg-background px-2 py-1.5 text-sm">
          {supportedLocales.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </div>
      {saved && <p className="mt-2 text-xs text-emerald-400">{translate(locale, "settings.language_saved")}</p>}
    </section>
  );
}
