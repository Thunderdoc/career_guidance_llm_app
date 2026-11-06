"use client";
import { useEffect } from "react";

/**
 * Transient bottom toast. Phase 8 adds an optional action button and a
 * ``sticky`` mode (no auto-dismiss) for messages the user must be able to
 * act on after a pause — e.g. the service worker's "update available".
 */
export function Toast({
  message,
  onDone,
  action,
  sticky = false,
}: {
  message: string;
  onDone?: () => void;
  action?: { label: string; onClick: () => void };
  sticky?: boolean;
}) {
  useEffect(() => {
    if (sticky) return;
    const id = setTimeout(() => onDone?.(), 4000);
    return () => clearTimeout(id);
  }, [onDone, sticky]);
  if (!message) return null;
  return (
    <div role="status" className="fixed bottom-5 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-xl bg-white px-4 py-3 text-sm font-medium text-black shadow-lg">
      <span>{message}</span>
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="shrink-0 rounded-lg bg-black px-3 py-1.5 text-xs font-semibold text-white"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
