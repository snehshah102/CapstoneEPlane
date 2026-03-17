"use client";

import { ReactNode } from "react";
import { usePathname } from "next/navigation";

type Props = {
  children: ReactNode;
};

export function RouteTransition({ children }: Props) {
  const pathname = usePathname();

  return (
    <div key={pathname} className="route-shell">
      {children}
    </div>
  );
}
