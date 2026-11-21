/**
 * Voice profile extraction for the voice flow (/voice).
 *
 * Turns a spoken/typed free-text answer ("I finished 12th in Madurai, I
 * know farming and basic computers, I need about fifteen thousand a
 * month") into the structured profile the existing recommendation engine
 * takes. Everything extracted is shown to the user for review and edit
 * before anything is submitted — the mic is an input method, not a
 * black box.
 *
 * Skills come from the app's own vocabulary (voice-vocabulary.ts,
 * generated from data/skill_synonyms.yaml). City, education and income
 * are pattern-matched; anything not recognised stays in the free-text
 * fields so the backend's own extractor still sees the full transcript.
 *
 * This is the OFFLINE fallback: the voice flow normally calls the
 * backend /api/v1/kv/voice/extract endpoint (LLM structured output when
 * configured, deterministic otherwise) and uses this extractor only
 * when the server is unreachable. The two paths share one vocabulary
 * and mirror each other's rules (Stage 3 parity port of
 * career_guidance/kaamvaani/extract.py): Unicode-mark-aware word
 * boundaries, Devanagari/Tamil education and income patterns, digit
 * normalisation, Hindi/Tamil city postpositions, and native-script
 * city aliases (CITY_ALIASES, generated from data/kv_cities.yaml).
 */

import type { Key } from "./i18n";
import type { Locale } from "./i18n";
import type { ProfileInput, Recommendation } from "./types";
import { CITY_ALIASES, SKILL_ALIASES } from "./voice-vocabulary";
import type { KvGapLearningResponse, KvMatch, KvVoiceProfile } from "./api";

export type VoiceProfile = {
  /** Canonical skill names matched from the vocabulary. */
  skills: string[];
  /** Free-text interests (sentences not consumed by the other fields). */
  interests: string;
  /** Education phrase, e.g. "12th pass", "ITI", "" when not mentioned. */
  education: string;
  /** City or town, "" when not mentioned. */
  city: string;
  /** Income need as spoken, e.g. "₹15,000 / month", "" when not mentioned. */
  incomeText: string;
  /** Parsed monthly income in INR, null when not mentioned. */
  incomeMonthly: number | null;
  /** Goal type for the recommend request. */
  goalType: "job_6_months" | "higher_studies" | "explore";
  /** The original transcript, kept for the review screen and fallback. */
  rawText: string;
};

export const EMPTY_PROFILE: VoiceProfile = {
  skills: [],
  interests: "",
  education: "",
  city: "",
  incomeText: "",
  incomeMonthly: null,
  goalType: "explore",
  rawText: "",
};

/* -------------------------------------------------------------------------- */
/* Cities — matched after "from / in / near / at". Indian metros + Tamil      */
/* Nadu districts/towns first (the GAVS audience), then other state towns.    */
/* -------------------------------------------------------------------------- */

