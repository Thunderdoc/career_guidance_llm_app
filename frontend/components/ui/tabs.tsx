"use client";

import { useRef } from "react";

import { cn } from "@/lib/cn";

/**
 * Tab list with the WAI-ARIA keyboard pattern (Phase 10 a11y pass):
 * roving tabindex (only the active tab is tabbable), ArrowLeft/Right
 * move + activate, Home/End jump to the ends.
 */
export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  const onKeyDown = (event: React.KeyboardEvent) => {
    const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    const current = Math.max(
      0,
      tabs.findIndex((t) => t.id === active),
    );
    let next = current;
    if (event.key === "ArrowRight") next = (current + 1) % tabs.length;
    if (event.key === "ArrowLeft") next = (current - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    onChange(tabs[next].id);
    listRef.current
      ?.querySelectorAll<HTMLElement>('[role="tab"]')
      [next]?.focus();
  };

  return (
    <div role="tablist" className="flex flex-wrap gap-2" ref={listRef} onKeyDown={onKeyDown}>
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={active === t.id}
          tabIndex={active === t.id ? 0 : -1}
          onClick={() => onChange(t.id)}
          className={cn(
            "min-h-[44px] rounded-full px-4 py-2 text-sm font-medium transition",
            active === t.id
              ? "bg-white text-black"
              : "border border-white/15 text-fg-2 hover:bg-white/5",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
