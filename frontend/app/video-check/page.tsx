import { KvVideoView } from "@/components/kv-video-view";

export const metadata = {
  title: "Video skill check — Career Guidance AI",
  description: "Experimental: check that a 30–60 second task clip is a real recording with visible, moving content. Indicative only — not a certificate.",
};

export default function VideoCheckPage() {
  return <KvVideoView />;
}
