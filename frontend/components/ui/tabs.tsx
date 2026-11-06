"use client";
import { cn } from "@/lib/cn";
export function Tabs({ tabs, active, onChange }: { tabs: { id: string; label: string }[]; active: string; onChange: (id: string) => void }) {
  return (
    <div role="tablist" className="flex flex-wrap gap-2">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={active === t.id} onClick={() => onChange(t.id)}
          className={cn("min-h-[44px] rounded-full px-4 py-2 text-sm font-medium transition", active === t.id ? "bg-white text-black" : "border border-white/15 text-fg-2 hover:bg-white/5")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}
