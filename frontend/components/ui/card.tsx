import { cn } from "@/lib/cn";
export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-2xl border border-white/10 bg-white/[0.02] p-6", className)} {...rest}>{children}</div>;
}
