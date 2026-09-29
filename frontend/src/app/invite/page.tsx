"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { translate, type Locale } from "@/lib/i18n";

// Redeem an admin-issued invite key (Settings → Invite Keys). Linked from
// the login page and from copied invite links (/invite?key=...).
function InviteForm() {
  const { redeemInvite } = useAuth();
  const searchParams = useSearchParams();
  const [locale, setLocale] = useState<Locale>("en");
  const t = (key: string) => translate(locale, key);
  const [inviteKey, setInviteKey] = useState(searchParams.get("key") ?? "");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("nurby.locale");
    if (saved === "en" || saved === "es") setLocale(saved);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await redeemInvite(inviteKey.trim(), email, password, displayName);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("invite_page.create_failed"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("invite_page.title")}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t("invite_page.subtitle")}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-md bg-red-500/10 border border-red-500/20 px-4 py-3 text-sm text-red-400">
              {error}
            </div>
          )}

          <div className="space-y-2">
            <label
              htmlFor="invite-key"
              className="text-sm font-medium text-foreground"
            >
              {t("invite_page.invite_key")}
            </label>
            <input
              id="invite-key"
              type="text"
              required
              autoComplete="off"
              spellCheck={false}
              value={inviteKey}
              onChange={(e) => setInviteKey(e.target.value)}
              className="w-full rounded-md border border-border bg-muted px-3 py-2 font-mono text-sm text-foreground placeholder:font-sans placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder={t("invite_page.invite_key_placeholder")}
            />
          </div>

          <div className="space-y-2">
            <label
              htmlFor="display-name"
              className="text-sm font-medium text-foreground"
            >
              {t("invite_page.name")}
            </label>
            <input
              id="display-name"
              type="text"
              required
              autoComplete="name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full rounded-md border border-border bg-muted px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder={t("invite_page.name_placeholder")}
            />
          </div>

          <div className="space-y-2">
            <label
              htmlFor="email"
              className="text-sm font-medium text-foreground"
            >
              {t("invite_page.email")}
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-border bg-muted px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder={t("invite_page.email_placeholder")}
            />
          </div>

          <div className="space-y-2">
            <label
              htmlFor="password"
              className="text-sm font-medium text-foreground"
            >
              {t("invite_page.password")}
            </label>
            <div className="relative">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                required
                minLength={8}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-md border border-border bg-muted px-3 py-2 pr-16 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent"
                placeholder={t("invite_page.password_placeholder")}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute inset-y-0 right-0 px-3 text-xs text-muted-foreground hover:text-foreground"
                aria-label={showPassword ? t("invite_page.hide_password") : t("invite_page.show_password")}
              >
                {showPassword ? t("invite_page.hide") : t("invite_page.show")}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-accent px-4 py-2 text-sm font-medium text-black transition-colors hover:bg-accent/90 disabled:opacity-50"
          >
            {submitting ? t("invite_page.creating") : t("invite_page.create_account")}
          </button>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          {t("invite_page.already_have_account")} {" "}
          <Link href="/login" className="text-accent hover:underline">
            {t("invite_page.sign_in")}
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function InvitePage() {
  // useSearchParams requires a Suspense boundary during prerender.
  return (
    <Suspense fallback={null}>
      <InviteForm />
    </Suspense>
  );
}
