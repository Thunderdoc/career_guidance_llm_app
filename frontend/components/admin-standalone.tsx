"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { RequireAuth } from "./require-auth";
import { AdminView } from "./admin-view";

/** /admin — a deep-linkable protected route (the sidebar tab renders the same view). */
export function AdminStandalone() {
  return (
    <main className="mx-auto w-full max-w-[880px] px-4 pb-24 pt-6 sm:px-8">
      <Link href="/" className="mb-4 inline-flex items-center gap-1 text-xs text-fg-3 hover:text-fg">
        <ArrowLeft size={14} /> Back to app
      </Link>
      <RequireAuth admin>
        <AdminView />
      </RequireAuth>
    </main>
  );
}
