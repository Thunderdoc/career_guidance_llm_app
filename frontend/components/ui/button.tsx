import { cn } from "@/lib/cn";
export function Button({ className, variant = "primary", ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "outline" }) {
  return <button className={cn("inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl px-5 py-3 text-sm font-medium transition disabled:opacity-50",
    variant === "primary" && "bg-white text-black hover:bg-white/90",
    variant === "ghost" && "text-[var(--cg-fg)] hover:bg-white/5",
    variant === "outline" && "border border-white/15 hover:bg-white/5", className)} {...rest} />;
}
