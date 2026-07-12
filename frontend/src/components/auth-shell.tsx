"use client";

import { usePathname } from "next/navigation";
import { AuthProvider, useAuth } from "@/lib/auth";
import { WebSocketProvider } from "@/lib/ws";
import { Navbar } from "@/components/navbar";

const PUBLIC_PATHS = ["/login", "/setup"];

function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { loading } = useAuth();

  // /share/{token} is the anonymous share-link viewer: render it bare
  // (no navbar, no session) like the other public paths.
  const isPublic =
    PUBLIC_PATHS.includes(pathname) || pathname.startsWith("/share/");

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    );
  }

  if (isPublic) {
    return <>{children}</>;
  }

  // WebSocketProvider must wrap the Navbar too, not just the page
  // content: the navbar's LiveStatusBadge reads the socket status, and
  // without a provider it falls back to a permanent "disconnected"
  // (the red "live offline" badge users saw on perfectly healthy
  // systems).
  return (
    <WebSocketProvider>
      <Navbar />
      <main className="flex-1">{children}</main>
    </WebSocketProvider>
  );
}

export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AuthGate>{children}</AuthGate>
    </AuthProvider>
  );
}
