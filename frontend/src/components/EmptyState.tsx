"use client";

import Link from "next/link";

/**
 * One house style for "nothing here yet" screens. Every empty page should
 * say WHY it is empty and WHAT to do next, rather than showing a bare line
 * of text that reads as broken. Pages branch the copy on whether cameras
 * exist: with no cameras the answer is "add one"; with cameras it is
 * "Nurby is still learning".
 */
export function EmptyState({
  icon,
  title,
  body,
  actionLabel,
  actionHref,
  onAction,
}: {
  icon?: React.ReactNode;
  title: string;
  body?: string;
  actionLabel?: string;
  actionHref?: string;
  onAction?: () => void;
}) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-card/30 px-6 py-12 text-center">
      {icon && (
        <div className="w-12 h-12 rounded-full bg-accent/10 border border-accent/30 flex items-center justify-center mx-auto mb-3 text-accent">
          {icon}
        </div>
      )}
      <h3 className="text-sm font-semibold mb-1">{title}</h3>
      {body && (
        <p className="text-xs text-muted-foreground leading-relaxed max-w-sm mx-auto">
          {body}
        </p>
      )}
      {actionLabel && actionHref && (
        <Link
          href={actionHref}
          className="inline-block mt-4 px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 transition-opacity"
        >
          {actionLabel}
        </Link>
      )}
      {actionLabel && onAction && !actionHref && (
        <button
          type="button"
          onClick={onAction}
          className="inline-block mt-4 px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 transition-opacity"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}

/** A small inline camera glyph for the common "add a camera" empty state. */
export function CameraGlyph() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M23 7l-7 5 7 5V7z" />
      <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
    </svg>
  );
}
