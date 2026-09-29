"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth, ApiError } from "@/lib/auth";
import { translate, type Locale } from "@/lib/i18n";

export default function SetupPage() {
  const { register } = useAuth();
  const router = useRouter();
  const [locale, setLocale] = useState<Locale>("en");
  const t = (key: string) => translate(locale, key);

  useEffect(() => {
    const saved = window.localStorage.getItem("nurby.locale");
    if (saved === "en" || saved === "es") setLocale(saved);
  }, []);

  // If setup is already complete, this form can only 409. Bounce home so
  // an existing install never lands on a doomed "Create account" screen.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/auth/needs-setup");
        if (res.ok) {
          const data = await res.json();
          if (!cancelled && data && data.needs_setup === false) {
            router.replace("/");
          }
        }
      } catch {
        /* stay on the form if the check fails */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  // Email the server rejected as already-in-use. Disables Create until
  // the user changes it, so they can't keep pressing a doomed button.
  const [takenEmail, setTakenEmail] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const emailTaken = takenEmail !== null && email.trim() === takenEmail;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await register(email, password, displayName);
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("setup.failed");
      setError(msg);
      // 409 = email already exists / setup already completed. Remember
      // the email so the button stays disabled until it changes.
      if (err instanceof ApiError && err.status === 409) {
        setTakenEmail(email.trim());
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{t("setup.title")}</h1>
          <p className="text-sm text-muted-foreground">
            {t("setup.subtitle")}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-md bg-red-500/10 border border-red-500/20 px-4 py-3 text-sm text-red-400">
              {error}
            </div>
          )}

          <div className="space-y-2">
            <label htmlFor="display-name" className="text-sm font-medium text-foreground">
              {t("setup.display_name")}
            </label>
            <input
              id="display-name"
              type="text"
              required
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full rounded-md border border-border bg-muted px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder={t("setup.display_name_placeholder")}
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="email" className="text-sm font-medium text-foreground">
              {t("setup.email")}
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={emailTaken}
              className={`w-full rounded-md border bg-muted px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 ${
                emailTaken
                  ? "border-red-500/50 focus:ring-red-500"
                  : "border-border focus:ring-accent"
              }`}
              placeholder={t("setup.email_placeholder")}
            />
            {emailTaken && (
              <p className="text-xs text-red-400">
                {t("setup.email_taken")} {" "}
                <Link href="/login" className="underline">
                  {t("setup.sign_in")}
                </Link>
                .
              </p>
            )}
          </div>

          <div className="space-y-2">
            <label htmlFor="password" className="text-sm font-medium text-foreground">
              {t("setup.password")}
            </label>
            <div className="relative">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                required
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-md border border-border bg-muted px-3 py-2 pr-16 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent"
                placeholder={t("setup.password_placeholder")}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute inset-y-0 right-0 px-3 text-xs text-muted-foreground hover:text-foreground"
                aria-label={showPassword ? t("setup.hide_password") : t("setup.show_password")}
              >
                {showPassword ? t("setup.hide") : t("setup.show")}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting || emailTaken}
            className="w-full rounded-md bg-accent px-4 py-2 text-sm font-medium text-black transition-colors hover:bg-accent/90 disabled:opacity-50"
          >
            {submitting ? t("setup.creating") : t("setup.create_account")}
          </button>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          {t("setup.already_set_up")} {" "}
          <Link href="/login" className="text-accent hover:underline">
            {t("setup.sign_in")}
          </Link>
        </p>
      </div>
    </div>
  );
}
