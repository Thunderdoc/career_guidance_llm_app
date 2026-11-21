/**
 * Browser Web Speech API wrapper for the voice flow (/voice).
 *
 * Free, no keys: SpeechRecognition (Chrome/Android) for speech-to-text and
 * speechSynthesis for text-to-speech. No audio is uploaded or stored by this
 * app — transcription is done by the browser's own speech service (in
 * Chrome that service runs on Google's servers; see the privacy note in
 * the voice UI), and only the resulting text is used, after the user has
 * reviewed it.
 *
 * Language codes use the Indian variants first (en-IN / hi-IN / ta-IN):
 * Chrome ships voices for them and recognition accuracy is better for
 * Indian speakers than the generic en-US / hi / ta tags.
 */

import type { Locale } from "./i18n";

/** BCP-47 tag per app locale (recognition + synthesis). */
export const SPEECH_LANG: Record<Locale, string> = {
  en: "en-IN",
  hi: "hi-IN",
  ta: "ta-IN",
};

/** Fallback voice preferences per locale, best first. */
const VOICE_PREFS: Record<Locale, string[]> = {
  en: ["en-IN", "en-GB", "en-US", "en"],
  hi: ["hi-IN", "hi"],
  ta: ["ta-IN", "ta-LK", "ta"],
};

/* -------------------------------------------------------------------------- */
/* Minimal Web Speech API types (the TS DOM lib has no webkit-prefixed ones)   */
/* -------------------------------------------------------------------------- */

export interface SpeechRecognitionAlternative {
  transcript: string;
  confidence: number;
}

export interface SpeechRecognitionResult {
  readonly length: number;
  isFinal: boolean;
  item(index: number): SpeechRecognitionAlternative;
  [index: number]: SpeechRecognitionAlternative;
}

export interface SpeechRecognitionResultList {
  readonly length: number;
  item(index: number): SpeechRecognitionResult;
  [index: number]: SpeechRecognitionResult;
}

export interface SpeechRecognitionEvent extends Event {
  resultIndex: number;
  results: SpeechRecognitionResultList;
}

export interface SpeechRecognitionErrorEvent extends Event {
  error: string;
  message: string;
}

export interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

function recognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as Record<string, unknown>;
  const ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return (typeof ctor === "function" ? (ctor as SpeechRecognitionConstructor) : null);
}

/* -------------------------------------------------------------------------- */
/* Support detection                                                           */
/* -------------------------------------------------------------------------- */

export function isSpeechRecognitionSupported(): boolean {
  return recognitionConstructor() !== null;
}

export function isSpeechSynthesisSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

/* -------------------------------------------------------------------------- */
/* Speech recognition                                                          */
/* -------------------------------------------------------------------------- */

export type RecognitionErrorKind = "not-allowed" | "no-speech" | "network" | "not-supported" | "other";

export type RecognizerCallbacks = {
  /** Interim (not yet final) transcript — update the live display. */
  onInterim: (text: string) => void;
  /** A final transcript chunk — append to the confirmed transcript. */
  onFinal: (text: string) => void;
  onError: (kind: RecognitionErrorKind) => void;
  /** Recognition stopped (user stopped it, or the engine ended the turn). */
  onEnd: () => void;
};

function mapRecognitionError(error: string): RecognitionErrorKind {
  if (error === "not-allowed" || error === "service-not-allowed") return "not-allowed";
  if (error === "no-speech") return "no-speech";
  if (error === "network") return "network";
  return "other";
}

/**
 * Start one recognition turn. Returns a handle with `stop()`; the caller
 * must call `stop()` (or the engine ends the turn itself). The recognizer
 * is created fresh per turn — reusing one across start/stop cycles is
 * where Chrome's implementation gets flaky.
 */
export function startRecognition(
  locale: Locale,
  callbacks: RecognizerCallbacks,
): { stop: () => void } | null {
  const Ctor = recognitionConstructor();
  if (!Ctor) {
    callbacks.onError("not-supported");
    return null;
  }
  const rec = new Ctor();
  rec.lang = SPEECH_LANG[locale];
  rec.continuous = false;
  rec.interimResults = true;
  rec.maxAlternatives = 1;

  rec.onresult = (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      if (result.isFinal) callbacks.onFinal(result[0].transcript);
      else interim += result[0].transcript;
    }
    if (interim) callbacks.onInterim(interim);
  };
  rec.onerror = (event) => callbacks.onError(mapRecognitionError(event.error));
  rec.onend = () => callbacks.onEnd();
  try {
    rec.start();
  } catch {
    callbacks.onError("other");
    return null;
  }
  return {
    stop: () => {
      try {
        rec.stop();
      } catch {
        /* already stopped */
      }
    },
  };
}

/* -------------------------------------------------------------------------- */
/* Speech synthesis                                                            */
/* -------------------------------------------------------------------------- */

function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  return new Promise((resolve) => {
    if (!isSpeechSynthesisSupported()) return resolve([]);
    const synth = window.speechSynthesis;
    const have = synth.getVoices();
    if (have.length > 0) return resolve(have);
    // Chrome loads voices asynchronously; voiceschanged fires when ready.
    const timer = setTimeout(() => resolve(synth.getVoices()), 1500);
    const onChange = () => {
      clearTimeout(timer);
      synth.removeEventListener("voiceschanged", onChange);
      resolve(synth.getVoices());
    };
    synth.addEventListener("voiceschanged", onChange);
  });
}

function pickVoice(voices: SpeechSynthesisVoice[], locale: Locale): SpeechSynthesisVoice | null {
  const prefs = VOICE_PREFS[locale];
  for (const pref of prefs) {
    const exact = voices.find((v) => v.lang.toLowerCase() === pref.toLowerCase());
    if (exact) return exact;
  }
  const base = locale.toLowerCase();
  return voices.find((v) => v.lang.toLowerCase().startsWith(base)) ?? null;
}

/**
 * Which of the app's locales has a synthesis voice in this browser?
 * Used to show honest language support — a locale with no voice is
 * offered for typing/recognition only, never for listen-back.
 */
export async function speechLanguagesAvailable(): Promise<Record<Locale, boolean>> {
  const voices = await loadVoices();
  const out = {} as Record<Locale, boolean>;
  (Object.keys(VOICE_PREFS) as Locale[]).forEach((locale) => {
    out[locale] = pickVoice(voices, locale) !== null;
  });
  return out;
}

export type SpeakCallbacks = {
  onEnd?: () => void;
  onError?: () => void;
};

/**
 * Speak `text` in `locale`. Any in-progress speech is cancelled first so
 * a new Listen tap never queues behind stale audio. Returns false when
 * synthesis is unavailable in this browser.
 */
export async function speak(
  text: string,
  locale: Locale,
  callbacks: SpeakCallbacks = {},
): Promise<boolean> {
  if (!isSpeechSynthesisSupported() || !text.trim()) return false;
  const synth = window.speechSynthesis;
  synth.cancel();
  const voice = pickVoice(await loadVoices(), locale);
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = SPEECH_LANG[locale];
  if (voice) utterance.voice = voice;
  utterance.rate = 0.95;
  utterance.onend = () => callbacks.onEnd?.();
  utterance.onerror = () => callbacks.onError?.();
  synth.speak(utterance);
  return true;
}

export function stopSpeaking(): void {
  if (isSpeechSynthesisSupported()) window.speechSynthesis.cancel();
}
