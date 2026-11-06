import { Info } from "lucide-react";
/** Every figure carries its source + as-of date (Master Prompt Rule 1). */
export function SourceLabel({ source, asOf }: { source: string; asOf?: string }) {
  const text = asOf ? `${source} · as of ${asOf}` : source;
  return <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed text-fg-3" title={text}><Info size={12} className="mt-0.5 shrink-0" aria-hidden /><span>{text}</span></p>;
}
