import type { Metadata, Viewport } from "next";
import "./globals.css";
import { I18nProvider } from "@/lib/i18n";
import { AuthProvider } from "@/lib/auth-context";

export const metadata: Metadata = {
  title: "Career Guidance AI — find your next career move",
  description:
    "Skill-gap analysis, learning roadmaps and market signals for 970+ careers, grounded in the O*NET taxonomy. Works offline; AI-enhanced when configured.",
  applicationName: "Career Guidance AI",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = { themeColor: "#0f0f0f", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Instrument+Serif:ital@0;1&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-dvh antialiased">
        <I18nProvider>
          <AuthProvider>{children}</AuthProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
