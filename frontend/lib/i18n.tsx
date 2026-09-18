"use client";

/**
 * Lightweight i18n: a typed dictionary for en / ta / hi and a React context.
 * Career content (O*NET titles, skills) stays in English; the chrome, hero,
 * composer, and status copy are translated.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type Locale = "en" | "ta" | "hi";

export const LOCALES: { id: Locale; label: string; native: string }[] = [
  { id: "en", label: "English", native: "English" },
  { id: "ta", label: "Tamil", native: "தமிழ்" },
  { id: "hi", label: "Hindi", native: "हिन्दी" },
];

const en = {
  app_name: "Career Guidance AI",
  connecting: "connecting…",
  careers_count: "{n} careers",
  nav_recommend: "Recommend",
  nav_recommend_hint: "Profile → 5 careers",
  nav_assessment: "Interests",
  nav_assessment_hint: "18-question RIASEC",
  nav_jobfit: "Job fit",
  nav_jobfit_hint: "Paste a JD, see gaps",
  nav_history: "History",
  nav_history_hint: "Saved runs & stats",
  about: "About",
  language: "Language",
  ai_mode: "AI mode",
  offline_mode: "Offline mode",
  ai_mode_desc: "LLM explanations grounded in O*NET.",
  offline_mode_desc:
    "Semantic matching over 970+ O*NET occupations. Set OPENAI_API_KEY for AI explanations.",
  interests_label: "Interests",
  expand_sidebar: "Expand sidebar",
  collapse_sidebar: "Collapse sidebar",
  hero_title: "Find your next career move.",
  hero_sub:
    "Tell us what you can do. We match you to real occupations, show exactly which skills you have and lack, and give you a roadmap — with salary bands and free courses.",
  skills_label: "Your skills",
  details: "Details",
  quiz_cta: "Not sure? Take the interest quiz",
  submit: "Get recommendations",
  try: "Try:",
  goal: "Career goal",
  goal_ph: "e.g. become a data analyst",
  interests: "Interests",
  interests_ph: "e.g. AI, education",
  education: "Education",
  education_ph: "e.g. B.Sc. Computer Science",
  experience: "Experience",
  attach_resume: "Attach resume (.pdf, .txt, .md)",
  remove_resume: "Remove resume",
  step_parse: "Normalising your skills",
  step_match: "Matching against 970+ O*NET occupations",
  step_gaps: "Computing skill gaps & priorities",
  step_market: "Attaching market signals & learning resources",
  step_llm: "Asking the LLM to explain (grounded)",
  results_title: "Your top matches",
  priority_skills: "Priority skills to learn",
  matching: "You already have",
  missing: "To learn",
  learning_path: "Learning path",
  next_steps: "Next steps",
  salary: "Salary",
  demand: "Demand",
  resources: "Free resources",
  export: "Export",
  error_generic: "Something went wrong. Please try again.",
  sign_in: "Sign in",
  sign_in_sub: "Save your runs, track skill progress and pick up where you left off.",
  sign_out: "Sign out",
  continue_google: "Continue with Google",
  or: "or",
  email: "E-mail",
  send_link: "Send me a sign-in link",
  link_sent: "Check your inbox",
  link_sent_sub: "We sent a sign-in link to {email}. It is valid for 15 minutes.",
  dev_link: "E-mail is not configured — open the link directly",
  sign_in_privacy: "We only store your e-mail and your saved runs. Delete your account any time.",
  nav_admin: "Admin",
  nav_admin_hint: "Users, content, feedback",
  auth_expired: "That sign-in link has expired or was already used.",
  auth_disabled: "This account has been disabled.",
  auth_cancelled: "Sign-in was cancelled.",
  signed_in_as: "Signed in as",
  delete_account: "Delete my account",
  password: "Password",
  login_hero: "Your career, mapped.",
  loop_1: "974 real occupations from O*NET.",
  loop_2: "Skill gaps, ranked by impact.",
  loop_3: "Salary bands and free courses.",
  perk_1: "Save every recommendation run across devices",
  perk_2: "Track the skills you've learned over time",
  perk_3: "Curated free courses for every gap",
  welcome_back: "Welcome back",
  verify_sent: "Account created! We sent a verification link to {email}. Open your Gmail/inbox (check spam too), click the link, then come back and sign in.",
  verify_blocked: "Please verify your email address before signing in. Check your inbox for the verification link.",
  verify_resent: "Verification e-mail re-sent to {email}. It can take a minute to arrive.",
  resend_verification: "Resend verification e-mail",
  resend_needs_password: "Enter your password to resend the verification e-mail.",
  verified_banner: "E-mail verified — you can sign in now.",
  login_required: "Please sign in to continue.",
  back_home: "Back to app",
  create_account: "Create account",
  have_account: "Already have an account? Sign in",
  no_account: "New here? Create an account",
  forgot_password: "Forgot password?",
  reset_sent: "Password reset e-mail sent to {email}.",
  enter_email_first: "Enter your e-mail address first.",
};

export type Dict = typeof en;
export type Key = keyof Dict;

const ta: Dict = {
  ...en,
  app_name: "தொழில் வழிகாட்டி AI",
  connecting: "இணைக்கிறது…",
  careers_count: "{n} தொழில்கள்",
  nav_recommend: "பரிந்துரை",
  nav_recommend_hint: "சுயவிவரம் → 5 தொழில்கள்",
  nav_assessment: "ஆர்வங்கள்",
  nav_assessment_hint: "18 கேள்வி RIASEC",
  nav_jobfit: "வேலை பொருத்தம்",
  nav_jobfit_hint: "வேலை விளக்கம் ஒட்டவும்",
  nav_history: "வரலாறு",
  nav_history_hint: "சேமித்த முடிவுகள்",
  about: "பற்றி",
  language: "மொழி",
  ai_mode: "AI முறை",
  offline_mode: "ஆஃப்லைன் முறை",
  ai_mode_desc: "O*NET அடிப்படையிலான LLM விளக்கங்கள்.",
  offline_mode_desc: "970+ O*NET தொழில்களுடன் பொருத்தம். AI விளக்கங்களுக்கு OPENAI_API_KEY அமைக்கவும்.",
  interests_label: "ஆர்வங்கள்",
  expand_sidebar: "பக்கப்பட்டியை விரிவாக்கு",
  collapse_sidebar: "பக்கப்பட்டியை மடக்கு",
  hero_title: "உங்கள் அடுத்த தொழில் படியைக் கண்டறியுங்கள்.",
  hero_sub:
    "உங்களால் என்ன செய்ய முடியும் என்று சொல்லுங்கள். உண்மையான தொழில்களுடன் பொருத்தி, உங்களிடம் உள்ள மற்றும் இல்லாத திறன்களைக் காட்டி, சம்பள வரம்புகள் மற்றும் இலவச படிப்புகளுடன் ஒரு வழிகாட்டியைத் தருகிறோம்.",
  skills_label: "உங்கள் திறன்கள்",
  details: "விவரங்கள்",
  quiz_cta: "உறுதியாக இல்லையா? ஆர்வ வினாடி வினா எடுக்கவும்",
  submit: "பரிந்துரைகளைப் பெறு",
  try: "முயற்சி:",
  goal: "தொழில் இலக்கு",
  goal_ph: "எ.கா. தரவு பகுப்பாய்வாளர் ஆக",
  interests: "ஆர்வங்கள்",
  interests_ph: "எ.கா. AI, கல்வி",
  education: "கல்வி",
  education_ph: "எ.கா. B.Sc. கணினி அறிவியல்",
  experience: "அனுபவம்",
  attach_resume: "ரெஸ்யூம் இணைக்க (.pdf, .txt, .md)",
  remove_resume: "ரெஸ்யூமை நீக்கு",
  step_parse: "உங்கள் திறன்களை ஒழுங்குபடுத்துகிறது",
  step_match: "970+ O*NET தொழில்களுடன் பொருத்துகிறது",
  step_gaps: "திறன் இடைவெளிகளைக் கணக்கிடுகிறது",
  step_market: "சந்தை தரவு மற்றும் படிப்புகளை இணைக்கிறது",
  step_llm: "LLM விளக்கத்தைக் கேட்கிறது",
  results_title: "உங்கள் சிறந்த பொருத்தங்கள்",
  priority_skills: "முதலில் கற்க வேண்டிய திறன்கள்",
  matching: "உங்களிடம் ஏற்கனவே உள்ளது",
  missing: "கற்க வேண்டியவை",
  learning_path: "கற்றல் பாதை",
  next_steps: "அடுத்த படிகள்",
  salary: "சம்பளம்",
  demand: "தேவை",
  resources: "இலவச வளங்கள்",
  export: "ஏற்றுமதி",
  error_generic: "ஏதோ தவறு நடந்தது. மீண்டும் முயற்சிக்கவும்.",
  sign_in: "உள்நுழை",
  sign_in_sub: "உங்கள் முடிவுகளைச் சேமித்து, திறன் முன்னேற்றத்தைக் கண்காணிக்கவும்.",
  sign_out: "வெளியேறு",
  continue_google: "Google மூலம் தொடரவும்",
  or: "அல்லது",
  email: "மின்னஞ்சல்",
  send_link: "உள்நுழைவு இணைப்பை அனுப்பு",
  link_sent: "உங்கள் இன்பாக்ஸைப் பாருங்கள்",
  link_sent_sub: "{email} க்கு உள்நுழைவு இணைப்பை அனுப்பியுள்ளோம். 15 நிமிடங்களுக்கு செல்லுபடியாகும்.",
  dev_link: "மின்னஞ்சல் அமைக்கப்படவில்லை — இணைப்பை நேரடியாகத் திறக்கவும்",
  sign_in_privacy: "உங்கள் மின்னஞ்சல் மற்றும் சேமித்த முடிவுகளை மட்டுமே சேமிக்கிறோம்.",
  nav_admin: "நிர்வாகம்",
  nav_admin_hint: "பயனர்கள், உள்ளடக்கம், கருத்து",
  auth_expired: "அந்த உள்நுழைவு இணைப்பு காலாவதியானது.",
  auth_disabled: "இந்தக் கணக்கு முடக்கப்பட்டுள்ளது.",
  auth_cancelled: "உள்நுழைவு ரத்து செய்யப்பட்டது.",
  signed_in_as: "உள்நுழைந்தவர்",
  delete_account: "எனது கணக்கை நீக்கு",
  password: "கடவுச்சொல்",
  login_hero: "உங்கள் தொழில் வாழ்க்கை, வரைபடமாக.",
  loop_1: "O*NET இலிருந்து 974 உண்மையான தொழில்கள்.",
  loop_2: "தாக்கத்தின்படி வரிசைப்படுத்தப்பட்ட திறன் இடைவெளிகள்.",
  loop_3: "சம்பள வரம்புகள் மற்றும் இலவச படிப்புகள்.",
  perk_1: "எல்லா சாதனங்களிலும் உங்கள் பரிந்துரைகளைச் சேமிக்கவும்",
  perk_2: "கற்ற திறன்களைக் கண்காணிக்கவும்",
  perk_3: "ஒவ்வொரு இடைவெளிக்கும் இலவச படிப்புகள்",
  welcome_back: "மீண்டும் வரவேற்கிறோம்",
  verify_sent: "கணக்கு உருவாக்கப்பட்டது! {email} க்கு சரிபார்ப்பு இணைப்பு அனுப்பியுள்ளோம். Gmail/இன்பாக்ஸைத் திறந்து (ஸ்பேமையும் பாருங்கள்), இணைப்பைக் கிளிக் செய்து, திரும்பி உள்நுழையவும்.",
  verify_blocked: "உள்நுழைவதற்கு முன் உங்கள் மின்னஞ்சலைச் சரிபார்க்கவும். சரிபார்ப்பு இணைப்புக்கு இன்பாக்ஸைப் பாருங்கள்.",
  verify_resent: "{email} க்கு சரிபார்ப்பு மின்னஞ்சல் மீண்டும் அனுப்பப்பட்டது.",
  resend_verification: "சரிபார்ப்பு மின்னஞ்சலை மீண்டும் அனுப்பு",
  resend_needs_password: "மீண்டும் அனுப்ப கடவுச்சொல்லை உள்ளிடவும்.",
  verified_banner: "மின்னஞ்சல் சரிபார்க்கப்பட்டது — இப்போது உள்நுழையலாம்.",
  login_required: "தொடர உள்நுழையவும்.",
  back_home: "ஆப்-க்குத் திரும்பு",
  create_account: "கணக்கை உருவாக்கு",
  have_account: "ஏற்கனவே கணக்கு உள்ளதா? உள்நுழை",
  no_account: "புதியவரா? கணக்கை உருவாக்கு",
  forgot_password: "கடவுச்சொல் மறந்துவிட்டதா?",
  reset_sent: "{email} க்கு கடவுச்சொல் மீட்டமைப்பு மின்னஞ்சல் அனுப்பப்பட்டது.",
  enter_email_first: "முதலில் உங்கள் மின்னஞ்சலை உள்ளிடவும்.",
};

const hi: Dict = {
  ...en,
  app_name: "करियर गाइडेंस AI",
  connecting: "कनेक्ट हो रहा है…",
  careers_count: "{n} करियर",
  nav_recommend: "सुझाव",
  nav_recommend_hint: "प्रोफ़ाइल → 5 करियर",
  nav_assessment: "रुचियाँ",
  nav_assessment_hint: "18-प्रश्न RIASEC",
  nav_jobfit: "जॉब फ़िट",
  nav_jobfit_hint: "JD पेस्ट करें, गैप देखें",
  nav_history: "इतिहास",
  nav_history_hint: "सहेजे गए परिणाम",
  about: "परिचय",
  language: "भाषा",
  ai_mode: "AI मोड",
  offline_mode: "ऑफ़लाइन मोड",
  ai_mode_desc: "O*NET पर आधारित LLM व्याख्याएँ।",
  offline_mode_desc: "970+ O*NET व्यवसायों से मिलान। AI व्याख्या के लिए OPENAI_API_KEY सेट करें।",
  interests_label: "रुचियाँ",
  expand_sidebar: "साइडबार खोलें",
  collapse_sidebar: "साइडबार बंद करें",
  hero_title: "अपना अगला करियर कदम खोजें।",
  hero_sub:
    "बताइए आप क्या कर सकते हैं। हम आपको असली व्यवसायों से मिलाते हैं, दिखाते हैं कि कौन से कौशल आपके पास हैं और कौन से नहीं, और वेतन बैंड व मुफ़्त कोर्स के साथ रोडमैप देते हैं।",
  skills_label: "आपके कौशल",
  details: "विवरण",
  quiz_cta: "पक्का नहीं? रुचि क्विज़ लें",
  submit: "सुझाव पाएँ",
  try: "आज़माएँ:",
  goal: "करियर लक्ष्य",
  goal_ph: "जैसे डेटा एनालिस्ट बनना",
  interests: "रुचियाँ",
  interests_ph: "जैसे AI, शिक्षा",
  education: "शिक्षा",
  education_ph: "जैसे B.Sc. कंप्यूटर साइंस",
  experience: "अनुभव",
  attach_resume: "रिज़्यूमे जोड़ें (.pdf, .txt, .md)",
  remove_resume: "रिज़्यूमे हटाएँ",
  step_parse: "आपके कौशल सामान्य किए जा रहे हैं",
  step_match: "970+ O*NET व्यवसायों से मिलान",
  step_gaps: "कौशल अंतर और प्राथमिकताएँ",
  step_market: "बाज़ार संकेत और संसाधन जोड़े जा रहे हैं",
  step_llm: "LLM से व्याख्या माँगी जा रही है",
  results_title: "आपके शीर्ष मिलान",
  priority_skills: "पहले सीखने योग्य कौशल",
  matching: "आपके पास पहले से है",
  missing: "सीखना है",
  learning_path: "सीखने का मार्ग",
  next_steps: "अगले कदम",
  salary: "वेतन",
  demand: "माँग",
  resources: "मुफ़्त संसाधन",
  export: "निर्यात",
  error_generic: "कुछ गलत हो गया। कृपया फिर से प्रयास करें।",
  sign_in: "साइन इन",
  sign_in_sub: "अपने परिणाम सहेजें और कौशल प्रगति ट्रैक करें।",
  sign_out: "साइन आउट",
  continue_google: "Google से जारी रखें",
  or: "या",
  email: "ई-मेल",
  send_link: "साइन-इन लिंक भेजें",
  link_sent: "अपना इनबॉक्स देखें",
  link_sent_sub: "हमने {email} पर साइन-इन लिंक भेजा है। यह 15 मिनट तक मान्य है।",
  dev_link: "ई-मेल कॉन्फ़िगर नहीं है — लिंक सीधे खोलें",
  sign_in_privacy: "हम केवल आपका ई-मेल और सहेजे गए परिणाम रखते हैं।",
  nav_admin: "एडमिन",
  nav_admin_hint: "उपयोगकर्ता, सामग्री, फ़ीडबैक",
  auth_expired: "यह साइन-इन लिंक समाप्त हो गया है।",
  auth_disabled: "यह खाता अक्षम कर दिया गया है।",
  auth_cancelled: "साइन-इन रद्द किया गया।",
  signed_in_as: "साइन इन:",
  delete_account: "मेरा खाता हटाएँ",
  password: "पासवर्ड",
  login_hero: "आपका करियर, मैप किया हुआ।",
  loop_1: "O*NET से 974 असली व्यवसाय।",
  loop_2: "प्रभाव के अनुसार क्रमबद्ध कौशल अंतर।",
  loop_3: "वेतन बैंड और मुफ़्त कोर्स।",
  perk_1: "हर सुझाव को सभी डिवाइस पर सहेजें",
  perk_2: "सीखे गए कौशल को ट्रैक करें",
  perk_3: "हर अंतर के लिए चुने हुए मुफ़्त कोर्स",
  welcome_back: "फिर से स्वागत है",
  verify_sent: "खाता बन गया! हमने {email} पर सत्यापन लिंक भेजा है। अपना Gmail/इनबॉक्स खोलें (स्पैम भी देखें), लिंक पर क्लिक करें, फिर वापस आकर साइन इन करें।",
  verify_blocked: "साइन इन करने से पहले कृपया अपना ई-मेल सत्यापित करें। सत्यापन लिंक के लिए इनबॉक्स देखें।",
  verify_resent: "{email} पर सत्यापन ई-मेल फिर से भेजा गया।",
  resend_verification: "सत्यापन ई-मेल फिर से भेजें",
  resend_needs_password: "फिर से भेजने के लिए पासवर्ड दर्ज करें।",
  verified_banner: "ई-मेल सत्यापित — अब आप साइन इन कर सकते हैं।",
  login_required: "जारी रखने के लिए साइन इन करें।",
  back_home: "ऐप पर वापस",
  create_account: "खाता बनाएँ",
  have_account: "पहले से खाता है? साइन इन करें",
  no_account: "नए हैं? खाता बनाएँ",
  forgot_password: "पासवर्ड भूल गए?",
  reset_sent: "{email} पर पासवर्ड रीसेट ई-मेल भेजा गया।",
  enter_email_first: "पहले अपना ई-मेल दर्ज करें।",
};

export const DICTS: Record<Locale, Dict> = { en, ta, hi };

const STORAGE_KEY = "cg.locale";

type Ctx = {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: Key, vars?: Record<string, string | number>) => string;
};

const I18nContext = createContext<Ctx>({
  locale: "en",
  setLocale: () => {},
  t: (k) => en[k],
});

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("en");

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY) as Locale | null;
    if (saved && saved in DICTS) {
      setLocaleState(saved);
    } else {
      const nav = navigator.language?.slice(0, 2);
      if (nav === "ta" || nav === "hi") setLocaleState(nav);
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((l: Locale) => {
    window.localStorage.setItem(STORAGE_KEY, l);
    setLocaleState(l);
  }, []);

  const t = useCallback(
    (key: Key, vars?: Record<string, string | number>) => {
      let s = DICTS[locale][key] ?? en[key] ?? key;
      if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v));
      return s;
    },
    [locale],
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}