const CITIES = [
  "Madurai", "Chennai", "Coimbatore", "Tiruchirappalli", "Trichy", "Salem",
  "Tirunelveli", "Thoothukudi", "Tuticorin", "Erode", "Vellore", "Thanjavur",
  "Dindigul", "Cuddalore", "Kanchipuram", "Tiruppur", "Nagercoil", "Karur",
  "Namakkal", "Villupuram", "Virudhunagar", "Sivakasi", "Srivilliputtur",
  "Rajapalayam", "Theni", "Ramanathapuram", "Pudukkottai", "Nagapattinam",
  "Dharmapuri", "Krishnagiri", "Ariyalur", "Perambalur", "Kanyakumari",
  "Udhagamandalam", "Ooty", "Kodaikanal", "Hosur", "Ambur", "Arakkonam",
  "Delhi", "New Delhi", "Mumbai", "Bengaluru", "Bangalore", "Hyderabad",
  "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Lucknow", "Patna", "Bhopal",
  "Kochi", "Thiruvananthapuram", "Visakhapatnam", "Vijayawada", "Guwahati",
  "Bhubaneswar", "Indore", "Nagpur", "Surat", "Vadodara", "Mysuru", "Mysore",
  "Mangaluru", "Mangalore", "Hubballi", "Warangal", "Guntur", "Nellore",
  "Amritsar", "Ludhiana", "Chandigarh", "Dehradun", "Ranchi", "Raipur",
  "Jodhpur", "Udaipur", "Kota", "Agra", "Varanasi", "Kanpur", "Meerut",
  "Prayagraj", "Allahabad", "Gorakhpur", "Jamshedpur", "Dhanbad", "Asansol",
  "Siliguri", "Kozhikode", "Thrissur", "Kollam", "Alappuzha", "Malappuram",
  "Kannur", "Kottayam", "Palakkad", "Belagavi", "Davanagere", "Ballari",
  "Tumakuru", "Shivamogga", "Kalaburagi", "Vijayapura", "Udupi",
  "Chikkamagaluru", "Hassan", "Mandya", "Raichur", "Bidar", "Kolar",
  "Chitradurga", "Noida", "Gurugram", "Gurgaon", "Faridabad", "Ghaziabad",
  "Aurangabad", "Nashik", "Kolhapur", "Solapur", "Amravati", "Jalgaon",
  "Rajkot", "Bhavnagar", "Jamnagar", "Junagadh", "Anand", "Gandhinagar",
  "Moradabad", "Bareilly", "Aligarh", "Saharanpur", "Muzaffarnagar",
  "Mathura", "Jhansi", "Faizabad", "Ayodhya", "Basti", "Deoria", "Ballia",
  "Gaya", "Muzaffarpur", "Bhagalpur", "Darbhanga", "Purnia", "Arrah",
  "Hajipur", "Katihar", "Munger", "Chapra", "Sasaram", "Siwan", "Motihari",
];

/* -------------------------------------------------------------------------- */
/* Education patterns — phrase (as spoken) mapped to a clean label.           */
/* Native-script alternatives mirror the backend (no trailing \b: a           */
/* combining mark such as the ी in 12वीं is not a word character, so \b       */
/* after it can never match).                                                 */
/* -------------------------------------------------------------------------- */

const EDUCATION_PATTERNS: { re: RegExp; label: string }[] = [
  { re: /\b12\s?th\b|\bclass\s*12\b|\bplus\s*two\b|\b\+2\b|\bhsc\b|\bxii\b|12\s*(?:वीं|वी)|12\s*(?:ஆம்|ம்)\s*வகுப்பு|பன்னிரண்டாம்\s*வகுப்பு|बारहवीं/i, label: "12th pass" },
  { re: /\b10\s?th\b|\bclass\s*10\b|\bsslc\b|\bmetric\b|10\s*(?:वीं|वी)|10\s*(?:ஆம்|ம்)\s*வகுப்பு|பத்தாம்\s*வகுப்பு|दसवीं/i, label: "10th pass" },
  { re: /\b8\s?th\b|\bclass\s*8\b|8\s*(?:वीं|वी)|8\s*(?:ஆம்|ம்)\s*வகுப்பு|எட்டாம்\s*வகுப்பு|आठवीं/i, label: "8th pass" },
  { re: /\biti\b|आईटीआई|ஐடிஐ/i, label: "ITI" },
  { re: /\bdiploma\b|डिप्लोमा|டிப்ளமோ/i, label: "Diploma" },
  { re: /\bb\.?\s?tech\b|\bbtech\b|\bb\.?\s?e\b|\bengineering\b/i, label: "B.Tech" },
  { re: /\bm\.?\s?tech\b|\bmtech\b/i, label: "M.Tech" },
  { re: /\bb\.?\s?sc\b|\bbsc\b/i, label: "B.Sc" },
  { re: /\bm\.?\s?sc\b|\bmsc\b/i, label: "M.Sc" },
  { re: /\bb\.?\s?com\b|\bbcom\b/i, label: "B.Com" },
  { re: /\bm\.?\s?com\b|\bmcom\b/i, label: "M.Com" },
  { re: /\bmba\b/i, label: "MBA" },
  { re: /\bb\.?\s?a\b|\bba\s+degree\b/i, label: "B.A." },
  { re: /\bgraduate\b|\bgraduation\b|\bdegree\b/i, label: "Graduate" },
  { re: /\bdropout\b|\bdropped\s+out\b|\bleft\s+school\b/i, label: "School (incomplete)" },
];

