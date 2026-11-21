"use client";

/**
 * Voice-first onboarding (/voice) — Kaam-Vaani Stage 4.
 *
 * Guided flow: greet → language → 5 spoken questions (skills,
 * education, city, income, goal) → confirm → Top-5 Kaam-Vaani matches
 * (POST /api/v1/kv/matches, scored for trade profiles — see
 * career_guidance/kaamvaani/matching.py), each with a plain-language
 * "why it fits", a "Simpler" re-explanation, and a gap + free learning
 * path with sources (POST /api/v1/kv/gap-learning, which also moves
 * the session to gap_learning). Every match is listenable, plus a
 * spoken summary; next / hear more / save controls on each card.
 *
 * Voice is free and keyless: the browser's Web Speech API
 * (SpeechRecognition + speechSynthesis, see lib/speech.ts). The mic is
 * one input method among two — the typed fallback next to it runs the
 * exact same flow, so the page is fully usable without a microphone.
 * Nothing is recorded or uploaded by this app; only the text the user
 * reviews and confirms is sent.
 *
 * Server round-trips (backend/kv_voice.py + backend/kv_matching.py,
 * behind the KV_VOICE flag): POST /extract turns the per-question
 * answers into a structured profile (LLM when configured,
 * deterministic otherwise), POST /confirm validates the state-machine
 * transition before anything uses the profile, POST /kv/matches
 * ranks the confirmed profile, and POST /kv/gap-learning validates
 * the matches → gap_learning transition. They degrade gracefully: if
 * the server is unreachable, extraction falls back to the offline
 * extractor in lib/voice-profile.ts, confirmation is mirrored
 * locally, and matching falls back to the anonymous POST /recommend
 * the guest flow uses — the UI says so honestly instead of
 * pretending the server answered. The session lives in sessionStorage
 * (resume if interrupted) and dies with the tab — multi-turn memory
 * is the current session only.
 */
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  BookOpen,
  Bookmark,
  BookmarkCheck,
  Check,
  ChevronRight,
  ExternalLink,
  Lightbulb,
  ListChecks,
  MapPin,
  Mic,
  Minus,
  PenLine,
  Plus,
  Quote,
  Shield,
  Sparkles,
  Square,
  Type,
  Volume2,
  VolumeX,
  Wallet,
  Wrench,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  type KvGapLearningResponse,
  type KvMatch,
  type KvMatchesResponse,
  type KvVoiceProfile,
  type KvVoiceSession,
} from "@/lib/api";
import { kvFlags } from "@/lib/flags";
import { LOCALES, useI18n, type Locale } from "@/lib/i18n";
import {
  buildKvGapSpeech,
  buildKvMatchSpeech,
  buildKvSimpler,
  buildKvSummarySpeech,
  buildKvWhy,
  buildMatchSpeech,
  buildProfileSpeech,
  buildSummarySpeech,
  EXAMPLE_ANSWERS,
  extractProfileFromAnswers,
  interpretYesNo,
  parseIncome,
  profileToInput,
  QUESTION_I18N_KEYS,
  QUESTION_IDS,
  serverProfileToVoiceProfile,
  voiceProfileToServer,
  type QuestionId,
  type VoiceProfile,
} from "@/lib/voice-profile";
import {
  isSpeechRecognitionSupported,
  isSpeechSynthesisSupported,
  speechLanguagesAvailable,
  speak,
  startRecognition,
  stopSpeaking,
  type RecognitionErrorKind,
} from "@/lib/speech";
import type { RecommendResponse, Recommendation } from "@/lib/types";
import { cn } from "@/lib/cn";
import {
  KV_QUESTION_META,
  KvJourney,
  KvMatchMeter,
  KvSoundArt,
  KvWaveform,
  kvCategoryForTitle,
} from "./kv-voice-ui";
import { ErrorNote, Spinner } from "./ui";

const inputCls =
  "mt-2 w-full rounded-xl border border-white/15 bg-transparent px-4 py-3 text-sm outline-none focus:border-accent/60";
const labelCls = "text-sm text-fg-2";

/** sessionStorage key for the resumable session (tab-scoped by design). */
const SESSION_KEY = "kv.voice.session";

/** sessionStorage key for saved matches (guest-first: the device keeps
 * them, the server never sees them). */
const SAVED_KEY = "cg.kv.saved";

type StoredSession = {
  session: KvVoiceSession;
  uiStep: 1 | 2;
  method: string | null;
  offline: boolean;
};

function chipCls(tone: "ok" | "muted") {
  return tone === "ok"
    ? "rounded-full bg-ok/15 px-2.5 py-1 text-xs text-ok"
    : "rounded-full bg-white/5 px-2.5 py-1 text-xs text-fg-2";
}

/** Selected-state tint for each language card on the greet screen. */
const LANG_TINT: Record<Locale, string> = {
  en: "border-accent/60 bg-accent/[0.12]",
  ta: "border-gold/60 bg-gold/[0.12]",
  hi: "border-kv-coral/60 bg-kv-coral/[0.12]",
};

function isLocale(value: string): value is Locale {
  return value === "en" || value === "ta" || value === "hi";
}

function newKvSession(locale: Locale): KvVoiceSession {
  const now = new Date().toISOString();
  return {
    state: "questions",
    language: locale,
    question_index: 0,
    answers: {},
    answer_source: {},
    profile: null,
    confirmed: false,
    remember: false,
    created_at: now,
    updated_at: now,
  };
}

