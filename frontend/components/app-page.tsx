"use client";

import { AppShell } from "./app-shell";
import { RequireAuth } from "./require-auth";

/**
 * Every signed-in route renders through this wrapper: it enforces the session
 * and mounts the routed shell (sidebar, topbar, announcements, feedback).
 */
export function AppPage({ children, admin = false }: { children: React.ReactNode; admin?: boolean }) {
  return (
    <RequireAuth admin={admin}>
      <AppShell>{children}</AppShell>
    </RequireAuth>
  );
}
