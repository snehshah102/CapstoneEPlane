# Latent SOH

This workspace builds a condition-aware latent SOH label from parquet telemetry using an event-level state-space model.

It defaults to the corrected downstream parquet file:
- `data/event_timeseries.parquet`

Key points:
- Input observations are the per-event BMS SOH estimates from aux telemetry.
- The pipeline does **not** treat those observations as ground truth.
- Measurement noise is made time-varying with condition scores driven by current, `dI/dt`, `dT/dt`, SOC edge behavior, estimator disagreement, and estimator reset flags.
- `FilterPy` is the canonical backend.
- `PyKalman` is run as a comparison backend when enabled.
- `R_t` aggressiveness is controlled by named profiles:
  - `balanced` is the default
  - `current` reproduces the original heavier profile
  - `light` and `instability_focused` are available for tuning

Main entrypoint:

```bash
.venv/bin/python -m ml_workspace.latent_soh.build_latent_soh --plane-id 166 --rt-profile balanced
```

Outputs:
- `output/plane_<plane_id>/event_observation_table.csv`
- `output/plane_<plane_id>/latent_soh_event_table.csv`
- `output/plane_<plane_id>/diagnostics/smoother_summary.json`
- `output/plane_<plane_id>/diagnostics/backend_agreement_summary.json`
- `output/plane_<plane_id>/diagnostics/condition_score_summary.csv`
- `output/plane_<plane_id>/diagnostics/top_raw_spike_events.csv`
- `output/plane_<plane_id>/diagnostics/spike_feature_summary.csv`
- `output/plane_<plane_id>/diagnostics/plots/`

The notebook [latent_soh_walkthrough.ipynb](/Users/benfogerty/Desktop/EPlaneCapstone/CapstoneEPlane/ml_workspace/latent_soh/latent_soh_walkthrough.ipynb) explains the method and graphs the main diagnostics.
