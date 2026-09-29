"use client";

import { useState } from "react";

import { ApiError, useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

// Claim form for a provisional owner account. Nurby drops a first-run
// visitor straight in with an auto-created owner, then nudges them to set
// a real email + password. This modal is the claim step. It is shared by
// the navbar "Secure account" button and the home nudge box so there is
// one form, not two.
export function SecureAccountModal({ onClose }: { onClose: () => void }) {
  const { user, claimAccount } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const [email, setEmail] = useState(
    user && !user.email.endsWith("@nurby.local") ? user.email : ""
  );
  const [displayName, setDisplayName] = useState(
    user && user.display_name && user.display_name !== "Owner" ? user.display_name : ""
  );
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [secured, setSecured] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError(t("account_security.password_too_short"));
      return;
    }
    setSubmitting(true);
    try {
      const claimedEmail = email.trim();
      await claimAccount(claimedEmail, password, displayName.trim());
      // Show explicit confirmation before closing. Closing silently (or
      // a remount clearing the fields) left users unsure whether the
      // account was actually secured.
      setSecured(claimedEmail);
      setTimeout(onClose, 2000);
      return;
    } catch (err) {
      const msg =
        err instanceof ApiError && err.status === 409
          ? t("account_security.email_in_use")
          : err instanceof Error
            ? err.message
            : t("account_security.secure_failed");
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg border border-border bg-card-elevated shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-5 py-4 border-b border-border">
          <div>
            <h2 className="text-sm font-semibold">{t("account_security.title")}</h2>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              {t("account_security.help")}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label={t("account_security.close")}
            className="text-muted-foreground hover:text-foreground text-lg leading-none"
          >
            &times;
          </button>
        </div>

        {secured ? (
          <div className="px-5 py-6 text-center space-y-2">
            <div className="text-2xl">✓</div>
            <p className="text-sm font-medium">{t("account_security.secured")}</p>
            <p className="text-xs text-muted-foreground">
              {t("account_security.secured_as", { email: secured })}
            </p>
          </div>
        ) : (
        <form onSubmit={submit} className="px-5 py-4 space-y-3">
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">
              {t("account_security.name")}
            </label>
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={t("account_security.name_placeholder")}
              className="w-full px-3 py-2 text-sm rounded-md border border-border bg-background focus:border-accent/60 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">
              {t("account_security.email")}
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t("account_security.email_placeholder")}
              className="w-full px-3 py-2 text-sm rounded-md border border-border bg-background focus:border-accent/60 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">
              {t("account_security.password")}
            </label>
            <div className="relative">
              <input
                type={showPw ? "text" : "password"}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t("account_security.password_placeholder")}
                className="w-full px-3 py-2 pr-14 text-sm rounded-md border border-border bg-background focus:border-accent/60 focus:outline-none"
              />
              <button
                type="button"
                onClick={() => setShowPw((s) => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
              >
                {showPw ? t("account_security.hide") : t("account_security.show")}
              </button>
            </div>
          </div>

          {error && (
            <p className="text-[11px] text-red-400 bg-red-500/10 border border-red-500/30 rounded-md px-2.5 py-1.5">
              {error}
            </p>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground transition-colors"
            >
              {t("account_security.later")}
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-1.5 text-xs font-medium rounded-md bg-accent text-black hover:bg-accent/90 disabled:opacity-50 transition-colors"
            >
              {submitting ? t("account_security.securing") : t("account_security.submit")}
            </button>
          </div>
        </form>
        )}
      </div>
    </div>
  );
}