export function VoiceView() {
  const { t, locale, setLocale } = useI18n();
  // 0 greet, 1 questions, 2 confirm, 3 results.
  const [step, setStep] = useState<0 | 1 | 2 | 3>(0);
  const [session, setSession] = useState<KvVoiceSession | null>(null);
  const [pendingResume, setPendingResume] = useState<StoredSession | null>(null);
  const [qIndex, setQIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const [usedVoice, setUsedVoice] = useState(false);
  const [interim, setInterim] = useState("");
  const [listening, setListening] = useState(false);
  const [recogError, setRecogError] = useState<RecognitionErrorKind | null>(null);
  const [recogSupported, setRecogSupported] = useState(true);
  const [ttsAvailable, setTtsAvailable] = useState<Record<Locale, boolean> | null>(null);
  const [profile, setProfile] = useState<VoiceProfile | null>(null);
  const [method, setMethod] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [confirmedOk, setConfirmedOk] = useState(false);
  const [confirmError, setConfirmError] = useState("");
  const [skillsText, setSkillsText] = useState("");
  const [interestsText, setInterestsText] = useState("");
  const [educationText, setEducationText] = useState("");
  const [cityText, setCityText] = useState("");
  const [incomeText, setIncomeText] = useState("");
  const [busy, setBusy] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<RecommendResponse | null>(null);
  // Stage 4: Kaam-Vaani matches (preferred) — the old /recommend result
  // stays as the fallback when the KV endpoint is unreachable.
  const [kvResult, setKvResult] = useState<KvMatchesResponse | null>(null);
  const [kvFallback, setKvFallback] = useState(false);
  const [gapDetails, setGapDetails] = useState<Record<string, KvGapLearningResponse>>({});
  const [gapLoading, setGapLoading] = useState<string | null>(null);
  const [gapError, setGapError] = useState<string | null>(null);
  const [simplerOpen, setSimplerOpen] = useState<Record<string, boolean>>({});
  // Saved matches (guest-first: the device keeps them, the server never
  // sees them). Loaded in the mount effect — never during render, which
  // also runs on the server where sessionStorage does not exist.
  const [savedMatches, setSavedMatches] = useState<string[]>([]);
  const [speaking, setSpeaking] = useState<string | null>(null);
  // Text-size control (spec 4.1): a zoom scale on the voice page, kept
  // in localStorage. Prototype-grade — zoom is supported in
  // Chrome/Safari/Edge (the low-end Android target), not old Firefox.
  const [textScale, setTextScale] = useState(0);
  const recognizer = useRef<{ stop: () => void } | null>(null);
  const autoSpoken = useRef("");

  useEffect(() => {
    setRecogSupported(isSpeechRecognitionSupported());
    if (isSpeechSynthesisSupported()) {
      void speechLanguagesAvailable().then(setTtsAvailable);
    } else {
      setTtsAvailable({ en: false, hi: false, ta: false });
    }
    // Resume: a session interrupted mid-flow offers to continue.
    try {
      const raw = window.sessionStorage.getItem(SESSION_KEY);
      if (raw) {
        const stored = JSON.parse(raw) as StoredSession;
        if (stored.session && Object.keys(stored.session.answers ?? {}).length > 0) {
          setPendingResume(stored);
        }
      }
      const savedRaw = window.sessionStorage.getItem(SAVED_KEY);
      if (savedRaw) {
        const parsed: unknown = JSON.parse(savedRaw);
        if (Array.isArray(parsed)) {
          setSavedMatches(parsed.filter((v): v is string => typeof v === "string"));
        }
      }
      const savedScale = window.localStorage.getItem("kv.textScale");
      if (savedScale === "1" || savedScale === "2") setTextScale(Number(savedScale));
    } catch {
      /* corrupt storage — start fresh */
    }
    return () => {
      recognizer.current?.stop();
      stopSpeaking();
    };
  }, []);

  // Persist the session after every change so a reload resumes the flow.
  // Reaching the results step completes onboarding — the stored session
  // is cleared so a later visit starts fresh instead of "resuming" a
  // finished flow.
  useEffect(() => {
    if (step === 3) {
      try {
        window.sessionStorage.removeItem(SESSION_KEY);
      } catch {
        /* private mode */
      }
      return;
    }
    if (!session || step === 0) return;
    try {
      const stored: StoredSession = {
        session,
        uiStep: step === 2 ? 2 : 1,
        method,
        offline,
      };
      window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(stored));
    } catch {
      /* private mode */
    }
  }, [session, step, method, offline]);

  const canListen = ttsAvailable?.[locale] ?? true;

  // Read-only chip preview of the editable skills text (confirm screen).
  const parsedSkills = skillsText
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const changeTextScale = (delta: number) => {
    const next = Math.max(0, Math.min(2, textScale + delta));
    setTextScale(next);
    try {
      window.localStorage.setItem("kv.textScale", String(next));
    } catch {
      /* private mode */
    }
  };

  const stopMic = useCallback(() => {
    recognizer.current?.stop();
    recognizer.current = null;
    setListening(false);
    setInterim("");
  }, []);

  const speakTracked = useCallback(
    async (id: string, text: string) => {
      const ok = await speak(text, locale, {
        onEnd: () => setSpeaking(null),
        onError: () => setSpeaking(null),
      });
      setSpeaking(ok ? id : null);
    },
    [locale],
  );

  // Auto-speak the current screen's main text once per screen — a
  // Tamil-only speaker should not need to read to follow the flow.
  // Best effort: if the device has no voice for the locale, nothing
  // plays and the on-screen text + tap controls still work. The effect
  // waits until the voice check has resolved (ttsAvailable !== null):
  // speaking before that leaves a stuck "Speaking…" indicator on
  // devices with no voice for the locale (the utterance never ends).
  const qId: QuestionId = QUESTION_IDS[qIndex];
  useEffect(() => {
    if (ttsAvailable === null || !canListen) return;
    let key = "";
    let text = "";
    if (step === 0) {
      key = `greet:${locale}`;
      text = `${t("voice_greet_title")} ${t("voice_greet_body")}`;
    } else if (step === 1) {
      key = `q:${qIndex}:${locale}`;
      text = t(QUESTION_I18N_KEYS[qId].q);
    } else if (step === 2 && profile) {
      key = `confirm:${locale}:${profile.rawText.slice(0, 32)}`;
      text = buildProfileSpeech(profile, t);
    } else if (step === 3 && kvResult && kvResult.matches.length > 0) {
      // Stage 4: speak the matches summary once when the results land —
      // a Tamil-only speaker should hear their matches, not just read them.
      key = `results:${locale}:${kvResult.matches[0].career_id}`;
      text = buildKvSummarySpeech(kvResult.matches, t);
    } else {
      return;
    }
    if (autoSpoken.current === key) return;
    autoSpoken.current = key;
    void speakTracked(key, text);
    // ttsAvailable is a dep (not just canListen): when the voice check
    // resolves, canListen may stay `true` while ttsAvailable flips from
    // null to resolved — the effect must re-run then to speak.
  }, [step, qIndex, qId, locale, canListen, ttsAvailable, profile, kvResult, t, speakTracked]);

  const fillEditFields = (p: VoiceProfile) => {
    setSkillsText(p.skills.join(", "));
    setInterestsText(p.interests);
    setEducationText(p.education);
    setCityText(p.city);
    setIncomeText(p.incomeText);
  };

  const goToQuestion = useCallback(
    (index: number, sess?: KvVoiceSession) => {
      stopMic();
      const s = sess ?? session;
      setQIndex(index);
      setAnswer(s?.answers[QUESTION_IDS[index]] ?? "");
      setUsedVoice(false);
      setRecogError(null);
      setInterim("");
    },
    [session, stopMic],
  );

  /** Record the current question's answer in the session. An empty
   * answer is recorded as skipped — the extractor and the server's
   * state machine both treat "no answer" as a completed question, so
   * the flow never stalls on a question the user can't answer. */
  const saveCurrentAnswer = (source: "voice" | "typed" | "skipped", text: string): KvVoiceSession | null => {
    if (!session) return null;
    const trimmed = text.trim();
    const effectiveSource = source === "skipped" || trimmed.length === 0 ? "skipped" : source;
    const answers = { ...session.answers, [qId]: effectiveSource === "skipped" ? "" : trimmed };
    const answer_source = { ...session.answer_source, [qId]: effectiveSource };
    const remaining = QUESTION_IDS.filter((q) => !(q in answers));
    const question_index = remaining.length > 0 ? QUESTION_IDS.indexOf(remaining[0]) : QUESTION_IDS.length;
    const next: KvVoiceSession = {
      ...session,
      answers,
      answer_source,
      question_index,
      updated_at: new Date().toISOString(),
    };
    setSession(next);
    return next;
  };

  const extractAll = async (sess: KvVoiceSession) => {
    stopMic();
    setExtracting(true);
    setError("");
    let p: VoiceProfile;
    let m: string;
    let off = false;
    let serverProfile: KvVoiceProfile;
    try {
      const res = await api.kvVoiceExtract({ answers: sess.answers, language: locale });
      p = serverProfileToVoiceProfile(res.profile);
      serverProfile = res.profile;
      m = res.method;
    } catch {
      // Server unreachable — the offline extractor runs on the device.
      // The confirm screen says so honestly (voice_offline_note).
      p = extractProfileFromAnswers(sess.answers);
      serverProfile = voiceProfileToServer(p);
      m = "deterministic";
      off = true;
    }
    setProfile(p);
    setMethod(m);
    setOffline(off);
    setSession({ ...sess, state: "confirm", profile: serverProfile, updated_at: new Date().toISOString() });
    fillEditFields(p);
    setExtracting(false);
    setStep(2);
  };

  const startFlow = () => {
    stopMic();
    setSession(newKvSession(locale));
    setQIndex(0);
    setAnswer("");
    setUsedVoice(false);
    setPendingResume(null);
    try {
      window.sessionStorage.removeItem(SESSION_KEY);
    } catch {
      /* private mode */
    }
    setStep(1);
  };

  const resumeSession = () => {
    if (!pendingResume) return;
    const s = pendingResume.session;
    stopMic();
    if (isLocale(s.language)) setLocale(s.language);
    setSession(s);
    setMethod(pendingResume.method);
    setOffline(pendingResume.offline);
    if (pendingResume.uiStep === 2 && s.profile) {
      const p = serverProfileToVoiceProfile(s.profile);
      setProfile(p);
      fillEditFields(p);
      setStep(2);
    } else {
      const index = Math.min(s.question_index, QUESTION_IDS.length - 1);
      setQIndex(index);
      setAnswer(s.answers[QUESTION_IDS[index]] ?? "");
      setUsedVoice(false);
      setStep(1);
    }
    setPendingResume(null);
  };

  const useExample = () => {
    stopMic();
    const answers: Record<string, string> = { ...EXAMPLE_ANSWERS[locale] };
    const answer_source: Record<string, string> = {};
    QUESTION_IDS.forEach((q) => {
      answer_source[q] = "typed";
    });
    const sess: KvVoiceSession = {
      ...newKvSession(locale),
      question_index: QUESTION_IDS.length,
      answers,
      answer_source,
    };
    setSession(sess);
    setPendingResume(null);
    void extractAll(sess);
  };

  const nextQuestion = () => {
    const next = saveCurrentAnswer(usedVoice ? "voice" : "typed", answer);
    if (!next) return;
    if (qIndex + 1 < QUESTION_IDS.length) {
      goToQuestion(qIndex + 1, next);
    } else {
      void extractAll(next);
    }
  };

  const skipQuestion = () => {
    const next = saveCurrentAnswer("skipped", "");
    if (!next) return;
    if (qIndex + 1 < QUESTION_IDS.length) {
      goToQuestion(qIndex + 1, next);
    } else {
      void extractAll(next);
    }
  };

  const prevQuestion = () => {
    if (qIndex === 0) return;
    const next = saveCurrentAnswer(usedVoice ? "voice" : "typed", answer);
    goToQuestion(qIndex - 1, next ?? undefined);
  };

  const toggleMic = () => {
    if (listening) {
      stopMic();
      return;
    }
    setRecogError(null);
    setInterim("");
    setListening(true);
    const handle = startRecognition(locale, {
      onInterim: (text) => setInterim(text),
      onFinal: (text) => {
        setUsedVoice(true);
        setAnswer((prev) => (prev ? `${prev} ${text}` : text));
      },
      onError: (kind) => {
        setRecogError(kind);
        setListening(false);
        setInterim("");
      },
      onEnd: () => {
        setListening(false);
        setInterim("");
      },
    });
    if (!handle) {
      setRecogError("other");
      setListening(false);
      return;
    }
    recognizer.current = handle;
  };

  /** The profile as the user edited it on the confirm screen — the
   * user's edits win over the extracted values, including the income
   * amount, which is re-parsed from the edited text. */
  const editedProfile = (): VoiceProfile | null => {
    if (!profile) return null;
    const income = parseIncome(incomeText);
    return {
      ...profile,
      skills: skillsText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      interests: interestsText,
      education: educationText,
      city: cityText,
      incomeText: income.display || incomeText,
      incomeMonthly: income.amount,
    };
  };

  /** Confirm (voice or tap) then fetch matches. The /confirm POST runs
   * once — if the matches call then fails, the retry goes straight to
   * matching instead of re-confirming an already-confirmed session
   * (the server would 400 that). Stage 4: the Kaam-Vaani /kv/matches
   * endpoint is tried first; only when it is unreachable (network
   * error, or 404/405 because the route is not mounted) does the flow
   * fall back to the anonymous POST /recommend the guest flow uses —
   * a 400 from /kv/matches is a real error and is shown, never
   * hidden behind the fallback. */
  const confirmAndMatch = async () => {
    const edited = editedProfile();
    if (!edited || !session) return;
    stopMic();
    setBusy(true);
    setError("");
    const serverProfile = voiceProfileToServer(edited);
    let confirmedSession: KvVoiceSession = session;
    if (!confirmedOk) {
      const sess: KvVoiceSession = {
        ...session,
        state: "confirm",
        profile: serverProfile,
        updated_at: new Date().toISOString(),
      };
      try {
        const res = await api.kvVoiceConfirm({ session: sess, profile: serverProfile, confirmed: true });
        confirmedSession = res.session;
        setSession(res.session);
      } catch {
        // Offline: mirror the confirm transition locally.
        confirmedSession = { ...sess, state: "matches", confirmed: true };
        setSession(confirmedSession);
      }
      setConfirmedOk(true);
    }
    try {
      const kv = await api.kvMatches({ session: confirmedSession, profile: serverProfile });
      setSession(kv.session);
      setKvResult(kv);
      setKvFallback(false);
      setResult(null);
      setStep(3);
    } catch (kvError) {
      const fallbackOk =
        kvError instanceof ApiError && (kvError.status === 0 || kvError.status === 404 || kvError.status === 405);
      if (!fallbackOk) {
        setError(kvError instanceof Error ? kvError.message : t("error_generic"));
        setBusy(false);
        return;
      }
      try {
        const res = await api.recommend(profileToInput(edited, locale));
        setResult(res);
        setKvFallback(true);
        setKvResult(null);
        if (res.run_id) {
          try {
            window.sessionStorage.setItem(`cg.report.${res.run_id}`, JSON.stringify(res));
          } catch {
            /* private mode */
          }
        }
        setStep(3);
      } catch (e) {
        setError(e instanceof Error ? e.message : t("error_generic"));
      }
    } finally {
      setBusy(false);
    }
  };

  /** "No, change something" — the server-validated decline back to the
   * questions, or the local mirror when the server is unreachable. */
  const declineAndEdit = async () => {
    stopMic();
    stopSpeaking();
    setSpeaking(null);
    setConfirmError("");
    if (session && profile && !confirmedOk) {
      const sessProfile = session.profile ?? voiceProfileToServer(profile);
      const sess: KvVoiceSession = {
        ...session,
        state: "confirm",
        profile: sessProfile,
        updated_at: new Date().toISOString(),
      };
      try {
        const res = await api.kvVoiceConfirm({ session: sess, profile: sessProfile, confirmed: false });
        setSession(res.session);
      } catch {
        setSession({ ...sess, state: "questions", confirmed: false });
      }
    }
    setConfirmedOk(false);
    goToQuestion(0);
    setStep(1);
  };

  /** Voice confirmation: "yes" confirms, "no" declines, anything
   * unclear asks the user to tap instead of guessing. */
  const toggleConfirmMic = () => {
    if (listening) {
      stopMic();
      return;
    }
    setRecogError(null);
    setConfirmError("");
    setInterim("");
    setListening(true);
    const handle = startRecognition(locale, {
      onInterim: (text) => setInterim(text),
      onFinal: (text) => {
        const verdict = interpretYesNo(text, locale);
        if (verdict === "yes") void confirmAndMatch();
        else if (verdict === "no") void declineAndEdit();
        else setConfirmError(t("voice_confirm_unclear"));
      },
      onError: (kind) => {
        setRecogError(kind);
        setListening(false);
        setInterim("");
      },
      onEnd: () => {
        setListening(false);
        setInterim("");
      },
    });
    if (!handle) {
      setRecogError("other");
      setListening(false);
      return;
    }
    recognizer.current = handle;
  };

  const listenQuestion = () => {
    const id = `q-listen-${qIndex}`;
    if (speaking === id) {
      stopSpeaking();
      setSpeaking(null);
      return;
    }
    void speakTracked(id, t(QUESTION_I18N_KEYS[qId].q));
  };

  const listenProfile = () => {
    if (!profile) return;
    if (speaking === "profile") {
      stopSpeaking();
      setSpeaking(null);
      return;
    }
    void speakTracked("profile", buildProfileSpeech(profile, t));
  };

  const listenOne = async (rec: Recommendation, rank: number) => {
    const id = rec.career_id || `rec-${rank}`;
    if (speaking === id) {
      stopSpeaking();
      setSpeaking(null);
      return;
    }
    const ok = await speak(buildMatchSpeech(rec, rank, t), locale, {
      onEnd: () => setSpeaking(null),
      onError: () => setSpeaking(null),
    });
    setSpeaking(ok ? id : null);
  };

  const listenAll = async () => {
    if (!result) return;
    if (speaking === "all") {
      stopSpeaking();
      setSpeaking(null);
      return;
    }
    const ok = await speak(buildSummarySpeech(result.recommendations, t), locale, {
      onEnd: () => setSpeaking(null),
      onError: () => setSpeaking(null),
    });
    setSpeaking(ok ? "all" : null);
  };

  /* ------------------------------------------------------------------ */
  /* Stage 4: spoken Kaam-Vaani results (through the Stage 3 voice      */
  /* gateway's TTS — the browser's speechSynthesis, see lib/speech.ts) */
  /* + gap/learning detail + save.                                      */
  /* ------------------------------------------------------------------ */

  const listenKvOne = async (match: KvMatch, rank: number) => {
    const id = `kv-${match.career_id}`;
    if (speaking === id) {
      stopSpeaking();
      setSpeaking(null);
      return;
    }
    const ok = await speak(buildKvMatchSpeech(match, rank, t), locale, {
      onEnd: () => setSpeaking(null),
      onError: () => setSpeaking(null),
    });
    setSpeaking(ok ? id : null);
  };

  const listenKvAll = async () => {
    if (!kvResult) return;
    if (speaking === "kv-all") {
      stopSpeaking();
      setSpeaking(null);
      return;
    }
    const ok = await speak(buildKvSummarySpeech(kvResult.matches, t), locale, {
      onEnd: () => setSpeaking(null),
      onError: () => setSpeaking(null),
    });
    setSpeaking(ok ? "kv-all" : null);
  };

  /** "Next match": speak the next match in the list (wraps to #1) and
   * scroll it into view. */
  const listenKvNext = async (rank: number) => {
    if (!kvResult || kvResult.matches.length === 0) return;
    const nextIndex = rank % kvResult.matches.length;
    const match = kvResult.matches[nextIndex];
    const id = `kv-${match.career_id}`;
    stopSpeaking();
    const ok = await speak(buildKvMatchSpeech(match, nextIndex + 1, t), locale, {
      onEnd: () => setSpeaking(null),
      onError: () => setSpeaking(null),
    });
    setSpeaking(ok ? id : null);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  /** Load the gap/learning detail for one match (server-validated
   * matches → gap_learning transition). Returns the detail, or null
   * when the server could not be reached. The profile is the edited
   * one the matches were ranked from, so the gap matches the card. */
  const loadGap = async (match: KvMatch): Promise<KvGapLearningResponse | null> => {
    const existing = gapDetails[match.career_id];
    if (existing) return existing;
    const confirmedProfile = editedProfile() ?? profile;
    if (!session || !confirmedProfile) return null;
    setGapLoading(match.career_id);
    setGapError(null);
    try {
      const res = await api.kvGapLearning({
        session,
        profile: voiceProfileToServer(confirmedProfile),
        occupation_id: match.career_id,
      });
      setSession(res.session);
      setGapDetails((prev) => ({ ...prev, [match.career_id]: res }));
      return res;
    } catch (e) {
      setGapError(e instanceof Error ? e.message : t("error_generic"));
      return null;
    } finally {
      setGapLoading(null);
    }
  };

  const toggleGap = (match: KvMatch) => {
    if (gapDetails[match.career_id]) {
      setGapDetails((prev) => {
        const next = { ...prev };
        delete next[match.career_id];
        return next;
      });
      return;
    }
    void loadGap(match);
  };

  /** "Hear more": speak the gap + free learning path for one match
   * (loads it first when the detail is not open yet). */
  const hearMore = async (match: KvMatch) => {
    const detail = gapDetails[match.career_id] ?? (await loadGap(match));
    if (!detail) return;
    const id = `kv-gap-${match.career_id}`;
    if (speaking === id) {
      stopSpeaking();
      setSpeaking(null);
      return;
    }
    const ok = await speak(buildKvGapSpeech(detail, t), locale, {
      onEnd: () => setSpeaking(null),
      onError: () => setSpeaking(null),
    });
    setSpeaking(ok ? id : null);
  };

  /** Save a match on this device (guest-first: the server never sees
   * the saved list). */
  const toggleSave = (careerId: string) => {
    setSavedMatches((prev) => {
      const next = prev.includes(careerId) ? prev.filter((id) => id !== careerId) : [...prev, careerId];
      try {
        window.sessionStorage.setItem(SAVED_KEY, JSON.stringify(next));
      } catch {
        /* private mode */
      }
      return next;
    });
  };

  const startAgain = () => {
    stopSpeaking();
    stopMic();
    setSpeaking(null);
    setSession(null);
    setPendingResume(null);
    setProfile(null);
    setMethod(null);
    setOffline(false);
    setConfirmedOk(false);
    setResult(null);
    setKvResult(null);
    setKvFallback(false);
    setGapDetails({});
    setGapError(null);
    setGapLoading(null);
    setSimplerOpen({});
    setError("");
    setAnswer("");
    setQIndex(0);
    try {
      window.sessionStorage.removeItem(SESSION_KEY);
    } catch {
      /* private mode */
    }
    setStep(0);
  };

  const steps = [t("voice_step_questions"), t("voice_step_confirm"), t("voice_step_results")];
  const stepperCurrent = step === 0 ? 0 : step - 1;
  // Current question's colour + icon (presentation only).
  const qMeta = KV_QUESTION_META[qId];
  const QIcon = qMeta.icon;
  const recogErrorText =
    recogError === "not-allowed"
      ? t("voice_mic_denied")
      : recogError === "no-speech"
        ? t("voice_no_speech")
        : recogError === "other"
          ? t("voice_mic_error")
          : recogError === "network"
            ? t("server_unreachable")
            : "";
  const methodIsAi = method === "llm" || method === "llm-repaired";
  const resumeQuestion = pendingResume
    ? pendingResume.uiStep === 2
      ? QUESTION_IDS.length
      : Math.min(pendingResume.session.question_index + 1, QUESTION_IDS.length)
    : 1;

  // Kaam-Vaani Stage 1: the flag gates the whole page — when KV_VOICE is
  // off the backend route 404s too, so the page must not offer the flow.
  // (Placed after all hooks, so the rules of hooks still hold.)
  if (!kvFlags.voice) {
    return (
      <div className="mx-auto w-full max-w-2xl px-5 pb-20">
        <header className="flex items-center justify-between gap-3 py-6">
          <Link href="/" className="shrink-0 whitespace-nowrap font-serif text-xl">
            Career Guidance AI
          </Link>
          <Link
            href="/start"
            className="text-right text-xs leading-tight text-accent underline decoration-dotted sm:text-sm"
          >
            {t("p1_start_title")}
          </Link>
        </header>
        <p className="mt-6 rounded-xl border border-white/15 px-4 py-3 text-sm text-fg-2">{t("voice_disabled")}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl px-5 pb-20" style={{ zoom: [1, 1.15, 1.3][textScale] }}>
      <header className="flex items-center justify-between gap-3 py-6">
        <Link href="/" className="shrink-0 whitespace-nowrap font-serif text-xl">
          Career Guidance AI
        </Link>
        <Link
          href="/start"
          className="text-right text-xs leading-tight text-accent underline decoration-dotted sm:text-sm"
        >
          {t("p1_start_title")}
        </Link>
      </header>
      {/* Text-size control (spec 4.1) — slim row, right-aligned, always
          available. The zoom scale applies to the whole voice page. */}
      <div className="flex items-center justify-end">
        <div
          className="flex items-center gap-0.5 rounded-full border border-white/10 px-1 py-0.5"
          role="group"
          aria-label="Text size"
        >
          <button
            type="button"
            onClick={() => changeTextScale(-1)}
            disabled={textScale === 0}
            aria-label="Smaller text"
            className="flex h-10 w-10 items-center justify-center rounded-full text-fg-2 transition hover:bg-white/5 disabled:opacity-30"
          >
            <Minus size={15} />
          </button>
          <Type size={15} aria-hidden="true" className="text-fg-3" />
          <button
            type="button"
            onClick={() => changeTextScale(1)}
            disabled={textScale === 2}
            aria-label="Bigger text"
            className="flex h-10 w-10 items-center justify-center rounded-full text-fg-2 transition hover:bg-white/5 disabled:opacity-30"
          >
            <Plus size={15} />
          </button>
        </div>
      </div>
      <h1 className="mt-3 font-serif text-3xl">{t("voice_title")}</h1>
      <p className="mt-2 text-sm text-fg-2">{t("voice_sub")}</p>
      <div className="mt-6">
        <KvJourney steps={steps} current={stepperCurrent} />
      </div>

      {step === 0 && (
        <div className="mt-8">
          {pendingResume && (
            <div className="mb-6 rounded-2xl border border-accent/40 bg-accent/[0.06] px-4 py-4">
              <h2 className="font-serif text-xl">{t("voice_resume_title")}</h2>
              <p className="mt-1 text-sm text-fg-2">
                {t("voice_resume_body", { n: resumeQuestion, total: QUESTION_IDS.length })}
              </p>
              <div className="mt-4 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={resumeSession}
                  className="min-h-[44px] rounded-xl bg-white px-6 py-3 text-sm font-medium text-black transition hover:bg-white/90"
                >
                  {t("voice_resume_yes")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setPendingResume(null);
                    try {
                      window.sessionStorage.removeItem(SESSION_KEY);
                    } catch {
                      /* private mode */
                    }
                  }}
                  className="min-h-[44px] rounded-xl border border-white/15 px-5 py-3 text-sm font-medium transition hover:bg-white/5"
                >
                  {t("voice_resume_no")}
                </button>
              </div>
            </div>
          )}

          {/* Hero — the voice promise, visual first: mic medallion with
              expanding rings, sound-wave art, then the words. */}
          <div className="relative overflow-hidden rounded-3xl border border-accent/25 bg-gradient-to-br from-accent/[0.12] via-panel to-kv-coral/[0.08] px-5 py-6">
            <span
              aria-hidden="true"
              data-decorative="true"
              className="spotlight -left-10 -top-10 h-40 w-40 bg-accent"
            />
            <span
              aria-hidden="true"
              data-decorative="true"
              className="spotlight -bottom-16 -right-8 h-44 w-44 bg-kv-coral"
            />
            <div className="relative flex flex-col items-center text-center">
              <div className="kv-float relative">
                <span
                  aria-hidden="true"
                  className="kv-ring absolute inset-0 rounded-full border-2 border-accent/50"
                />
                <span
                  aria-hidden="true"
                  className="kv-ring absolute inset-0 rounded-full border-2 border-accent/30"
                  style={{ animationDelay: "0.9s" }}
                />
                <span className="relative flex h-20 w-20 items-center justify-center rounded-full bg-accent text-black shadow-[0_0_40px_rgba(0,212,170,0.45)]">
                  <Mic size={36} />
                </span>
              </div>
              <KvSoundArt className="mt-2 h-14 w-full max-w-[280px]" />
              <h2 className="mt-1 font-serif text-2xl">{t("voice_greet_title")}</h2>
              <p className="mt-2 text-sm text-fg-2">{t("voice_greet_body")}</p>
            </div>
          </div>

          {/* Language picker — sets the speech language and the UI locale
              together. Chosen once here; the flow keeps it throughout.
              Big cards, one per language, each with its own tint. */}
          <div className="mt-6">
            <span className={labelCls}>{t("voice_lang_label")}</span>
            <div className="mt-2 grid grid-cols-3 gap-2" role="group" aria-label={t("voice_lang_label")}>
              {LOCALES.map((l) => {
                const selected = locale === l.id;
                return (
                  <button
                    key={l.id}
                    type="button"
                    onClick={() => setLocale(l.id)}
                    aria-pressed={selected}
                    className={cn(
                      "relative min-h-[64px] rounded-2xl border px-3 py-3 text-left transition",
                      selected ? LANG_TINT[l.id] : "border-white/15 text-fg-2 hover:bg-white/5",
                    )}
                  >
                    <span className="block text-base font-semibold text-fg">{l.native}</span>
                    <span className="block text-[11px] text-fg-3">{l.label}</span>
                    {selected && (
                      <span className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-white text-black">
                        <Check size={12} strokeWidth={3} />
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-6 flex flex-col gap-3">
            <button
              type="button"
              onClick={startFlow}
              className="flex min-h-[52px] w-full items-center justify-center gap-2 rounded-2xl bg-accent px-6 py-3.5 text-base font-semibold text-black transition hover:opacity-90"
            >
              {t("voice_greet_start")} <ArrowRight size={18} />
            </button>
            <button
              type="button"
              onClick={useExample}
              className="min-h-[48px] w-full rounded-2xl border border-white/15 px-5 py-3 text-sm font-medium transition hover:bg-white/5"
            >
              {t("voice_try_example")}
            </button>
          </div>
          <div className="mt-6 flex gap-2.5 rounded-2xl bg-white/[0.03] px-4 py-3 ring-1 ring-white/5">
            <Shield size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-fg-3" />
            <p className="text-xs leading-relaxed text-fg-3">{t("voice_privacy")}</p>
          </div>
        </div>
      )}

      {step === 1 && session && (
        <div className="mt-8">
          {/* Question header: icon chip in this question's colour + count. */}
          <div className="flex items-center gap-3">
            <span
              className={cn(
                "flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ring-1",
                qMeta.chip,
              )}
            >
              <QIcon size={22} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">
                {t("voice_question_of", { n: qIndex + 1, total: QUESTION_IDS.length })}
              </p>
              <p className="text-xs text-fg-3">
                {qIndex + 1} / {QUESTION_IDS.length}
              </p>
            </div>
          </div>
          <div
            className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10"
            role="progressbar"
            aria-valuenow={qIndex + 1}
            aria-valuemin={1}
            aria-valuemax={QUESTION_IDS.length}
          >
            <div
              className={cn("h-full rounded-full transition-all", qMeta.bar)}
              style={{ width: `${((qIndex + 1) / QUESTION_IDS.length) * 100}%` }}
            />
          </div>

          <h2 className="mt-6 font-serif text-xl">{t(QUESTION_I18N_KEYS[qId].q)}</h2>
          <p className="mt-1 text-sm text-fg-2">{t(QUESTION_I18N_KEYS[qId].hint)}</p>

          <button
            type="button"
            disabled={!canListen}
            onClick={listenQuestion}
            className="mt-4 flex min-h-[44px] items-center gap-2 rounded-full border border-white/15 px-4 py-2 text-sm font-medium transition hover:bg-white/5 disabled:opacity-40"
          >
            {speaking === `q-listen-${qIndex}` ? <VolumeX size={16} /> : <Volume2 size={16} />}
            {speaking === `q-listen-${qIndex}` ? t("voice_stop") : t("voice_listen_question")}
          </button>
          {!canListen && (
            <p className="mt-2 rounded-xl bg-gold/10 px-3 py-2 text-sm text-gold ring-1 ring-gold/20">
              {t("voice_no_tts")}
            </p>
          )}

          {recogSupported ? (
            <div className={cn("mt-6 flex flex-col items-center gap-3 rounded-3xl px-4 py-6 ring-1 ring-white/5", qMeta.soft)}>
              <div className="relative">
                {listening && (
                  <span
                    aria-hidden
                    className="kv-ring absolute inset-0 rounded-full border-2 border-danger/60"
                  />
                )}
                <button
                  type="button"
                  onClick={toggleMic}
                  aria-label={listening ? t("voice_mic_stop") : t("voice_mic_start")}
                  aria-pressed={listening}
                  className={`relative flex h-24 w-24 items-center justify-center rounded-full transition ${
                    listening
                      ? "bg-[var(--cg-danger)] text-white"
                      : "bg-[var(--cg-accent)] text-black hover:opacity-90"
                  }`}
                >
                  {listening ? <Square size={30} /> : <Mic size={36} />}
                </button>
              </div>
              <KvWaveform active={listening} className={listening ? "text-danger" : "text-accent"} />
              <p className="text-sm font-medium">{listening ? t("voice_listening") : t("voice_mic_start")}</p>
              {interim && (
                <p
                  className="flex w-full gap-2 rounded-2xl bg-bg/60 px-4 py-3 text-sm text-fg ring-1 ring-white/5"
                  aria-live="polite"
                >
                  <Quote size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-fg-3" />
                  <span>{interim}</span>
                </p>
              )}
              {recogErrorText && (
                <p className="w-full rounded-xl bg-gold/10 px-3 py-2 text-center text-sm text-gold ring-1 ring-gold/20">
                  {recogErrorText}
                </p>
              )}
            </div>
          ) : (
            <p className="mt-6 rounded-xl border border-white/15 bg-white/[0.03] px-4 py-3 text-sm text-fg-2">
              {t("voice_unsupported")}
            </p>
          )}

          {/* Typed fallback — always visible next to the mic, same flow. */}
          <div className="mt-6 rounded-2xl bg-panel p-4 ring-1 ring-white/5">
            <label htmlFor="voice-answer" className="flex items-center gap-2 text-sm font-medium">
              <PenLine size={15} aria-hidden="true" className="text-fg-3" />
              {t("voice_answer_label")}
            </label>
            <textarea
              id="voice-answer"
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder={t("voice_type_answer_ph")}
              rows={3}
              className={`${inputCls} resize-y`}
            />
          </div>

          <div className="mt-5 flex flex-col gap-3">
            <button
              type="button"
              disabled={extracting}
              onClick={nextQuestion}
              className="flex min-h-[52px] w-full items-center justify-center gap-2 rounded-2xl bg-accent px-6 py-3.5 text-base font-semibold text-black transition hover:opacity-90 disabled:opacity-40"
            >
              {t("p1_next")} <ArrowRight size={18} />
            </button>
            <div className="flex gap-3">
              <button
                type="button"
                disabled={qIndex === 0 || extracting}
                onClick={prevQuestion}
                className="flex min-h-[48px] flex-1 items-center justify-center gap-2 rounded-2xl border border-white/15 px-5 py-3 text-sm font-medium transition hover:bg-white/5 disabled:opacity-40"
              >
                <ArrowLeft size={16} /> {t("voice_back")}
              </button>
              <button
                type="button"
                disabled={extracting}
                onClick={skipQuestion}
                className="min-h-[48px] flex-1 rounded-2xl border border-white/15 px-5 py-3 text-sm font-medium transition hover:bg-white/5 disabled:opacity-40"
              >
                {t("voice_skip")}
              </button>
            </div>
          </div>
          {extracting && <Spinner label={t("connecting")} />}
        </div>
      )}

      {step === 2 && profile && (
        <div className="mt-8 space-y-5">
          <div>
            <h2 className="font-serif text-xl">{t("voice_confirm_title")}</h2>
            <p className="mt-1 text-sm text-fg-2">{t("voice_confirm_hint")}</p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className={chipCls(methodIsAi ? "ok" : "muted")}>
              {methodIsAi ? t("voice_method_ai") : t("voice_method_offline")}
            </span>
            <button
              type="button"
              disabled={!canListen}
              onClick={listenProfile}
              className="flex min-h-[44px] items-center gap-2 rounded-full border border-white/15 px-4 py-2 text-sm font-medium transition hover:bg-white/5 disabled:opacity-40"
            >
              {speaking === "profile" ? <VolumeX size={16} /> : <Volume2 size={16} />}
              {speaking === "profile" ? t("voice_stop") : t("voice_confirm_listen")}
            </button>
          </div>
          {offline && (
            <p className="rounded-xl border border-white/15 bg-white/[0.03] px-4 py-3 text-sm text-fg-2">
              {t("voice_offline_note")}
            </p>
          )}

          {/* What the user said — a quote card, not a plain box. */}
          <div className="rounded-2xl bg-white/[0.04] px-4 py-3 ring-1 ring-white/10">
            <span className="flex items-center gap-2 text-sm font-medium">
              <Quote size={15} aria-hidden="true" className="text-fg-3" />
              {t("voice_transcript_label")}
            </span>
            <p className="mt-1.5 text-sm leading-relaxed">{profile.rawText}</p>
          </div>

          {/* Profile fields — icon cards, one per field. The skills field
              is a 2-row textarea (a single-line input clipped long text)
              with the parsed skills previewed as chips underneath. */}
          <div className="rounded-2xl bg-panel p-4 ring-1 ring-white/5">
            <label htmlFor="voice-skills" className="flex items-center gap-2 text-sm font-medium">
              <span
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-xl ring-1",
                  KV_QUESTION_META.skills.chip,
                )}
              >
                <Wrench size={15} />
              </span>
              {t("voice_skills_label")}
            </label>
            <textarea
              id="voice-skills"
              value={skillsText}
              onChange={(e) => setSkillsText(e.target.value)}
              placeholder="farming, typing, computer"
              rows={2}
              className={`${inputCls} resize-y`}
            />
            {parsedSkills.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5" aria-hidden="true">
                {parsedSkills.map((s) => (
                  <span key={s} className={chipCls("ok")}>
                    {s}
                  </span>
                ))}
              </div>
            )}
            {skillsText.trim().length === 0 && (
              <p className="mt-2 rounded-xl bg-gold/10 px-3 py-2 text-sm text-gold ring-1 ring-gold/20">
                {t("voice_no_skills")}
              </p>
            )}
          </div>
          <div className="rounded-2xl bg-panel p-4 ring-1 ring-white/5">
            <label htmlFor="voice-interests" className="flex items-center gap-2 text-sm font-medium">
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-kv-violet/15 text-kv-violet ring-1 ring-kv-violet/30">
                <Sparkles size={15} />
              </span>
              {t("voice_interests_label")}
            </label>
            <textarea
              id="voice-interests"
              value={interestsText}
              onChange={(e) => setInterestsText(e.target.value)}
              rows={3}
              className={`${inputCls} resize-y`}
            />
          </div>
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="rounded-2xl bg-panel p-4 ring-1 ring-white/5">
              <label htmlFor="voice-education" className="flex items-center gap-2 text-sm font-medium">
                <span
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-xl ring-1",
                    KV_QUESTION_META.education.chip,
                  )}
                >
                  <BookOpen size={15} />
                </span>
                {t("voice_education_label")}
              </label>
              <input
                id="voice-education"
                value={educationText}
                onChange={(e) => setEducationText(e.target.value)}
                placeholder="12th pass"
                className={inputCls}
              />
            </div>
            <div className="rounded-2xl bg-panel p-4 ring-1 ring-white/5">
              <label htmlFor="voice-city" className="flex items-center gap-2 text-sm font-medium">
                <span
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-xl ring-1",
                    KV_QUESTION_META.city.chip,
                  )}
                >
                  <MapPin size={15} />
                </span>
                {t("voice_city_label")}
              </label>
              <input
                id="voice-city"
                value={cityText}
                onChange={(e) => setCityText(e.target.value)}
                placeholder="Madurai"
                className={inputCls}
              />
            </div>
          </div>
          <div className="rounded-2xl bg-panel p-4 ring-1 ring-white/5">
            <label htmlFor="voice-income" className="flex items-center gap-2 text-sm font-medium">
              <span
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-xl ring-1",
                  KV_QUESTION_META.income.chip,
                )}
              >
                <Wallet size={15} />
              </span>
              {t("voice_income_label")}
            </label>
            <input
              id="voice-income"
              value={incomeText}
              onChange={(e) => setIncomeText(e.target.value)}
              placeholder="₹15,000 / month"
              className={inputCls}
            />
          </div>

          {recogSupported && (
            <div className="rounded-2xl bg-accent/[0.07] p-4 ring-1 ring-accent/20">
              <div className="flex items-center gap-3">
                <div className="relative shrink-0">
                  {listening && (
                    <span
                      aria-hidden
                      className="kv-ring absolute inset-0 rounded-full border-2 border-danger/60"
                    />
                  )}
                  <button
                    type="button"
                    onClick={toggleConfirmMic}
                    aria-label={t("voice_confirm_voice")}
                    aria-pressed={listening}
                    className={`relative flex h-14 w-14 items-center justify-center rounded-full transition ${
                      listening
                        ? "bg-[var(--cg-danger)] text-white"
                        : "bg-[var(--cg-accent)] text-black hover:opacity-90"
                    }`}
                  >
                    {listening ? <Square size={22} /> : <Mic size={26} />}
                  </button>
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium">
                    {listening ? t("voice_listening") : t("voice_confirm_voice")}
                  </p>
                  <KvWaveform active={listening} className={listening ? "text-danger" : "text-accent"} />
                </div>
              </div>
              {interim && (
                <p
                  className="mt-3 flex gap-2 rounded-2xl bg-bg/60 px-4 py-3 text-sm text-fg ring-1 ring-white/5"
                  aria-live="polite"
                >
                  <Quote size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-fg-3" />
                  <span>{interim}</span>
                </p>
              )}
              {confirmError && (
                <p className="mt-2 rounded-xl bg-gold/10 px-3 py-2 text-sm text-gold ring-1 ring-gold/20">
                  {confirmError}
                </p>
              )}
              {recogErrorText && (
                <p className="mt-2 rounded-xl bg-gold/10 px-3 py-2 text-sm text-gold ring-1 ring-gold/20">
                  {recogErrorText}
                </p>
              )}
            </div>
          )}

          <div>
            <ErrorNote error={error} />
          </div>
          <div className="flex flex-col gap-3">
            <button
              type="button"
              disabled={busy}
              onClick={() => void confirmAndMatch()}
              className="min-h-[52px] w-full rounded-2xl bg-accent px-6 py-3.5 text-base font-semibold text-black transition hover:opacity-90 disabled:opacity-40"
            >
              {busy ? t("connecting") : t("voice_confirm_yes")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void declineAndEdit()}
              className="min-h-[48px] w-full rounded-2xl border border-white/15 px-5 py-3 text-sm font-medium transition hover:bg-white/5 disabled:opacity-40"
            >
              {t("voice_confirm_no")}
            </button>
          </div>
          {busy && <Spinner label={t("step_match")} />}
        </div>
      )}

      {step === 3 && kvResult && (
        <div className="mt-8">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-serif text-3xl">{t("voice_results_title")}</h2>
            <span className="rounded-full bg-accent/15 px-2.5 py-1 text-xs font-semibold text-accent ring-1 ring-accent/30">
              {kvResult.matches.length} {t("voice_step_results")}
            </span>
          </div>
          {((profile && profile.skills.length > 0) || profile?.city) && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {profile?.skills.slice(0, 4).map((s) => (
                <span key={s} className={chipCls("muted")}>
                  {s}
                </span>
              ))}
              {profile?.city && <span className={chipCls("muted")}>{profile.city}</span>}
            </div>
          )}
          <button
            type="button"
            disabled={!canListen || kvResult.matches.length === 0}
            onClick={() => void listenKvAll()}
            className="mt-4 flex min-h-[52px] w-full items-center justify-center gap-2 rounded-2xl bg-accent px-5 py-3.5 text-base font-semibold text-black transition hover:opacity-90 disabled:opacity-40"
          >
            {speaking === "kv-all" ? <VolumeX size={18} /> : <Volume2 size={18} />}
            {speaking === "kv-all" ? t("voice_stop") : t("voice_listen_all")}
          </button>
          {!canListen && (
            <p className="mt-2 rounded-xl bg-gold/10 px-3 py-2 text-sm text-gold ring-1 ring-gold/20">
              {t("voice_no_tts")}
            </p>
          )}
          {speaking && <p className="mt-2 text-sm text-fg-2">{t("voice_speaking")}</p>}
          {kvResult.matches.length === 0 && (
            <p className="mt-6 rounded-xl border border-white/15 px-4 py-3 text-sm text-fg-2">
              {t("voice_no_kv_matches")}
            </p>
          )}

          <div className="mt-6 flex flex-col gap-4">
            {kvResult.matches.map((match, i) => {
              const id = `kv-${match.career_id}`;
              const isSpeaking = speaking === id;
              const detail = gapDetails[match.career_id];
              const isSaved = savedMatches.includes(match.career_id);
              const simpler = simplerOpen[match.career_id] ?? false;
              const why = buildKvWhy(match, t);
              const missing = detail
                ? detail.gap.skills.filter((s) => s.status === "missing").map((s) => s.skill)
                : [];
              // Category icon + colour from the occupation title (presentation
              // only — it never changes what is matched).
              const cat = kvCategoryForTitle(match.title);
              const CatIcon = cat.icon;
              const gapTotal = detail
                ? detail.gap.counts.strong + detail.gap.counts.weak + detail.gap.counts.missing
                : 0;
              return (
                <article
                  key={match.career_id}
                  id={id}
                  className="relative overflow-hidden rounded-[var(--radius-lg)] bg-panel p-5 pt-6 ring-1 ring-white/5"
                >
                  <span aria-hidden="true" className={cn("absolute inset-x-0 top-0 h-1", cat.bar)} />
                  <div className="flex items-start gap-3">
                    <span
                      className={cn(
                        "flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ring-1",
                        cat.chip,
                      )}
                    >
                      <CatIcon size={22} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                        #{i + 1} · {t("voice_match")}
                      </p>
                      <h3 className="mt-1 font-serif text-xl leading-snug">{match.title}</h3>
                    </div>
                    <button
                      type="button"
                      onClick={() => toggleSave(match.career_id)}
                      aria-label={`${isSaved ? t("voice_saved") : t("voice_save")}: ${match.title}`}
                      aria-pressed={isSaved}
                      className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full border transition ${
                        isSaved
                          ? "border-accent/60 bg-accent/15 text-accent"
                          : "border-white/15 text-fg-2 hover:bg-white/5"
                      }`}
                    >
                      {isSaved ? <BookmarkCheck size={19} /> : <Bookmark size={19} />}
                    </button>
                  </div>
                  <div className="mt-4">
                    <KvMatchMeter value={match.match_percent} label={t("voice_match")} />
                  </div>
                  {why && (
                    <p className="mt-3 flex gap-2 rounded-xl bg-white/[0.04] px-3 py-2 text-sm text-fg-2 ring-1 ring-white/5">
                      <BadgeCheck size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-ok" />
                      <span>{why}</span>
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={() =>
                      setSimplerOpen((prev) => ({ ...prev, [match.career_id]: !simpler }))
                    }
                    className="mt-3 flex min-h-[44px] items-center gap-2 rounded-full border border-white/15 px-4 py-2 text-sm font-medium transition hover:bg-white/5"
                    aria-expanded={simpler}
                  >
                    <Lightbulb size={16} /> {t("voice_simpler")}
                  </button>
                  {simpler && (
                    <p className="mt-2 rounded-xl bg-white/[0.04] px-3 py-2 text-sm text-fg-2 ring-1 ring-white/5">
                      {buildKvSimpler(match, t)}
                    </p>
                  )}
                  {match.matched_skills.length > 0 && (
                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                      <Check size={14} aria-hidden="true" className="shrink-0 text-ok" />
                      {match.matched_skills.map((s) => (
                        <span key={s} className={chipCls("ok")}>
                          {s}
                        </span>
                      ))}
                    </div>
                  )}
                  {match.missing_skills.length > 0 && (
                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                      <BookOpen size={14} aria-hidden="true" className="shrink-0 text-fg-3" />
                      <span className="text-xs text-fg-2">{t("voice_to_learn")}:</span>
                      {match.missing_skills.slice(0, 4).map((s) => (
                        <span key={s} className={chipCls("muted")}>
                          {s}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="mt-4 flex gap-2">
                    <button
                      type="button"
                      disabled={!canListen}
                      onClick={() => void listenKvOne(match, i + 1)}
                      aria-label={`${t("voice_listen")}: ${match.title}`}
                      className={`flex min-h-[48px] flex-1 items-center justify-center gap-2 rounded-2xl border px-4 py-2 text-sm font-medium transition disabled:opacity-40 ${
                        isSpeaking ? "border-accent/60 bg-white/[0.06]" : "border-white/15 hover:bg-white/5"
                      }`}
                    >
                      {isSpeaking ? <VolumeX size={16} /> : <Volume2 size={16} />}
                      {isSpeaking ? t("voice_stop") : t("voice_listen")}
                    </button>
                    <button
                      type="button"
                      disabled={!canListen || kvResult.matches.length < 2}
                      onClick={() => void listenKvNext(i + 1)}
                      className="flex min-h-[48px] flex-1 items-center justify-center gap-2 rounded-2xl border border-white/15 px-4 py-2 text-sm font-medium transition hover:bg-white/5 disabled:opacity-40"
                    >
                      {t("voice_next_match")} <ArrowRight size={16} />
                    </button>
                  </div>
                  <button
                    type="button"
                    disabled={!canListen}
                    onClick={() => void hearMore(match)}
                    className="mt-2 flex min-h-[48px] w-full items-center justify-center gap-2 rounded-2xl border border-white/15 px-4 py-2 text-sm font-medium transition hover:bg-white/5 disabled:opacity-40"
                  >
                    <Volume2 size={16} /> {t("voice_hear_more")}
                  </button>
                  <button
                    type="button"
                    disabled={gapLoading === match.career_id}
                    onClick={() => toggleGap(match)}
                    className="mt-3 flex min-h-[52px] w-full items-center justify-center gap-2 rounded-2xl bg-accent px-6 py-3.5 text-base font-semibold text-black transition hover:opacity-90 disabled:opacity-40"
                  >
                    {detail ? t("voice_learn_hide") : t("voice_learn_how")}{" "}
                    <ChevronRight size={18} className={cn("transition-transform", detail && "-rotate-90")} />
                  </button>
                  {gapLoading === match.career_id && <Spinner label={t("step_match")} />}
                  {detail && (
                    <div className="mt-5 border-t border-white/10 pt-4">
                      <h4 className="flex items-center gap-2 font-serif text-lg">
                        <ListChecks size={18} aria-hidden="true" className="text-accent" />
                        {t("voice_gap_title")}
                      </h4>
                      {/* Visual skill count: strong (teal) + weak (gold) +
                          missing (grey) dots — countable at a glance. */}
                      <div className="mt-3 flex flex-wrap items-center gap-1.5" aria-hidden="true">
                        {Array.from({ length: detail.gap.counts.strong }).map((_, k) => (
                          <span key={`s${k}`} className="h-3 w-3 rounded-full bg-accent" />
                        ))}
                        {Array.from({ length: detail.gap.counts.weak }).map((_, k) => (
                          <span key={`w${k}`} className="h-3 w-3 rounded-full bg-gold" />
                        ))}
                        {Array.from({ length: detail.gap.counts.missing }).map((_, k) => (
                          <span key={`m${k}`} className="h-3 w-3 rounded-full bg-white/15" />
                        ))}
                        <span className="ml-1 text-xs text-fg-3">{gapTotal}</span>
                      </div>
                      <p className="mt-2 text-sm text-fg-2">
                        {t("voice_gap_have", { n: detail.gap.counts.strong, total: gapTotal })}
                      </p>
                      {missing.length > 0 && (
                        <div className="mt-3 flex flex-wrap items-center gap-1.5">
                          <BookOpen size={14} aria-hidden="true" className="shrink-0 text-fg-3" />
                          <span className="text-xs text-fg-2">{t("voice_to_learn")}:</span>
                          {missing.slice(0, 6).map((s) => (
                            <span key={s} className={chipCls("muted")}>
                              {s}
                            </span>
                          ))}
                        </div>
                      )}
                      <h4 className="mt-5 font-serif text-lg">{t("voice_learning_path")}</h4>
                      {detail.learning_path.length > 0 ? (
                        <ol className="mt-3 space-y-3">
                          {detail.learning_path.map((item, li) => (
                            <li key={item.url} className="flex gap-3">
                              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/[0.07] text-xs font-semibold">
                                {li + 1}
                              </span>
                              <div className="min-w-0">
                                <a
                                  href={item.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-sm text-fg-1 underline decoration-dotted"
                                >
                                  {item.title}
                                </a>
                                <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-fg-3">
                                  <span className={chipCls("muted")}>{item.provider}</span>
                                  {item.free && <span className={chipCls("ok")}>{t("voice_free")}</span>}
                                  <span>{item.source}</span>
                                </p>
                              </div>
                            </li>
                          ))}
                        </ol>
                      ) : (
                        <p className="mt-2 text-sm text-fg-2">{t("voice_learning_none")}</p>
                      )}
                      {detail.citations.length > 0 && (
                        <div className="mt-5">
                          <h4 className="font-serif text-lg">{t("voice_sources")}</h4>
                          <ul className="mt-2 space-y-2 text-sm text-fg-2">
                            {detail.citations.map((citation) => (
                              <li key={citation.source_id} className="flex gap-2">
                                <ExternalLink
                                  size={14}
                                  aria-hidden="true"
                                  className="mt-1 shrink-0 text-fg-3"
                                />
                                <span>
                                  <a
                                    href={citation.url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-fg-1 underline decoration-dotted"
                                  >
                                    {citation.title}
                                  </a>
                                  {citation.date ? (
                                    <span className="text-fg-3"> · {citation.date}</span>
                                  ) : null}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>

          {gapError && <ErrorNote error={gapError} />}

          <p className="mt-6 text-center text-[11px] text-fg-3">
            Guidance, not a guarantee. Data: O*NET 24.1 (CC BY 4.0).
          </p>

          <div className="mt-6">
            <button
              type="button"
              onClick={startAgain}
              className="min-h-[48px] w-full rounded-2xl border border-white/15 px-5 py-3 text-sm font-medium transition hover:bg-white/5"
            >
              {t("voice_start_again")}
            </button>
          </div>
        </div>
      )}

      {step === 3 && result && (
        <div className="mt-8">
          {kvFallback && (
            <p className="mb-4 rounded-xl border border-white/15 px-4 py-3 text-sm text-fg-2">
              {t("voice_kv_fallback")}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-serif text-3xl">{t("voice_results_title")}</h2>
            <span className="rounded-full bg-accent/15 px-2.5 py-1 text-xs font-semibold text-accent ring-1 ring-accent/30">
              {result.recommendations.length} {t("voice_step_results")}
            </span>
          </div>
          {result.detected_skills.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {result.detected_skills.slice(0, 8).map((s) => (
                <span key={s} className={chipCls("muted")}>
                  {s}
                </span>
              ))}
              {result.detected_skills.length > 8 && <span className={chipCls("muted")}>…</span>}
            </div>
          )}
          <p className="mt-2 text-xs text-fg-3">
            {result.provider}
            {result.used_fallback && " · AI unavailable, offline results shown"}
          </p>
          <button
            type="button"
            disabled={!canListen}
            onClick={() => void listenAll()}
            className="mt-4 flex min-h-[52px] w-full items-center justify-center gap-2 rounded-2xl bg-accent px-5 py-3.5 text-base font-semibold text-black transition hover:opacity-90 disabled:opacity-40"
          >
            {speaking === "all" ? <VolumeX size={18} /> : <Volume2 size={18} />}
            {speaking === "all" ? t("voice_stop") : t("voice_listen_all")}
          </button>
          {!canListen && (
            <p className="mt-2 rounded-xl bg-gold/10 px-3 py-2 text-sm text-gold ring-1 ring-gold/20">
              {t("voice_no_tts")}
            </p>
          )}
          {speaking && <p className="mt-2 text-sm text-fg-2">{t("voice_speaking")}</p>}

          <div className="mt-6 flex flex-col gap-4">
            {result.recommendations.map((rec, i) => {
              const id = rec.career_id || `rec-${i + 1}`;
              const isSpeaking = speaking === id;
              const cat = kvCategoryForTitle(rec.title);
              const CatIcon = cat.icon;
              return (
                <article
                  key={id}
                  className="relative overflow-hidden rounded-[var(--radius-lg)] bg-panel p-5 pt-6 ring-1 ring-white/5"
                >
                  <span aria-hidden="true" className={cn("absolute inset-x-0 top-0 h-1", cat.bar)} />
                  <div className="flex items-start gap-3">
                    <span
                      className={cn(
                        "flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ring-1",
                        cat.chip,
                      )}
                    >
                      <CatIcon size={22} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                        #{i + 1} · {rec.suitability}
                      </p>
                      <h3 className="mt-1 font-serif text-xl leading-snug">{rec.title}</h3>
                    </div>
                  </div>
                  <div className="mt-4">
                    <KvMatchMeter value={rec.match_percent} label={t("voice_match")} />
                  </div>
                  <p className="mt-3 flex gap-2 rounded-xl bg-white/[0.04] px-3 py-2 text-sm text-fg-2 ring-1 ring-white/5">
                    <BadgeCheck size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-ok" />
                    <span>{rec.match_reason}</span>
                  </p>
                  {rec.matching_skills.length > 0 && (
                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                      <Check size={14} aria-hidden="true" className="shrink-0 text-ok" />
                      {rec.matching_skills.map((s) => (
                        <span key={s} className={chipCls("ok")}>
                          {s}
                        </span>
                      ))}
                    </div>
                  )}
                  {rec.missing_skills.length > 0 && (
                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                      <BookOpen size={14} aria-hidden="true" className="shrink-0 text-fg-3" />
                      <span className="text-xs text-fg-2">{t("voice_to_learn")}:</span>
                      {rec.missing_skills.slice(0, 4).map((s) => (
                        <span key={s} className={chipCls("muted")}>
                          {s}
                        </span>
                      ))}
                    </div>
                  )}
                  {rec.learning_path.length > 0 && (
                    <ol className="mt-4 space-y-2.5">
                      {rec.learning_path.slice(0, 3).map((stepText, li) => (
                        <li key={stepText} className="flex gap-3 text-sm text-fg-2">
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/[0.07] text-xs font-semibold text-fg">
                            {li + 1}
                          </span>
                          <span>{stepText}</span>
                        </li>
                      ))}
                    </ol>
                  )}
                  <button
                    type="button"
                    disabled={!canListen}
                    onClick={() => void listenOne(rec, i + 1)}
                    aria-label={`${t("voice_listen")}: ${rec.title}`}
                    className={`mt-4 flex min-h-[48px] w-full items-center justify-center gap-2 rounded-2xl border px-4 py-2 text-sm font-medium transition disabled:opacity-40 ${
                      isSpeaking ? "border-accent/60 bg-white/[0.06]" : "border-white/15 hover:bg-white/5"
                    }`}
                  >
                    {isSpeaking ? <VolumeX size={16} /> : <Volume2 size={16} />}
                    {isSpeaking ? t("voice_stop") : t("voice_listen")}
                  </button>
                </article>
              );
            })}
          </div>

          <p className="mt-6 text-center text-[11px] text-fg-3">
            Guidance, not a guarantee. Data: O*NET 24.1 (CC BY 4.0).
          </p>

          <div className="mt-6 flex flex-col gap-3">
            {result.run_id && (
              <Link
                href={`/report/${result.run_id}`}
                className="flex min-h-[52px] w-full items-center justify-center gap-2 rounded-2xl bg-accent px-6 py-3.5 text-base font-semibold text-black transition hover:opacity-90"
              >
                {t("voice_full_report")} <ArrowRight size={18} />
              </Link>
            )}
            <button
              type="button"
              onClick={startAgain}
              className="min-h-[48px] w-full rounded-2xl border border-white/15 px-5 py-3 text-sm font-medium transition hover:bg-white/5"
            >
              {t("voice_start_again")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
