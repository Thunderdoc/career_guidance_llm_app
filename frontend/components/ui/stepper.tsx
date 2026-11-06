import { Check } from "lucide-react";
import { cn } from "@/lib/cn";
export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Progress">
      {steps.map((label, i) => (
        <li key={label} className="flex items-center gap-2">
          <span className={cn("flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold",
            i < current && "bg-[var(--cg-success)] text-black", i === current && "bg-white text-black", i > current && "border border-white/20 text-fg-3")}>
            {i < current ? <Check size={14} /> : i + 1}
          </span>
          <span className={cn("text-sm", i === current ? "text-fg" : "text-fg-3")}>{label}</span>
          {i < steps.length - 1 && <span aria-hidden className="mx-1 h-px w-6 bg-white/15" />}
        </li>
      ))}
    </ol>
  );
}
