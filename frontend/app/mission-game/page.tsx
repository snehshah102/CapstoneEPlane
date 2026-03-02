import type { Metadata } from "next";

import { MissionGameShell } from "@/components/mission-game/mission-game-shell";

export const metadata: Metadata = {
  title: "FlightLab"
};

export default function MissionGamePage() {
  return <MissionGameShell />;
}
