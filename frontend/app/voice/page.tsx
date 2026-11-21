import type { Metadata } from "next";
import { VoiceView } from "@/components/voice-view";

export const metadata: Metadata = { title: "Voice — Career Guidance AI", robots: { index: false } };

export default function Page() {
  return <VoiceView />;
}
