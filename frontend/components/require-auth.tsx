"use client";

/**
 * Reusable route guard.
 *
 * <RequireAuth>        – signed-in users only (redirects to /login?next=…)
 * <RequireAuth admin>  – signed-in AND server-confirmed admin (role comes from
 *                        /api/v1/auth/me, which the backend derives from the DB;
 *                        the API additionally enforces it on every /admin route).
 */
import { motion } from "motion/react";
import { Loader2, ShieldOff } from "lucide-react";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth-context";

export function RequireAuth({ children, admin = false, fallback }: { children: React.ReactNode; admin?: boolean; fallback?: React.ReactNode }) {
  const { user, loading } = useAuth();

  useEffect(() => {
    if (!loading && !user) {
      const next = window.location.pathname + window.location.search;
      window.location.replace(`/login?next=${encodeURIComponent(next)}`);
    }
  }, [user, loading]);

  if (loading || !user) {
    return (
      fallback ?? (
        <div className="flex min-h-[40vh] items-center justify-center" role="status" aria-live="polite">
          <Loader2 className="animate-spin text-fg-3" />
        </div>
      )
    );
  }
  if (admin && !user.is_admin) {
    return (
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="pt-16 text-center">
        <ShieldOff className="mx-auto text-fg-3" />
        <h1 className="mt-4 font-serif text-3xl">Admin only</h1>
        <p className="mt-2 text-sm text-fg-2">Your account ({user.email}) is signed in but is not an administrator.</p>
      </motion.div>
    );
  }
  return <>{children}</>;
}
