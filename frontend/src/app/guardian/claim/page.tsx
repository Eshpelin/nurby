"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { translate, type Locale } from "@/lib/i18n";

function ClaimForm() {
  const router = useRouter();
  const params = useSearchParams();
  const locale: Locale = typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("es") ? "es" : "en";
  const t = (key: string) => translate(locale, key);
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const valid = token && password.length >= 8 && password === confirm;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!token) {
      setError(t("guardian_claim.missing_token"));
      return;
    }
    if (password.length < 8) {
      setError(t("guardian_claim.password_short"));
      return;
    }
    if (password !== confirm) {
      setError(t("guardian_claim.password_mismatch"));
      return;
    }
    setBusy(true);
    try {
      const res = await fetch("/api/guardian/claim", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password, display_name: name || undefined }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        setError(data?.detail || t("guardian_claim.invalid_invite"));
        setBusy(false);
        return;
      }
      localStorage.setItem("nurby_token", data.token);
      localStorage.setItem("nurby_user", JSON.stringify(data.user));
      router.replace("/guardian");
    } catch {
      setError(t("guardian_claim.generic_error"));
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-lg border border-[hsl(0_0%_14.9%)] bg-[hsl(0_0%_5.5%)] p-7">
        <h1 className="text-xl font-semibold text-foreground">{t("guardian_claim.title")}</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          {t("guardian_claim.subtitle")}
        </p>
        {!token && (
          <p className="mt-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-400">
            {t("guardian_claim.missing_token")}
          </p>
        )}
        <form onSubmit={submit} className="mt-5 space-y-3">
          <input
            type="text"
            placeholder={t("guardian_claim.name_placeholder")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-[hsl(0_0%_14.9%)] bg-[hsl(0_0%_8%)] px-3 py-2 text-sm text-foreground outline-none focus:border-emerald-500"
          />
          <input
            type="password"
            placeholder={t("guardian_claim.password_placeholder")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            className="w-full rounded-md border border-[hsl(0_0%_14.9%)] bg-[hsl(0_0%_8%)] px-3 py-2 text-sm text-foreground outline-none focus:border-emerald-500"
          />
          <input
            type="password"
            placeholder={t("guardian_claim.confirm_placeholder")}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            className="w-full rounded-md border border-[hsl(0_0%_14.9%)] bg-[hsl(0_0%_8%)] px-3 py-2 text-sm text-foreground outline-none focus:border-emerald-500"
          />
          {error && <p className="text-sm text-red-400">{error}</p>}
          <button
            type="submit"
            disabled={!valid || busy}
            className="w-full rounded-md bg-emerald-500 px-3 py-2 text-sm font-medium text-black transition disabled:opacity-40"
          >
            {busy ? t("guardian_claim.setting_up") : t("guardian_claim.submit")}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function GuardianClaimPage() {
  return (
    <Suspense fallback={null}>
      <ClaimForm />
    </Suspense>
  );
}
