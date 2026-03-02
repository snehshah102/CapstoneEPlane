import type { Metadata } from "next";
import { IBM_Plex_Sans, Space_Grotesk } from "next/font/google";
import Link from "next/link";

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
    <html lang="en" className={`${headingFont.variable} ${bodyFont.variable}`}>
      <body className="min-h-screen bg-hero-grid font-[var(--font-body)]">
        <QueryProvider>
          <div className="mx-auto max-w-[1320px] px-4 pb-12 pt-6 md:px-8">
            <header className="glass mb-8 flex flex-wrap items-center justify-between gap-3 rounded-2xl px-5 py-4">
              <div>
                <Link
                  href="/"
                  className="font-[var(--font-heading)] text-xl tracking-wide"
                >
                  AeroCell
                </Link>
                <p className="text-xs text-slate-300">
                  Unlocking Battery Intelligence for Next-Generation Electric
                  Aviation
                </p>
              </div>
              <nav className="flex items-center gap-4 text-sm text-muted">
                <Link href="/" className="transition hover:text-text">
                  Home
                </Link>
                <Link href="/experience" className="transition hover:text-text">
                  Experience
                </Link>
                <Link href="/planes" className="transition hover:text-text">
                  Planes
                </Link>
                <Link href="/learn" className="transition hover:text-text">
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
