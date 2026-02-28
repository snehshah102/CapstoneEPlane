# Battery Inference

This workspace contains a plane-level battery type inference workflow based on charging-event telemetry.

It estimates effective pack capacity from partial charging traces and uses top-of-charge voltage as a secondary cross-check.

## Run

```bash
python ml_workspace/battery_inference/infer_battery_type.py --plane-id 166
```

## Outputs

The script writes outputs under:

- `ml_workspace/battery_inference/output/plane_<plane_id>/charge_event_capacity_summary.csv`
- `ml_workspace/battery_inference/output/plane_<plane_id>/plane_battery_inference.json`
- `ml_workspace/battery_inference/output/plane_<plane_id>/diagnostic_plots.png`

# Plane 166 Battery Inference Results

## Result

- Inferred battery type: `PB345V119E-L`
- Confidence: `0.80`

## Brief Explanation

The inference favored `PB345V119E-L` because the charging-event capacity proxy was much closer to the `29.0 Ah` rated-capacity battery than the `33.0 Ah` alternative.

Key supporting results:

- Valid event-battery segments used: `261`
- Median estimated effective capacity: `26.13 Ah`
- Distance to `29.0 Ah`: `2.87 Ah`
- Distance to `33.0 Ah`: `6.87 Ah`
- Median top-of-charge voltage: `404.2 V`

The voltage cross-check also supported the same conclusion. A top-of-charge voltage around `404 V` is more consistent with the higher-voltage `PB345V119E-L` pack than the `PB345V124E-L` pack.

## Why Confidence Was Not Higher

Confidence was reduced slightly because the capacity spread was still somewhat broad:

- Capacity IQR: `2.16 Ah`

That means the partial-charge capacity proxy is directionally useful for battery-type inference, but not precise enough to treat as a direct rated-capacity measurement.

## Supporting Files

- `charge_event_capacity_summary.csv`
- `plane_battery_inference.json`
- `diagnostic_plots.png`
