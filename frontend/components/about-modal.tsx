"use client";

import { AnimatePresence, motion } from "motion/react";
import { X } from "lucide-react";
import { useEffect } from "react";

export function AboutModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="fixed inset-0 z-40 bg-black/60" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
            <motion.div
              role="dialog"
              aria-modal="true"
              aria-label="About"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
              onClick={(e) => e.stopPropagation()}
              className="relative w-full max-w-lg rounded-[20px] bg-panel p-6 shadow-[var(--shadow-lg)] ring-1 ring-white/10"
            >
              <button onClick={onClose} aria-label="Close" className="absolute right-4 top-4 rounded-full bg-bg-3 p-2 text-fg-2 hover:text-fg">
                <X size={16} />
              </button>
              <h2 className="font-serif text-2xl">About Career Guidance AI</h2>
              <div className="mt-3 space-y-3 text-sm text-fg-2">
                <p>
                  Recommends careers from your skills, interests, education, goals and resume. Every match is grounded in the <b className="text-fg">O*NET</b> occupational taxonomy (974 occupations, CC BY 4.0), so skills are real, named competencies — never invented.
                </p>
                <ul className="list-disc space-y-1 pl-5">
                  <li>
                    <b className="text-fg">Offline mode</b> — semantic matching (TF-IDF + competency overlap + interest fit) runs entirely on your server.
                  </li>
                  <li>
                    <b className="text-fg">AI mode</b> — with <code className="mono rounded bg-bg-3 px-1">OPENAI_API_KEY</code>, an LLM writes explanations and plans using only the retrieved occupations (RAG); its output is validated against that context.
                  </li>
                  <li>Salary bands are live (Adzuna) when configured, otherwise labelled estimates by preparation level.</li>
                  <li>Resumes are processed in memory; only a short excerpt is stored with history.</li>
                </ul>
                <p className="text-xs text-fg-3">This is guidance, not a guarantee. Always validate with real job postings and people in the field.</p>
              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
}
