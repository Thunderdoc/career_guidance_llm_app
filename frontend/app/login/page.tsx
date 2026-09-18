import type { Metadata } from "next";
import { LoginPage } from "@/components/login-page";

export const metadata: Metadata = { title: "Sign in — Career Guidance AI" };

export default function Page() {
  return <LoginPage />;
}
