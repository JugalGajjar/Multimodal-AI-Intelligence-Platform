import { Analytics } from "@vercel/analytics/next";
import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { PostHogProvider } from "@/components/analytics/posthog-provider";
import { Providers } from "@/components/providers";
import { THEME_INIT_SCRIPT } from "@/components/theme/theme-provider";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Multimodal AI Intelligence Platform",
  description:
    "Multimodal RAG over text, PDFs, Word, PowerPoint, images, audio, and video, with knowledge graphs and agentic reasoning.",
};

// Explicit viewport export. Without this Next.js sometimes ships no viewport
// meta at all, and mobile Safari / Chromium fall back to a 980-1080px "legacy
// desktop" viewport — which renders the page zoomed in and forces users to
// pinch-out. `viewportFit: "cover"` lets content flow under the notch on iOS.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        {/* Set theme class before React hydrates to avoid flash-of-wrong-theme. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">
        <PostHogProvider>
          <Providers>{children}</Providers>
        </PostHogProvider>
        <Analytics />
      </body>
    </html>
  );
}
