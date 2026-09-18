"use client";

/**
 * Firebase Auth (client side).
 *
 * Config comes from NEXT_PUBLIC_FIREBASE_* env vars (see frontend/.env.example).
 * These values are public by design; security is enforced by Firebase Auth
 * and by the backend, which verifies every ID token before issuing a session.
 */
import { getApps, initializeApp, type FirebaseApp } from "firebase/app";
import {
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  getAuth,
  getRedirectResult,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signInWithRedirect,
  signOut,
  type Auth,
  type User as FirebaseUser,
} from "firebase/auth";

export const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "",
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "",
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET ?? "",
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID ?? "",
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "",
};

export const firebaseConfigured = Boolean(firebaseConfig.apiKey && firebaseConfig.projectId && firebaseConfig.appId);

let app: FirebaseApp | null = null;
export function firebaseAuth(): Auth {
  if (!firebaseConfigured) throw Object.assign(new Error("Firebase is not configured."), { code: "app/not-configured" });
  if (!app) app = getApps()[0] ?? initializeApp(firebaseConfig);
  return getAuth(app);
}

/** Thrown when an email/password account has not verified its address yet. */
export class UnverifiedEmailError extends Error {
  code = "auth/email-not-verified";
  constructor(public email: string) {
    super("Please verify your email address before signing in.");
  }
}

/** Codes that mean "the popup route is unavailable — try a full-page redirect". */
const REDIRECT_FALLBACK_CODES = new Set([
  "auth/popup-blocked",
  "auth/unauthorized-domain",
  "auth/operation-not-supported-in-this-environment",
  "auth/popup-closed-by-user",
]);

export function needsRedirectFallback(e: unknown): boolean {
  return REDIRECT_FALLBACK_CODES.has(errorCode(e));
}

export function errorCode(e: unknown): string {
  return (e as { code?: string })?.code ?? "";
}

// ---- Google -----------------------------------------------------------------
// Google accounts are verified by Google; no Firebase verification e-mail needed.
export async function signInWithGoogle(): Promise<string> {
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  const cred = await signInWithPopup(firebaseAuth(), provider);
  return cred.user.getIdToken();
}

/** Full-page redirect sign-in: the fallback when popups are blocked or the domain rule bites. */
export async function signInWithGoogleRedirect(): Promise<void> {
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  await signInWithRedirect(firebaseAuth(), provider);
}

/** Resolve the pending redirect sign-in on /login load (returns null when there wasn't one). */
export async function completeGoogleRedirect(): Promise<{ idToken: string; email: string } | null> {
  if (!firebaseConfigured) return null;
  const cred = await getRedirectResult(firebaseAuth());
  if (!cred?.user) return null;
  const idToken = await cred.user.getIdToken();
  return { idToken, email: cred.user.email ?? "" };
}

// ---- Email / password -------------------------------------------------------
export type SignUpResult = { verificationSent: true; email: string };

/**
 * Send a Firebase action e-mail, retrying without a continue URL when the
 * project has not whitelisted our domain in *Authentication → Templates →
 * Action URL* (`auth/unauthorized-continue-uri`).
 */
export async function sendActionEmail(
  send: (continueUrl?: string) => Promise<void>,
  continueUrl: string,
): Promise<{ continueUrlUsed: boolean }> {
  try {
    await send(continueUrl);
    return { continueUrlUsed: true };
  } catch (e) {
    if (errorCode(e) !== "auth/unauthorized-continue-uri") throw e;
    await send(undefined);
    return { continueUrlUsed: false };
  }
}

/** Create the account, send the verification e-mail, and sign out until verified. */
export async function signUpWithEmail(email: string, password: string): Promise<SignUpResult> {
  const a = firebaseAuth();
  const cred = await createUserWithEmailAndPassword(a, email, password);
  try {
    await sendActionEmail(
      (url) => (url ? sendEmailVerification(cred.user, { url }) : sendEmailVerification(cred.user)),
      window.location.origin + "/login?verified=1",
    );
  } finally {
    await signOut(a); // never leave an unverified session around
  }
  return { verificationSent: true, email };
}

/** Sign in; if the address is unverified, sign out and throw UnverifiedEmailError. */
export async function signInWithEmail(email: string, password: string): Promise<string> {
  const a = firebaseAuth();
  const cred = await signInWithEmailAndPassword(a, email, password);
  await cred.user.reload(); // pick up a verification that happened in another tab
  const fresh = a.currentUser ?? cred.user;
  if (!fresh.emailVerified) {
    await signOut(a);
    throw new UnverifiedEmailError(email);
  }
  return fresh.getIdToken(true);
}

