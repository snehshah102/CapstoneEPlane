"use client";

import dynamic from "next/dynamic";

type Point = {
  lat: number;
  lon: number;
  label: string;
};

type Props = {
  departure: Point | null;
  destination: Point | null;
};

const RouteMapCanvas = dynamic(
  () => import("./route-map-canvas").then((mod) => mod.RouteMapCanvas),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[280px] items-center justify-center rounded-xl border border-slate-600/30 text-sm text-slate-300">
        Loading route map...
      </div>
    )
  }
);

export function RouteMap({ departure, destination }: Props) {
  return <RouteMapCanvas departure={departure} destination={destination} />;
}
