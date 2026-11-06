export function ScoreMeter({ value, label }: { value: number; label: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm"><span className="text-fg-2">{label}</span><span className="font-semibold">{Math.round(pct)}</span></div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-white/10" role="meter" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <div className="h-full rounded-full bg-[var(--cg-accent)]" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
