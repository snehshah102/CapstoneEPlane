"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";

import { FlightEventSummary } from "@/lib/contracts/schemas";

const ReactECharts = dynamic(() => import("echarts-for-react"), {
  ssr: false
});

type Props = {
  flights: FlightEventSummary[];
};

export function WearScatterChart({ flights }: Props) {
  const scatterPoints = useMemo(
    () =>
      flights
        .filter((flight) => flight.isFlightEvent)
        .map((flight) => {
          const duration = flight.durationMin ?? 20;
          const stress = Number(
            (
              0.45 * Math.min(100, duration) +
              (flight.eventType.toLowerCase().includes("test") ? 10 : 4)
            ).toFixed(2)
          );
          return [duration, stress, flight.flightId];
        }),
    [flights]
  );

  const option = useMemo(
    () => ({
      tooltip: {
        trigger: "item",
        formatter: (params: { value: [number, number, number] }) =>
          `Flight ${params.value[2]}<br/>Duration: ${params.value[0]} min<br/>Wear score: ${params.value[1]}`
      },
      xAxis: {
        type: "value",
        name: "Duration (min)",
        nameTextStyle: { color: "#94a3b8" },
        axisLabel: { color: "#94a3b8" }
      },
      yAxis: {
        type: "value",
        name: "Wear Score",
        nameTextStyle: { color: "#94a3b8" },
        axisLabel: { color: "#94a3b8" }
      },
      grid: { left: 44, right: 16, top: 24, bottom: 32 },
      series: [
        {
          data: scatterPoints,
          type: "scatter",
          symbolSize: 11,
          itemStyle: { color: "#10b981", opacity: 0.85 }
        }
      ]
    }),
    [scatterPoints]
  );

  return <ReactECharts option={option} style={{ height: 260, width: "100%" }} />;
}
