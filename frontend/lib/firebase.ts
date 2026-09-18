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
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
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

// ---- Google -----------------------------------------------------------------
// Google accounts are verified by Google; no Firebase verification e-mail needed.
export async function signInWithGoogle(): Promise<string> {
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  const cred = await signInWithPopup(firebaseAuth(), provider);
  return cred.user.getIdToken();
}

// ---- Email / password -------------------------------------------------------
export type SignUpResult = { verificationSent: true; email: string };

/** Create the account, send the verification e-mail, and sign out until verified. */
export async function signUpWithEmail(email: string, password: string): Promise<SignUpResult> {
  const a = firebaseAuth();
  const cred = await createUserWithEmailAndPassword(a, email, password);
  try {
    await sendEmailVerification(cred.user, { url: window.location.origin + "/login?verified=1" });
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
    await sendEmailVerification(cred.user, { url: window.location.origin + "/login?verified=1" });
  } finally {
    await signOut(a);
  }
}

export const resetPassword = (email: string) =>
  sendPasswordResetEmail(firebaseAuth(), email, { url: window.location.origin + "/login" });

export const firebaseSignOut = async () => {
  if (!firebaseConfigured) return;
  await signOut(firebaseAuth()).catch(() => {});
};

export const currentFirebaseUser = (): FirebaseUser | null => (firebaseConfigured ? firebaseAuth().currentUser : null);

// ---- Errors -----------------------------------------------------------------
export function friendlyFirebaseError(e: unknown): string {
  const code = (e as { code?: string })?.code ?? "";
  const map: Record<string, string> = {
    "auth/email-not-verified": "Please verify your email address before signing in. Check your inbox (and spam) for the verification link.",
    "auth/popup-closed-by-user": "The sign-in window was closed before finishing.",
    "auth/cancelled-popup-request": "The sign-in window was closed before finishing.",
    "auth/popup-blocked": "Your browser blocked the sign-in popup. Allow popups for this site and try again.",
    "auth/unauthorized-domain": "This domain is not authorised for sign-in. Add it in Firebase → Authentication → Settings → Authorised domains.",
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
    "auth/too-many-requests": "Too many attempts. Please wait a few minutes and try again.",
    "auth/network-request-failed": "Network error while contacting Firebase. Check your connection.",
    "auth/expired-action-code": "That verification link has expired. Request a new one.",
    "auth/invalid-action-code": "That verification link is invalid or was already used.",
    "auth/account-exists-with-different-credential": "An account with this e-mail already exists using a different sign-in method.",
    "app/not-configured": "Sign-in is not configured on this deployment (missing NEXT_PUBLIC_FIREBASE_* variables).",
  };
  if (map[code]) return map[code];
  const msg = (e as Error)?.message ?? "";
  return msg && !msg.startsWith("Firebase:") ? msg : "Sign-in failed. Please try again.";
}