/* -------------------------------------------------------------------------- */
/* Income — ₹ / Rs / rupees / रुपये / ரூபாய் / "k" / thousand / हजार /      */
/* ஆயிரம் / lakh / लाख / லட்சம், monthly. Mirrors the backend INCOME_RE:    */
/* a bare number never matches (it is as likely a year or a phone            */
/* fragment); a currency marker, a unit, or a monthly marker is required.    */
/* -------------------------------------------------------------------------- */

/** Devanagari (०-९) and Tamil (௦-௯) digits → ASCII. */
export function normaliseDigits(text: string): string {
  return text.replace(/[०-९]/g, (d) => String(d.charCodeAt(0) - 0x966)).replace(/[௦-௯]/g, (d) =>
    String(d.charCodeAt(0) - 0xbe6),
  );
}

const INCOME_RE =
  /(?:₹|rs\.?|inr|rupees?|रुपये|रुपया|रू\.?|ரூபாய்|ரூ\.?)\s*([\d,]*\d[\d,]*(?:\.\d+)?)\s*(k|thousand|हज़ार|हजार|ஆயிரம்|lakh|लाख|லட்சம்|l|lac)?|([\d,]*\d[\d,]*(?:\.\d+)?)\s*(k|thousand|हज़ार|हजार|ஆயிரம்|lakh|लाख|லட்சம்|l|lac)\s*(?:per\s*month|monthly|a\s*month|\/month|\bpm\b|महीना|मासिक|மாதம்|மாதாந்திர)?|([\d,]*\d[\d,]*(?:\.\d+)?)\s*(?:₹|rs\.?|inr|rupees?|रुपये|रुपया|रू\.?|ரூபாய்|ரூ\.?)\s*(?:per\s*month|monthly|a\s*month|\/month|\bpm\b|महीना|मासिक|மாதம்|மாதாந்திர)?|([\d,]*\d[\d,]*(?:\.\d+)?)\s*(?:per\s*month|monthly|a\s*month|\/month|\bpm\b|महीना|मासिक|மாதம்|மாதாந்திர)/i;

const UNIT_MULTIPLIER: Record<string, number> = {
  lakh: 100_000,
  लाख: 100_000,
  லட்சம்: 100_000,
  l: 100_000,
  lac: 100_000,
  k: 1_000,
  thousand: 1_000,
  हज़ार: 1_000,
  हजार: 1_000,
  ஆயிரம்: 1_000,
};

/** Amount + display text for a monthly-income mention. Exported so an
 * edited income field can be re-parsed instead of going stale. */
export function parseIncome(text: string): { amount: number | null; display: string } {
  const m = INCOME_RE.exec(normaliseDigits(text));
  if (!m) return { amount: null, display: "" };
  const rawNum = (m[1] ?? m[3] ?? m[5] ?? m[6] ?? "").replace(/,/g, "");
  const unit = (m[2] ?? m[4] ?? "").toLowerCase();
  const num = Number(rawNum);
  if (!Number.isFinite(num) || num <= 0) return { amount: null, display: "" };
  const amount = Math.round(num * (UNIT_MULTIPLIER[unit] ?? 1));
  // Sanity: a monthly income need below ₹500 or above ₹10 lakh is almost
  // certainly a misread (a year, a phone number fragment) — ignore it.
  if (amount < 500 || amount > 1_000_000) return { amount: null, display: "" };
  return { amount, display: `₹${amount.toLocaleString("en-IN")} / month` };
}

