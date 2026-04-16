"use client";

import { AuthProvider } from "@/lib/auth";

export function AuthShell({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}
