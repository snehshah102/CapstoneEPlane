"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";

import { SohTrendPoint } from "@/lib/contracts/schemas";

const ReactECharts = dynamic(() => import("echarts-for-react"), {
  ssr: false
});

type Props = {
  points: SohTrendPoint[];
};

export function SohLineChart({ points }: Props) {
  const option = useMemo(
    () => ({
      textStyle: { color: "#dbeafe" },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: points.map((item) => item.date),
        axisLabel: { color: "#94a3b8" }
      },
      yAxis: {
        type: "value",
        min: Math.max(0, Math.floor(Math.min(...points.map((x) => x.soh)) - 5)),
        max: 100,
        axisLabel: { color: "#94a3b8" }
      },
      grid: { left: 36, right: 24, top: 24, bottom: 36 },
      series: [
        {
          type: "line",
          smooth: true,
          data: points.map((item) => item.soh),
          showSymbol: false,
          lineStyle: { width: 3, color: "#22d3ee" },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(34,211,238,0.35)" },
                { offset: 1, color: "rgba(34,211,238,0.02)" }
              ]
            }
          }
        }
      ]
    }),
    [points]
  );

  return <ReactECharts option={option} style={{ height: 280, width: "100%" }} />;
}
