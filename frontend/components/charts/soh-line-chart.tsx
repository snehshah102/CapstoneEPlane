"use client";

import ReactECharts from "echarts-for-react";
import { useMemo } from "react";

import { SohTrendPoint } from "@/lib/contracts/schemas";

type Props = {
  points: SohTrendPoint[];
};

export function SohLineChart({ points }: Props) {
  const option = useMemo(
    () => ({
      animation: false,
      textStyle: { color: "#1e293b" },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        data: points.map((item) => item.date),
        axisLabel: { color: "#64748b" }
      },
      yAxis: {
        type: "value",
        min: Math.max(0, Math.floor(Math.min(...points.map((x) => x.soh)) - 5)),
        max: 100,
        axisLabel: { color: "#64748b" }
      },
      grid: { left: 36, right: 24, top: 24, bottom: 36 },
      series: [
        {
          type: "line",
          smooth: true,
          data: points.map((item) => item.soh),
          showSymbol: false,
          lineStyle: { width: 3, color: "#2563eb" },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(37,99,235,0.3)" },
                { offset: 1, color: "rgba(37,99,235,0.03)" }
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
