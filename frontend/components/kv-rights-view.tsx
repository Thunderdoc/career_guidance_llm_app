"use client";

/**
 * /rights — rights & safety help (Kaam-Vaani Step 9.1).
 *
 * Plain and functional by design: the design agent owns the polish.
 * Guest-first: no sign-in needed. Answers come only from the
 * knowledge base's rights topics (rights, scam, wages, employment),
 * quoted verbatim with their citation — or the assistant refuses
 * when nothing grounds the answer. A scam question also shows an
 * escalation block of VERIFIED helpline numbers, rendered only from
 * the API response: this file never hardcodes a phone number.
 *
 * English-only in Step 9.1 (L37/L63); the voice flow stays the
 * trilingual surface, and answers are English quotes either way.
 */
import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, Loader2, Phone, Search, ShieldCheck } from "lucide-react";
import { ApiError, api, type KvRightsAnswer } from "@/lib/api";
import { kvFlags } from "@/lib/flags";
import { KvCallout, KvEmptyState, KvHeader, kvBtnGhost, kvBtnPrimary, kvInputCls } from "./kv-portal-ui";

const EXAMPLES = [
  "What is EPF and who gets it?",
  "An employer asked me to pay a registration fee. Is that a scam?",
  "What is the minimum wage for construction work?",
];

export function KvRightsView() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<KvRightsAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(q: string) {
    const trimmed = q.trim();
    if (!trimmed || loading) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      const result = await api.kvRightsAsk({ question: trimmed });
      setAnswer(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the assistant. Try again.");
    } finally {
      setLoading(false);
    }
  }

  if (!kvFlags.rag) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-10">
        <KvEmptyState icon={ShieldCheck}>Rights help is not available right now.</KvEmptyState>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <Link href="/" className={kvBtnGhost}>
        <ArrowLeft size={16} /> Home
      </Link>
      <KvHeader>
        <ShieldCheck size={22} className="text-accent" /> Rights &amp; safety help
      </KvHeader>
      <p className="mt-2 text-sm text-fg-2">
        Ask about worker rights, wages, or scams. Answers come only from the knowledge base, with
        the source shown — if nothing covers your question, the assistant says so instead of
        guessing.
      </p>

      <form
        className="mt-6 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(question);
        }}
      >
        <input
          className={kvInputCls}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about EPF, minimum wage, or a suspected scam…"
          aria-label="Your question"
          maxLength={1000}
        />
        <button type="submit" className={kvBtnPrimary} disabled={loading || !question.trim()}>
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />} Ask
        </button>
      </form>

      <div className="mt-3 flex flex-wrap gap-2">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            className="rounded-full border border-white/15 px-3 py-1 text-xs text-fg-2 transition hover:bg-white/5"
            onClick={() => {
              setQuestion(example);
              void ask(example);
            }}
          >
            {example}
          </button>
        ))}
      </div>

      {error && (
        <KvCallout tone="danger">
          <p>{error}</p>
        </KvCallout>
      )}

      {answer && (
        <section className="mt-6 rounded-xl border border-white/10 bg-white/[0.03] p-4" aria-live="polite">
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{answer.answer}</p>
          {answer.citations.length > 0 && (
            <div className="mt-3 border-t border-white/10 pt-3">
              <p className="text-xs font-medium text-fg-2">Source</p>
              {answer.citations.map((citation) => (
                <p key={citation.source_id} className="mt-1 text-xs text-fg-2">
                  {citation.source_url ? (
                    <a href={citation.source_url} target="_blank" rel="noreferrer" className="underline decoration-dotted">
                      {citation.source_title || citation.source_url}
                    </a>
                  ) : (
                    citation.source_title
                  )}
                  {citation.source_date ? ` (${citation.source_date})` : ""}
                </p>
              ))}
            </div>
          )}
          {answer.escalation.length > 0 && (
            <div className="mt-4">
              <KvCallout tone="warn">
                <p className="font-medium">If you may have been scammed, get help now — these helplines are free:</p>
                <ul className="mt-2 space-y-2">
                  {answer.escalation.map((line) => (
                    <li key={line.number} className="text-sm">
                      <a href={`tel:${line.number}`} className="font-medium underline decoration-dotted">
                        <Phone size={14} className="mr-1 inline" />
                        {line.number}
                      </a>{" "}
                      — {line.name}
                      <span className="block text-xs text-fg-2">{line.purpose}</span>
                      {line.portal && (
                        <a href={line.portal} target="_blank" rel="noreferrer" className="block text-xs underline decoration-dotted">
                          Report online: {line.portal}
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </KvCallout>
            </div>
          )}
          {answer.refused && answer.escalation.length === 0 && (
            <p className="mt-3 text-xs text-fg-2">
              This question is outside what the assistant can answer from its sources. Your
              coordinator can help with the rest.
            </p>
          )}
        </section>
      )}
    </main>
  );
}