/* -------------------------------------------------------------------------- */
/* Skills — longest-alias-first word-boundary scan over the vocabulary.       */
/* -------------------------------------------------------------------------- */

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Word-boundary-ish test that also works for non-Latin scripts, where \b fails.
 * Marks (Unicode category M) count as word characters, so Indic-script
 * words do not split at vowel signs: without this, the alias "कर" (tax)
 * would match inside "नौकरी" (job) — the mirror of the backend's
 * mark-aware check (ASSUMPTIONS.md A16, fixed in Stage 3). */
function containsPhrase(haystack: string, phrase: string): boolean {
  const idx = haystack.indexOf(phrase);
  if (idx === -1) return false;
  const before = idx === 0 ? " " : haystack[idx - 1];
  const after = haystack[idx + phrase.length] ?? " ";
  const isWordChar = (c: string) => /[\p{L}\p{M}\p{N}_]/u.test(c);
  return !isWordChar(before) && !isWordChar(after);
}

function extractSkills(text: string): string[] {
  const lowered = ` ${text.toLowerCase()} `;
  const found: string[] = [];
  const seen = new Set<string>();
  for (const [alias, canonical] of SKILL_ALIASES) {
    if (seen.has(canonical)) continue;
    if (containsPhrase(lowered, alias)) {
      seen.add(canonical);
      found.push(canonical);
    }
  }
  return found;
}

/* -------------------------------------------------------------------------- */
/* Main extraction                                                             */
/* -------------------------------------------------------------------------- */

const JOB_WORDS = /\b(job|work|naukri|velai|kaam|earn|salary|employ|vazhkai|udyog|rozgar)\b/i;
const STUDY_WORDS = /\b(study|college|degree|padhai|learn more|higher studies|university|padippu)\b/i;
const JOB_WORDS_NATIVE = ["வேலை", "சம்பளம்", "நௌகரி", "नौकरी", "काम", "रोजगार", "वेतन", "सैलरी"];
const STUDY_WORDS_NATIVE = ["படிப்பு", "படிக்க", "கல்லூரி", "पढ़ाई", "पढ़ना", "कॉलेज", "यूनिवर्सिटी"];

function extractGoalType(text: string): VoiceProfile["goalType"] {
  if (JOB_WORDS.test(text) || JOB_WORDS_NATIVE.some((w) => text.includes(w))) return "job_6_months";
  if (STUDY_WORDS.test(text) || STUDY_WORDS_NATIVE.some((w) => text.includes(w))) return "higher_studies";
  return "explore";
}

const CITY_PREPOSITIONS = ["from", "in", "near", "at", "around", "mein", "me", "se"];
const CITY_POSTPOSITIONS = ["mein", "me", "se", "la", "le"];

function extractCity(text: string): string {
  const lowered = normaliseDigits(text).toLowerCase();
  for (const city of CITIES) {
    const c = city.toLowerCase();
    const pre = new RegExp(`\\b(?:${CITY_PREPOSITIONS.join("|")})\\s+${escapeRegExp(c)}\\b`, "i");
    const post = new RegExp(`\\b${escapeRegExp(c)}\\s+(?:${CITY_POSTPOSITIONS.join("|")})\\b`, "i");
    if (pre.test(lowered) || post.test(lowered)) return city;
  }
  // Native-script names match by substring (Tamil locatives are suffixes,
  // so word boundaries do not apply) — same rule as the backend.
  for (const [alias, canonical] of CITY_ALIASES) {
    if (lowered.includes(alias)) return canonical;
  }
  return "";
}

/** Match a city in a guided-flow answer WITHOUT a preposition: the answer
 * to "where do you live?" is a location by construction, so a bare
 * "Madurai" counts. Mirrors the backend's match_city_bare. */
