"use client";

import { useState } from "react";

import { ApiError, useAuth } from "@/lib/auth";

// Claim form for a provisional owner account. Nurby drops a first-run
// visitor straight in with an auto-created owner, then nudges them to set
// a real email + password. This modal is the claim step. It is shared by
// the navbar "Secure account" button and the home nudge box so there is
// one form, not two.
export function SecureAccountModal({ onClose }: { onClose: () => void }) {
  const { user, claimAccount } = useAuth();
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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setSubmitting(true);
    try {
      await claimAccount(email.trim(), password, displayName.trim());
      onClose();
    } catch (err) {
      const msg =
        err instanceof ApiError && err.status === 409
          ? "That email is already in use. Try another."
          : err instanceof Error
            ? err.message
            : "Could not secure account.";
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
            <h2 className="text-sm font-semibold">Secure your account</h2>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              Set an email and password so only you can get back in.
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-muted-foreground hover:text-foreground text-lg leading-none"
          >
            &times;
          </button>
        </div>

        <form onSubmit={submit} className="px-5 py-4 space-y-3">
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">
              Your name
            </label>
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Alex"
              className="w-full px-3 py-2 text-sm rounded-md border border-border bg-background focus:border-accent/60 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">
              Email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full px-3 py-2 text-sm rounded-md border border-border bg-background focus:border-accent/60 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">
              Password
            </label>
            <div className="relative">
              <input
                type={showPw ? "text" : "password"}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 8 characters"
                className="w-full px-3 py-2 pr-14 text-sm rounded-md border border-border bg-background focus:border-accent/60 focus:outline-none"
              />
              <button
                type="button"
                onClick={() => setShowPw((s) => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
              >
                {showPw ? "Hide" : "Show"}
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
              Later
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-1.5 text-xs font-medium rounded-md bg-accent text-black hover:bg-accent/90 disabled:opacity-50 transition-colors"
            >
              {submitting ? "Securing..." : "Secure account"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
