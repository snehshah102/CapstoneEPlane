"use client";

import ReactECharts from "echarts-for-react";
import { useMemo } from "react";

type Props = {
  sohCurrent: number;
};

export function RangeEnduranceChart({ sohCurrent }: Props) {
  const option = useMemo(() => {
    const chargePoints = [50, 60, 70, 80, 90, 100];
    const baseRangeKm = 230 * (sohCurrent / 100);
    const rangeSeries = chargePoints.map((soc) =>
      Number(((baseRangeKm * soc) / 100).toFixed(1))
    );
    const enduranceSeries = rangeSeries.map((km) =>
      Number((km / 3.1).toFixed(1))
    );

    return {
      animation: false,
      tooltip: {
        trigger: "axis"
      },
      legend: {
        data: ["Estimated Range (km)", "Estimated Endurance (min)"],
        textStyle: { color: "#475569" }
      },
      xAxis: {
        type: "category",
        data: chargePoints.map((value) => `${value}%`),
        axisLabel: { color: "#64748b" }
      },
      yAxis: [
        {
          type: "value",
          name: "Range (km)",
          axisLabel: { color: "#64748b" },
          nameTextStyle: { color: "#64748b" }
        },
        {
          type: "value",
          name: "Endurance (min)",
          axisLabel: { color: "#64748b" },
          nameTextStyle: { color: "#64748b" }
        }
      ],
      grid: { left: 48, right: 48, top: 40, bottom: 36 },
      series: [
        {
          name: "Estimated Range (km)",
          type: "line",
          smooth: true,
          lineStyle: { width: 3, color: "#2563eb" },
          data: rangeSeries,
          areaStyle: { color: "rgba(37,99,235,0.14)" }
        },
        {
          name: "Estimated Endurance (min)",
          type: "line",
          smooth: true,
          yAxisIndex: 1,
          lineStyle: { width: 3, color: "#0f766e" },
          data: enduranceSeries,
          areaStyle: { color: "rgba(15,118,110,0.12)" }
        }
      ]
    };
  }, [sohCurrent]);

  return <ReactECharts option={option} style={{ height: 280, width: "100%" }} />;
}