export function matchCityBare(answer: string): string {
  const lowered = ` ${normaliseDigits(answer).toLowerCase()} `;
  for (const city of CITIES) {
    if (containsPhrase(lowered, city.toLowerCase())) return city;
  }
  for (const [alias, canonical] of CITY_ALIASES) {
    if (lowered.includes(alias)) return canonical;
  }
  return "";
}

function extractEducation(text: string): string {
  const normalised = normaliseDigits(text);
  for (const { re, label } of EDUCATION_PATTERNS) {
    if (re.test(normalised)) return label;
  }
  return "";
}

export function extractProfile(text: string): VoiceProfile {
  const trimmed = text.trim();
  if (!trimmed) return { ...EMPTY_PROFILE, rawText: "" };

  const skills = extractSkills(trimmed);
  const education = extractEducation(trimmed);
  const city = extractCity(trimmed);
  const income = parseIncome(trimmed);

  // Interests: sentences that did not feed another field, so the user's
  // own words still reach the matcher instead of being thrown away.
  const sentences = trimmed
    .split(/(?<=[.!?])\s+|\n+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const interests = sentences
    .filter((s) => {
      const lower = s.toLowerCase();
      if (education && EDUCATION_PATTERNS.some(({ re }) => re.test(s))) return false;
      if (city && lower.includes(city.toLowerCase())) return false;
      if (income.amount !== null && INCOME_RE.test(s)) return false;
      return true;
    })
    .join(" ")
    .slice(0, 400);

  const goalType = extractGoalType(trimmed);

  return {
    skills,
    interests,
    education,
    city,
    incomeText: income.display,
    incomeMonthly: income.amount,
    goalType,
    rawText: trimmed,
  };
}

/* -------------------------------------------------------------------------- */
/* Guided flow — per-question extraction (mirrors the backend's               */
/* extract_profile_guided) and the server-profile mapper.                    */
/* -------------------------------------------------------------------------- */

/** The guided-flow questions, in order (same ids as the backend). */
export const QUESTION_IDS = ["skills", "education", "city", "income", "goal"] as const;
export type QuestionId = (typeof QUESTION_IDS)[number];

/**
 * Extract a profile from the guided flow's per-question answers. The base
 * extraction runs over the combined transcript; the question context then
 * sharpens it (a bare "Madurai" to the city question counts, the
 * education/income answers are parsed on their own, the skills answer's
 * skills are unioned in). Used as the offline fallback when the server
 * /extract endpoint is unreachable.
 */
export function extractProfileFromAnswers(answers: Partial<Record<QuestionId, string>>): VoiceProfile {
  const ordered = QUESTION_IDS.map((q) => (answers[q] ?? "").trim());
  const combined = ordered.filter(Boolean).join(". ");
  const base = extractProfile(combined);
  const byQuestion = Object.fromEntries(QUESTION_IDS.map((q, i) => [q, ordered[i]])) as Record<
    QuestionId,
    string
  >;
  const city = matchCityBare(byQuestion.city);
  const education = extractEducation(byQuestion.education);
  const income = parseIncome(byQuestion.income);
  const skills = extractSkills(byQuestion.skills);
  const goal = extractGoalType(byQuestion.goal);
  const mergedSkills = [...base.skills];
  for (const skill of skills) {
    if (!mergedSkills.includes(skill)) mergedSkills.push(skill);
  }
  return {
    ...base,
    skills: mergedSkills,
    education: education || base.education,
    city: city || base.city,
    incomeMonthly: income.amount ?? base.incomeMonthly,
    incomeText: income.display || base.incomeText,
    goalType: goal !== "explore" ? goal : base.goalType,
  };
}

/** Map the server's snake_case VoiceProfile to the local camelCase one. */
export function serverProfileToVoiceProfile(server: KvVoiceProfile): VoiceProfile {
  return {
    skills: server.skills,
    interests: server.interests,
    education: server.education,
    city: server.city,
    incomeText: server.income_text,
    incomeMonthly: server.income_monthly,
    goalType:
      server.goal_type === "job_6_months" || server.goal_type === "higher_studies"
        ? server.goal_type
        : "explore",
    rawText: server.raw_text,
  };
}

/** Map the local camelCase VoiceProfile to the server's snake_case one. */
export function voiceProfileToServer(profile: VoiceProfile): KvVoiceProfile {
  return {
    skills: profile.skills,
    interests: profile.interests,
    education: profile.education,
    city: profile.city,
    income_text: profile.incomeText,
    income_monthly: profile.incomeMonthly,
    goal_type: profile.goalType,
    raw_text: profile.rawText,
  };
}

/** i18n keys for each guided-flow question (text + hint). */
export const QUESTION_I18N_KEYS = {
  skills: { q: "voice_q_skills", hint: "voice_q_skills_hint" },
  education: { q: "voice_q_education", hint: "voice_q_education_hint" },
  city: { q: "voice_q_city", hint: "voice_q_city_hint" },
  income: { q: "voice_q_income", hint: "voice_q_income_hint" },
  goal: { q: "voice_q_goal", hint: "voice_q_goal_hint" },
} as const;

/* -------------------------------------------------------------------------- */
/* Voice confirmation — yes/no words per locale (for "say yes to confirm").   */
/* Short Latin words match on word boundaries ("no" must not fire inside     */
/* "know"); longer and native-script words match by substring.               */
/* -------------------------------------------------------------------------- */

const YES_WORDS: Record<Locale, string[]> = {
  en: ["yes", "yeah", "yep", "correct", "right", "okay", "ok"],
  hi: ["हाँ", "हां", "जी", "सही", "haan", "han", "ji", "sahi", "yes"],
  ta: ["ஆமாம்", "ஆமா", "சரி", "aama", "aamaa", "sari", "yes"],
};

const NO_WORDS: Record<Locale, string[]> = {
  en: ["no", "nope", "wrong", "not right", "incorrect"],
  hi: ["नहीं", "ना", "गलत", "nahi", "na", "galat", "no"],
  ta: ["இல்லை", "இல்ல", "தவறு", "illa", "illai", "thappu", "no"],
};

function wordMatches(transcript: string, word: string): boolean {
  const isShortLatin = /^[a-z]{1,3}$/.test(word);
  if (isShortLatin) {
    return new RegExp(`\\b${escapeRegExp(word)}\\b`).test(transcript);
  }
  return transcript.includes(word);
}

/** "yes" / "no" / "unclear" for a voice-confirmation transcript. A
 * transcript matching both sides (or neither) is unclear — the UI then
 * asks the user to tap instead of guessing. */
export function interpretYesNo(transcript: string, locale: Locale): "yes" | "no" | "unclear" {
  const lowered = transcript.toLowerCase();
  const yes = YES_WORDS[locale].some((w) => wordMatches(lowered, w.toLowerCase()));
  const no = NO_WORDS[locale].some((w) => wordMatches(lowered, w.toLowerCase()));
  if (yes && !no) return "yes";
  if (no && !yes) return "no";
  return "unclear";
}

/* -------------------------------------------------------------------------- */
/* Profile → recommend request (the same endpoint the guest flow uses).        */
/* -------------------------------------------------------------------------- */

export function profileToInput(profile: VoiceProfile, language: Locale): ProfileInput {
  // Skills: the matched canonicals. When nothing matched, pass the raw
  // transcript — the backend's own extractor still finds skills in it,
  // so a user is never punished for the client vocabulary missing a word.
  const skills = profile.skills.length > 0 ? profile.skills.join(", ") : profile.rawText;
  const goals = [
    profile.goalType,
    profile.incomeText ? `Needs to earn ${profile.incomeText}` : "",
  ]
    .filter(Boolean)
    .join(". ");
  return {
    skills,
    interests: profile.interests,
    education: profile.education,
    experience_level: "Student / No experience",
    goals,
    resume_text: "",
    constraints: {
      persona: "school",
      city: profile.city,
      relocate: false,
      hours_per_week: 6,
      budget_range: "Free only",
      language,
      goal_type: profile.goalType,
    },
  };
}

/* -------------------------------------------------------------------------- */
/* Spoken text — built only from the real recommendation data. Career titles  */
/* and reasons stay English (O*NET data is English); the wrapper sentences    */
/* follow the selected locale.                                                 */
/* -------------------------------------------------------------------------- */

type T = (key: Key, vars?: Record<string, string | number>) => string;

function joinList(items: string[]): string {
  if (items.length === 0) return "";
  if (items.length === 1) return items[0];
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** One career, read aloud: rank, title, match %, reason, have/learn. */
export function buildMatchSpeech(rec: Recommendation, rank: number, t: T): string {
  const parts = [
    t("voice_speak_match", { n: rank, title: rec.title, pct: Math.round(rec.match_percent) }),
    rec.match_reason,
  ];
  if (rec.matching_skills.length > 0) {
    parts.push(t("voice_speak_have", { skills: joinList(rec.matching_skills.slice(0, 4)) }));
  }
  if (rec.missing_skills.length > 0) {
    parts.push(t("voice_speak_learn", { skills: joinList(rec.missing_skills.slice(0, 3)) }));
  }
  return parts.filter(Boolean).join(" ");
}

/** Short summary of all matches, for "Listen to my matches". */
export function buildSummarySpeech(recs: Recommendation[], t: T): string {
  if (recs.length === 0) return "";
  const lines = [t("voice_speak_intro", { n: recs.length })];
  recs.forEach((rec, i) => {
    lines.push(t("voice_speak_match", { n: i + 1, title: rec.title, pct: Math.round(rec.match_percent) }));
  });
  return lines.join(" ");
}

/* -------------------------------------------------------------------------- */
/* Kaam-Vaani matches (Stage 4) — why-it-fits, simpler explanation, spoken    */
/* results. Career titles and skill names stay English (O*NET data is        */
/* English); the wrapper sentences follow the selected locale.                */
/* -------------------------------------------------------------------------- */

/** Plain-language "why it fits" for one match, composed from the
 * structured reasons the backend returned (never invented): the skills
 * the user already has, whether the job name matches what they said,
 * whether it can pay what they need, whether it fits their education. */
export function buildKvWhy(match: KvMatch, t: T): string {
  const parts: string[] = [];
  for (const reason of match.reasons) {
    if (reason.kind === "skill" && reason.skills && reason.skills.length > 0) {
      parts.push(t("voice_why_skills", { skills: joinList(reason.skills.slice(0, 3)) }));
    } else if (reason.kind === "title") {
      parts.push(t("voice_why_title"));
    } else if (reason.kind === "income") {
      parts.push(t("voice_why_income"));
    } else if (reason.kind === "zone") {
      parts.push(t("voice_why_zone"));
    }
  }
  return parts.join(" ");
}

/** "Simpler" re-explanation (Class 6–8 reading level): one short
 * sentence — what the job is, what the user already knows, what they
 * still need to learn. Template-built from the real match data. */
export function buildKvSimpler(match: KvMatch, t: T): string {
  const have =
    match.matched_skills.length > 0 ? joinList(match.matched_skills.slice(0, 3)) : t("voice_simpler_none");
  const learn =
    match.missing_skills.length > 0 ? joinList(match.missing_skills.slice(0, 3)) : t("voice_simpler_none");
  return t("voice_simpler_text", { title: match.title, have, learn });
}

/** One Kaam-Vaani match, read aloud: rank, title, match %, why it
 * fits, have/learn. */
export function buildKvMatchSpeech(match: KvMatch, rank: number, t: T): string {
  const parts = [
    t("voice_speak_match", { n: rank, title: match.title, pct: Math.round(match.match_percent) }),
    buildKvWhy(match, t),
  ];
  if (match.matched_skills.length > 0) {
    parts.push(t("voice_speak_have", { skills: joinList(match.matched_skills.slice(0, 4)) }));
  }
  if (match.missing_skills.length > 0) {
    parts.push(t("voice_speak_learn", { skills: joinList(match.missing_skills.slice(0, 3)) }));
  }
  return parts.filter(Boolean).join(" ");
}

/** Short summary of all Kaam-Vaani matches, for "Listen to my matches". */
export function buildKvSummarySpeech(matches: KvMatch[], t: T): string {
  if (matches.length === 0) return "";
  const lines = [t("voice_speak_intro", { n: matches.length })];
  matches.forEach((match, i) => {
    lines.push(
      t("voice_speak_match", { n: i + 1, title: match.title, pct: Math.round(match.match_percent) }),
    );
  });
  return lines.join(" ");
}

/** "Hear more" for one match: the gap + free learning path, read aloud
 * — only the resources that actually exist, each with its provider. */
export function buildKvGapSpeech(detail: KvGapLearningResponse, t: T): string {
  const parts = [t("voice_speak_gap_intro", { title: detail.title })];
  const missing = detail.gap.skills.filter((s) => s.status === "missing").map((s) => s.skill);
  if (missing.length > 0) {
    parts.push(t("voice_speak_learn", { skills: joinList(missing.slice(0, 4)) }));
  }
  if (detail.learning_path.length > 0) {
    const items = detail.learning_path
      .slice(0, 3)
      .map((item) => `${item.title} (${item.provider})`)
      .join(", ");
    parts.push(t("voice_speak_learn_path", { items }));
  }
  return parts.filter(Boolean).join(" ");
}

/** The extracted profile, read aloud for confirmation — only the fields
 * the user actually gave, so an empty field is never spoken as a fact. */
export function buildProfileSpeech(profile: VoiceProfile, t: T): string {
  const parts = [t("voice_speak_profile")];
  if (profile.skills.length > 0) {
    parts.push(t("voice_speak_skills", { skills: joinList(profile.skills) }));
  }
  if (profile.education) {
    parts.push(t("voice_speak_education", { education: profile.education }));
  }
  if (profile.city) {
    parts.push(t("voice_speak_city", { city: profile.city }));
  }
  if (profile.incomeText) {
    parts.push(t("voice_speak_income", { income: profile.incomeText }));
  }
  if (profile.goalType === "job_6_months") {
    parts.push(t("voice_speak_goal_job"));
  } else if (profile.goalType === "higher_studies") {
    parts.push(t("voice_speak_goal_study"));
  }
  return parts.filter(Boolean).join(" ");
}

/* -------------------------------------------------------------------------- */
/* Example answers — labelled as examples, for users who don't know what     */
/* to say (and for testing the flow without a microphone). One answer per    */
/* guided question, per locale.                                              */
/* -------------------------------------------------------------------------- */

export const EXAMPLE_ANSWERS: Record<Locale, Record<QuestionId, string>> = {
  en: {
    skills: "farming and basic computer work, and I can type",
    education: "12th pass",
    city: "Madurai",
    income: "15000 rupees a month",
    goal: "I need a job",
  },
  hi: {
    skills: "मुझे खेती और बेसिक कंप्यूटर आता है",
    education: "मैंने 12वीं पास की है",
    city: "मैं मदुरै से हूँ",
    income: "मुझे महीने के 15000 रुपये चाहिए",
    goal: "मुझे नौकरी चाहिए",
  },
  ta: {
    skills: "எனக்கு விவசாயம், அடிப்படை கணினி வேலை தெரியும்",
    education: "நான் 12ஆம் வகுப்பு முடித்துவிட்டேன்",
    city: "மதுரையில் இருக்கிறேன்",
    income: "மாதம் 15000 ரூபாய் சம்பளம்",
    goal: "வேலை வேண்டும்",
  },
};
