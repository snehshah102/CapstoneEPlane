"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: "/planes", label: "Planes" },
  { href: "/mission-game", label: "FlightLab" },
  { href: "/learn", label: "Learn" }
] as const;

function isActive(pathname: string, href: string) {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SiteHeader() {
  const pathname = usePathname();

  return (
    <header className="mb-10 flex flex-wrap items-center justify-between gap-4 border-b border-slate-200/90 pb-5">
      <div className="space-y-1">
        <Link
          href="/"
          className="inline-flex rounded-2xl px-2 py-1 font-[var(--font-heading)] text-[2rem] leading-none tracking-tight text-slate-900 transition duration-200 hover:bg-white/80 hover:text-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
        >
          AeroCell
        </Link>
        <p className="max-w-xl text-sm text-slate-600">
          Unlocking Battery Intelligence for Next-Generation Electric Aviation
        </p>
      </div>

      <nav className="flex flex-wrap items-center gap-2">
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "inline-flex min-h-11 items-center justify-center rounded-full px-4 py-2 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400",
                active
                  ? "bg-blue-600 text-white shadow-sm"
                  : "bg-white/70 text-slate-700 ring-1 ring-slate-200 hover:-translate-y-0.5 hover:bg-white hover:text-slate-900 hover:shadow-sm"
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
