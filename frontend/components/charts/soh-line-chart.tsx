"use client";

import ReactECharts from "echarts-for-react";
import { useMemo } from "react";

import { SohTrendPoint } from "@/lib/contracts/schemas";

type ForecastPoint = {
  date: string;
  soh: number;
};

type Props = {
  points: SohTrendPoint[];
  forecastPoints?: ForecastPoint[];
  window?: "30d" | "90d" | "1y" | "full";
};

export function SohLineChart({
  points,
  forecastPoints = [],
  window = "90d"
}: Props) {
  const xAxisDates = useMemo(() => {
    const allDates = new Set<string>();
    for (const point of points) {
      if (Number.isFinite(Date.parse(point.date))) {
        allDates.add(point.date);
      }
    }
    for (const point of forecastPoints) {
      if (Number.isFinite(Date.parse(point.date))) {
        allDates.add(point.date);
      }
    }
    return [...allDates].sort((a, b) => Date.parse(a) - Date.parse(b));
  }, [points, forecastPoints]);

  const historyMap = useMemo(
    () => new Map(points.map((point) => [point.date, point.soh])),
    [points]
  );
  const forecastMap = useMemo(
    () => new Map(forecastPoints.map((point) => [point.date, point.soh])),
    [forecastPoints]
  );

  const yDomain = useMemo(() => {
    const values = [
      ...points.map((point) => point.soh),
      ...forecastPoints.map((point) => point.soh)
    ];
    if (!values.length) {
      return { min: 0, max: 100 };
    }

    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    const span = maxVal - minVal;

    if (window === "30d" || window === "90d") {
      const pad = Math.max(0.2, span * 0.4);
      let min = Math.max(0, minVal - pad);
      let max = Math.min(100, maxVal + pad);
      if (max - min < 1.0) {
        const center = (max + min) / 2;
        min = Math.max(0, center - 0.6);
        max = Math.min(100, center + 0.6);
      }
      return { min, max };
    }

    return { min: 0, max: 100 };
  }, [points, forecastPoints, window]);

  const option = useMemo(
    () => ({
      animation: false,
      textStyle: { color: "#1e293b" },
      tooltip: { trigger: "axis", valueFormatter: (value: number) => `${value.toFixed(2)}%` },
      legend: {
        top: 0,
        textStyle: { color: "#334155", fontSize: 11 }
      },
      xAxis: {
        type: "category",
        data: xAxisDates,
        axisLabel: { color: "#64748b" }
      },
      yAxis: {
        type: "value",
        min: Number(yDomain.min.toFixed(2)),
        max: Number(yDomain.max.toFixed(2)),
        axisLabel: { color: "#64748b" }
      },
      grid: { left: 36, right: 24, top: 44, bottom: 36 },
      series: [
        {
          name: "Observed SOH",
          type: "line",
          smooth: true,
          data: xAxisDates.map((date) => historyMap.get(date) ?? null),
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
        },
        {
          name: "Forecast SOH",
          type: "line",
          smooth: false,
          connectNulls: true,
          showSymbol: false,
          data: xAxisDates.map((date) => forecastMap.get(date) ?? null),
          lineStyle: { width: 2, type: "dashed", color: "#f97316" },
          markLine:
            forecastPoints.length > 1
              ? {
                  symbol: "none",
                  lineStyle: { type: "dotted", color: "#f97316" },
                  label: { formatter: "Forecast start", color: "#ea580c", fontSize: 10 },
                  data: [{ xAxis: forecastPoints[0].date }]
                }
              : undefined
        }
      ]
    }),
    [xAxisDates, historyMap, forecastMap, yDomain, forecastPoints]
  );

  return <ReactECharts option={option} style={{ height: 280, width: "100%" }} />;
}
