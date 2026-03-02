import type { Metadata } from "next";
import { IBM_Plex_Sans, Space_Grotesk } from "next/font/google";
import Link from "next/link";

import { ChunkReloadGuard } from "@/components/providers/chunk-reload-guard";
import { QueryProvider } from "@/components/providers/query-provider";
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
            <header className="mb-12 flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 pb-4">
              <div className="space-y-0.5">
                <Link
                  href="/"
                  prefetch={false}
                  className="font-[var(--font-heading)] text-xl tracking-tight text-slate-900"
                >
                  AeroCell
                </Link>
                <p className="text-xs text-muted">
                  Unlocking Battery Intelligence for Next-Generation Electric
                  Aviation
                </p>
              </div>
              <nav className="flex items-center gap-6 text-sm text-slate-600">
                <Link href="/" prefetch={false} className="transition hover:text-slate-900">
                  Home
                </Link>
                <Link href="/planes" prefetch={false} className="transition hover:text-slate-900">
                  Planes
                </Link>
                <Link
                  href="/mission-game"
                  prefetch={false}
                  className="transition hover:text-slate-900"
                >
                  FlightLab
                </Link>
                <Link href="/learn" prefetch={false} className="transition hover:text-slate-900">
                  Learn
                </Link>
              </nav>
            </header>
            {children}
          </div>
        </QueryProvider>
      </body>
    </html>
  );
}
