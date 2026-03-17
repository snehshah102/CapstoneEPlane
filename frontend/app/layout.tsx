import type { Metadata } from "next";
import { IBM_Plex_Sans, Space_Grotesk } from "next/font/google";

import { SiteHeader } from "@/components/layout/site-header";
import { ChunkReloadGuard } from "@/components/providers/chunk-reload-guard";
import { QueryProvider } from "@/components/providers/query-provider";
import { RouteTransition } from "@/components/providers/route-transition";
import "./globals.css";

const headingFont = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-heading",
  weight: ["500", "700"]
});

const bodyFont = IBM_Plex_Sans({
  subsets: ["latin"],
  variable: "--font-body",
  weight: ["400", "500", "600", "700"]
});

export const metadata: Metadata = {
  title: {
    default: "AeroCell | Battery Intelligence for Electric Aviation",
    template: "AeroCell | %s"
  },
  description:
    "Unlocking Battery Intelligence for Next-Generation Electric Aviation."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${headingFont.variable} ${bodyFont.variable}`}
      suppressHydrationWarning
    >
      <body
        className="min-h-screen bg-hero-grid font-[var(--font-body)]"
        suppressHydrationWarning
      >
        <QueryProvider>
          <ChunkReloadGuard />
          <div className="mx-auto max-w-[1240px] px-5 pb-16 pt-5 md:px-8">
            <SiteHeader />
            <RouteTransition>{children}</RouteTransition>
          </div>
        </QueryProvider>
      </body>
    </html>
  );
}
