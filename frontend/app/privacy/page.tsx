import type { Metadata } from "next";
import { PrivacyNoticeView } from "@/components/privacy-notice-view";

export const metadata: Metadata = { title: "Privacy — Career Guidance AI" };

/**
 * Privacy policy (Phase 5: plain-language notice; summary in EN/TA/HI,
 * full legal text in English — see components/privacy-notice-view.tsx).
 * Business name and contact are placeholders the owner fills in before
 * announcing paid plans (see SELLING.md go-live list).
 */
export default function Page() {
  return <PrivacyNoticeView />;
}
