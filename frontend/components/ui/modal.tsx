"use client";
export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-label={title} onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#1a1a1a] p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between"><h2 className="font-serif text-xl">{title}</h2>
        <button onClick={onClose} aria-label="Close" className="min-h-[44px] min-w-[44px] rounded-lg hover:bg-white/5">✕</button></div>
        <div className="mt-3">{children}</div>
      </div>
    </div>
  );
}
