"use client";

/**
 * Firebase Auth (client). The web config is public by design; access is
 * governed by Firebase Auth rules and by our backend verifying ID tokens.
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
} from "firebase/auth";

export const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "AIzaSyBE5Duza92jED_vkSz26MftRinBvrVORKg",
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "career-ai-ecba3.firebaseapp.com",
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "career-ai-ecba3",
  storageBucket: "career-ai-ecba3.firebasestorage.app",
  messagingSenderId: "203620159836",
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "1:203620159836:web:fcd9aa2c02df2ec09f3199",
};

let app: FirebaseApp | null = null;
export function firebaseAuth(): Auth {
  if (!app) app = getApps()[0] ?? initializeApp(firebaseConfig);
  return getAuth(app);
}

export async function googleIdToken(): Promise<string> {
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  const cred = await signInWithPopup(firebaseAuth(), provider);
  return cred.user.getIdToken();
}

export async function emailPasswordIdToken(email: string, password: string, mode: "signin" | "signup"): Promise<string> {
  const a = firebaseAuth();
  if (mode === "signup") {
    const cred = await createUserWithEmailAndPassword(a, email, password);
    await sendEmailVerification(cred.user).catch(() => {});
    return cred.user.getIdToken();
  }
  const cred = await signInWithEmailAndPassword(a, email, password);
  return cred.user.getIdToken();
}

export const resetPassword = (email: string) => sendPasswordResetEmail(firebaseAuth(), email);
export const firebaseSignOut = () => signOut(firebaseAuth()).catch(() => {});

export function friendlyFirebaseError(e: unknown): string {
  const code = (e as { code?: string })?.code ?? "";
  const map: Record<string, string> = {
    "auth/popup-closed-by-user": "Sign-in window was closed.",
    "auth/cancelled-popup-request": "Sign-in window was closed.",
    "auth/popup-blocked": "Your browser blocked the sign-in popup. Allow popups and try again.",
    "auth/unauthorized-domain": "This domain is not authorised in Firebase → Authentication → Settings → Authorised domains.",
    "auth/operation-not-allowed": "This sign-in method is not enabled in the Firebase console.",
    "auth/invalid-email": "That e-mail address doesn't look right.",
    "auth/user-not-found": "No account with that e-mail. Create one instead?",
    "auth/wrong-password": "Wrong password.",
    "auth/invalid-credential": "Wrong e-mail or password.",
    "auth/email-already-in-use": "An account with that e-mail already exists — sign in instead.",
    "auth/weak-password": "Password must be at least 6 characters.",
    "auth/too-many-requests": "Too many attempts. Please wait a moment.",
    "auth/network-request-failed": "Network error reaching Firebase.",
  };
  return map[code] ?? (e as Error)?.message ?? "Sign-in failed.";
}
