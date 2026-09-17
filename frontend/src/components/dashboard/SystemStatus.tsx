"use client";

import Link from "next/link";
import type { SystemStatus } from "@/lib/systemStatus";

const DOT: Record<string, string> = {
  ok: "bg-green-500 pulse-dot",
  warn: "bg-yellow-500",
  down: "bg-red-500 pulse-dot",
};
const PILL_TEXT: Record<string, string> = {
  ok: "text-muted-foreground hover:text-foreground",
  warn: "text-yellow-500 hover:text-yellow-400",
  down: "text-red-400 hover:text-red-300",
};

// The single header pill. One verdict for the whole system; quiet grey/green
// when healthy, coloured when not. Replaces the separate live + AI pills.
export function SystemStatusPill({ status }: { status: SystemStatus }) {
  return (
    <Link
      href={status.href}
      role="status"
      title={status.detail || "All systems are running."}
      className={`flex items-center gap-2 text-xs transition-colors ${PILL_TEXT[status.level]}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${DOT[status.level]}`} />
      <span className="font-mono hidden md:inline">{status.label}</span>
    </Link>
  );
}

const STRIP_TONE: Record<string, string> = {
  warn: "border-yellow-500/35 bg-yellow-500/10",
  down: "border-red-500/35 bg-red-500/10",
};
const STRIP_DOT: Record<string, string> = {
  warn: "bg-yellow-500",
  down: "bg-red-500",
};
const STRIP_STRONG: Record<string, string> = {
  warn: "text-yellow-500",
  down: "text-red-400",
};

// The single dashboard strip. Shown only when something is wrong; says it
// once, with the detail and a way to look closer. Replaces the two
// full-width banners and the empty-feed re-explanation.
export function SystemStatusStrip({ status }: { status: SystemStatus }) {
  if (status.level === "ok") return null;
  return (
    <div className={`mb-4 flex items-start gap-2.5 rounded-lg border p-3 ${STRIP_TONE[status.level]}`}>
      <span className={`mt-1 h-2 w-2 flex-none rounded-full ${STRIP_DOT[status.level]}`} />
      <p className="text-xs leading-relaxed">
        <span className={`font-semibold ${STRIP_STRONG[status.level]}`}>{status.label}.</span>{" "}
        <span className="text-muted-foreground">{status.detail}</span>{" "}
        <Link href={status.href} className="text-accent hover:underline">System doctor</Link>
      </p>
    </div>
  );
}