/** Re-send the verification e-mail. Needs the password because unverified users are never kept signed in. */
export async function resendVerification(email: string, password: string): Promise<void> {
  const a = firebaseAuth();
  const cred = await signInWithEmailAndPassword(a, email, password);
  try {
    await cred.user.reload();
    if ((a.currentUser ?? cred.user).emailVerified) return; // already verified — nothing to send
    await sendActionEmail(
      (url) => (url ? sendEmailVerification(cred.user, { url }) : sendEmailVerification(cred.user)),
      window.location.origin + "/login?verified=1",
    );
  } finally {
    await signOut(a);
  }
}

export const resetPassword = (email: string) =>
  sendActionEmail(
    (url) => (url ? sendPasswordResetEmail(firebaseAuth(), email, { url }) : sendPasswordResetEmail(firebaseAuth(), email)),
    window.location.origin + "/login",
  );

export const firebaseSignOut = async () => {
  if (!firebaseConfigured) return;
  await signOut(firebaseAuth()).catch(() => {});
};

export const currentFirebaseUser = (): FirebaseUser | null => (firebaseConfigured ? firebaseAuth().currentUser : null);

// ---- Errors -----------------------------------------------------------------
/**
 * Human-readable message for every Firebase error code the sign-in screen can
 * meet. Unknown codes render as `Sign-in failed (auth/xxx)` so the user (and
 * we) can always see which Firebase rule is unhappy.
 */
export function friendlyFirebaseError(e: unknown): string {
  const code = errorCode(e);
  const host = typeof window !== "undefined" ? window.location.hostname : "this domain";
  const map: Record<string, string> = {
    "auth/email-not-verified": "Please verify your email address before signing in. Check your inbox (and spam) for the verification link.",
    "auth/configuration-not-found": `Sign-in is not configured for this project (auth/configuration-not-found). In the Firebase console open Authentication and click "Get started", then enable the Google and Email/Password providers.`,
    "auth/unauthorized-domain": `Domain ${host} is not authorised for sign-in (auth/unauthorized-domain). Add it in the Firebase console under Firebase → Authentication → Settings → Authorised domains → Add domain.`,
    "auth/unauthorized-continue-uri": `Firebase refused the return URL for ${host} (auth/unauthorized-continue-uri). Retried without it — if this repeats, add ${window.location.origin} under Authentication → Templates → Action URL settings.`,
    "auth/invalid-api-key": "The Firebase API key is invalid (auth/invalid-api-key). Check NEXT_PUBLIC_FIREBASE_API_KEY in the Vercel project settings against Firebase → Project settings → Your apps.",
    "auth/missing-email": "Please enter your e-mail address.",
    "auth/internal-error": "Firebase returned an internal error (auth/internal-error). Please try again in a moment; if it persists, confirm the sign-in providers are enabled in the Firebase console.",
    "auth/requires-recent-login": "This action needs a fresh sign-in (auth/requires-recent-login). Sign out and sign in again, then retry.",
    "auth/popup-blocked": "Your browser blocked the sign-in popup (auth/popup-blocked). Use “Continue with Google (redirect)” below, or allow popups for this site.",
    "auth/popup-closed-by-user": "The sign-in window was closed before finishing.",
    "auth/cancelled-popup-request": "The sign-in window was closed before finishing.",
    "auth/network-request-failed": "Network error while contacting Firebase (auth/network-request-failed). Check your connection — corporate VPNs sometimes block identitytoolkit.googleapis.com.",
    "auth/too-many-requests": "Too many attempts (auth/too-many-requests). Firebase temporarily blocked sign-in from this device — wait a few minutes and try again.",
    "auth/operation-not-allowed": "This sign-in method is not enabled in the Firebase console.",
    "auth/invalid-email": "That e-mail address doesn't look right.",
    "auth/user-not-found": "No account exists with that e-mail. Create one instead?",
    "auth/wrong-password": "Wrong e-mail or password.",
    "auth/invalid-credential": "Wrong e-mail or password.",
    "auth/invalid-login-credentials": "Wrong e-mail or password.",
    "auth/user-disabled": "This account has been disabled.",
    "auth/email-already-in-use": "An account with that e-mail already exists — sign in instead.",
    "auth/weak-password": "Password must be at least 6 characters.",
    "auth/missing-password": "Please enter your password.",
    "auth/expired-action-code": "That verification link has expired. Request a new one.",
    "auth/invalid-action-code": "That verification link is invalid or was already used.",
    "auth/account-exists-with-different-credential": "An account with this e-mail already exists using a different sign-in method.",
    "app/not-configured": "Sign-in is not configured on this deployment (missing NEXT_PUBLIC_FIREBASE_* variables).",
  };
  if (map[code]) return map[code];
  if (code) return `Sign-in failed (${code})`;
  const msg = (e as Error)?.message ?? "";
  return msg && !msg.startsWith("Firebase:") ? msg : "Sign-in failed — please try again.";
}
