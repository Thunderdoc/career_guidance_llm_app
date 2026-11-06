"use client";

/**
 * Phase 7 scoped chat panel for /report/[runId].
 *
 * Loaded via next/dynamic from the report view so its code never lands
 * in the report route's first-load bundle. Talks to POST /api/v1/chat:
 * the server re-checks run ownership (signed-in owner or the guest's
 * own anonymous run), scope-checks deterministically, and answers only
 * from that report. Refusals arrive with the i18n key p7_chat_refusal
 * and are rendered localised; failures use the UI-kit's empty/error
 * patterns (EmptyState for the empty thread, inline error line).
 */
import { useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { EmptyState } from "./ui/empty-state";

type Turn = { role: "user" | "assistant"; text: string; offline?: boolean };

export function ChatPanel({ runId }: { runId: number }) {
  const { t } = useI18n();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  const send = async () => {
    const message = draft.trim();
    if (!message || busy) return;
    setDraft("");
    setError(false);
    setBusy(true);
    setTurns((prev) => [...prev, { role: "user", text: message }]);
    try {
      const res = await api.chat(runId, message);
      const text = res.refused ? t("p7_chat_refusal") : res.answer;
      setTurns((prev) => [
        ...prev,
        { role: "assistant", text, offline: res.mode === "offline" },
      ]);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mt-8 rounded-2xl border border-white/10 p-6" aria-label={t("p7_chat_title")}>
      <h2 className="font-serif text-2xl">{t("p7_chat_title")}</h2>
      <p className="mt-1 text-sm text-fg-2">{t("p7_chat_sub")}</p>
      <div className="mt-4 space-y-3" role="log" aria-live="polite" aria-label={t("p7_chat_title")}>
        {turns.length === 0 && <EmptyState title={t("p7_chat_title")} hint={t("p7_chat_empty")} />}
        {turns.map((turn, i) => (
          <div
            key={i}
            className={
              turn.role === "user"
                ? "ml-auto max-w-[85%] rounded-xl bg-white/10 px-4 py-2 text-sm"
                : "mr-auto max-w-[85%] rounded-xl border border-white/10 px-4 py-2 text-sm"
            }
          >
            <p>{turn.text}</p>
            {turn.offline && <p className="mt-1 text-xs text-fg-3">{t("p7_chat_offline")}</p>}
          </div>
        ))}
        {busy && <p className="text-sm text-fg-2">{t("p7_chat_thinking")}</p>}
        {error && (
          <p role="alert" className="text-sm text-red-300">
            {t("p7_chat_error")}
          </p>
        )}
      </div>
      <form
        className="mt-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <label className="sr-only" htmlFor="p7-chat-input">
          {t("p7_chat_title")}
        </label>
        <input
          id="p7-chat-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("p7_chat_placeholder")}
          maxLength={1000}
          className="w-full rounded-xl border border-white/15 bg-transparent px-4 py-2 text-sm outline-none focus:border-white/40"
        />
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          className="rounded-xl bg-white px-4 py-2 text-sm font-medium text-black hover:bg-white/90 disabled:opacity-50"
        >
          {t("p7_chat_send")}
        </button>
      </form>
    </section>
  );
}
