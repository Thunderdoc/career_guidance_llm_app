"use client";

/**
 * Redirect island for the public root: signed-in visitors go to /dashboard.
 * Renders nothing, so the server-rendered landing copy stays in the HTML
 * for anonymous visitors and search engines.
 */
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export function SignedInRedirect() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [user, loading, router]);

  return null;
}
