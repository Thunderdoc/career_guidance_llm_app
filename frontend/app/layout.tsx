import type { Metadata, Viewport } from "next";
import "./globals.css";
import { I18nProvider } from "@/lib/i18n";
import { PwaRegister } from "@/components/pwa-register";
import { AuthProvider } from "@/lib/auth-context";

export const metadata: Metadata = {
  title: "Career Guidance AI — find your next career move",
  description:
    "Skill-gap analysis, career ladders, pathway checks and learning roadmaps for 974 occupations, with curated market data for India. Rule-based, explainable and private.",
  applicationName: "Career Guidance AI",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
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
          <AuthProvider>
            <PwaRegister />
            {children}
          </AuthProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
