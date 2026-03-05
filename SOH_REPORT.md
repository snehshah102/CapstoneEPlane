# SOH Estimation, Forecasting, SOC/RUL, and Scheduling Report
Last updated: 2026-03-02

This document is a detailed, single‑file information dump for the capstone report. It summarizes the SOH estimation methods and results, SOH forecasting approaches and benchmarks, SOC/RUL models, and the scheduling/recommendation system implemented in this repository. All metrics and configuration values are pulled from the current outputs in this repo.

---

## Executive Summary
We use **Kalman‑smoothed latent SOH** (FilterPy backend) as the canonical ground truth for forecasting and scheduling. In parallel, a **partial‑charge SOH estimator** based on IV/ICA features is available for charge events. Forecasting is event‑based with **target = `delta_soh`**, enabling forward simulation of SOH by iteratively applying predicted delta SOH. Circuit capacity and SOC rate are modeled with a POH‑based SOC‑per‑circuit curve calibrated per plane, plus a data‑driven SOC rate regressor. The scheduling optimizer uses these models to minimize predicted SOH loss while meeting flight demand and respecting SOC and charging constraints.

---

## Data Sources and Core Tables
Primary inputs used across the pipeline:
- `data/event_manifest.parquet` and `data/event_timeseries.parquet` for event definitions and timeseries measurements.
- `ml_workspace/latent_soh/output/plane_166/latent_soh_event_table.csv`
- `ml_workspace/latent_soh/output/plane_192/latent_soh_event_table.csv`
- `ml_workspace/battery_specs.yaml` for battery limits and charge/discharge constraints.
- `readME.md` for the POH traffic pattern circuit SOC table.

Event‑level modeling uses the latent SOH event table as the canonical source. Each row is an event (flight/mission, charge, etc. as labeled by `event_type`), with event timing, SOC spans, and telemetry summaries.

Current event dataset summary from `ml_workspace/soh_forecast/output/dataset_summary.json`:
- Total rows: 1204
- With next event available: 1200
- Gaps > 30 days: 10 (kept for diagnostics, excluded from training by default)
- Plane 166: 1106 rows, date range 2023‑05‑16 to 2025‑12‑02
- Plane 192: 98 rows, date range 2025‑06‑03 to 2025‑07‑05

---

## SOH Estimation (Ground Truth + Alternative Estimators)

### 1) Latent SOH Smoothing (Canonical Ground Truth)
Purpose: provide a stable SOH trajectory from noisy observed SOH.

Implementation: FilterPy Kalman smoothing. PyKalman is a comparison backend only.  
Canonical output: `latent_soh_smooth_pct` in the latent SOH event tables.

Plane 166 smoothing summary from `ml_workspace/latent_soh/output/plane_166/diagnostics/smoother_summary.json`:
- Events: 1106 (553 per battery)
- Base sigma per battery: 0.55
- Raw total variation: ~484/469
- Smoothed total variation: ~51.1/49.7
- Raw max upward jump: 29/25
- Smoothed max upward jump: ~1.02

Plane 192 smoothing summary from `ml_workspace/latent_soh/output/plane_192/diagnostics/smoother_summary.json`:
- Events: 98 (49 per battery)
- Base sigma per battery: 0.55
- Smoothed total variation: ~0.856/0.798

Notes:
- This smoothed series is the current ground truth for training the forecasting model.
- Observed SOH is retained for diagnostics and plotting.

### 2) Partial‑Charge SOH Estimation (IV/ICA‑Based)
Purpose: estimate SOH from partial charge events when full cycles are not available.

Charge event filters from `ml_workspace/partial_charge_soh/output/*/model_metrics.json`:
- Minimum rows per charge event: 1000
- Minimum SOC span: 20%
- Minimum voltage span: 15 V
- Minimum monotonic fraction: 0.95
- Maximum target gap: 24 hours

Plane 166 results:
- Best model: `hybrid_raw_soh_ica_iv`
- Test MAE: 3.41, RMSE: 6.05, R²: 0.376
- Baseline `raw_soh_median_charge` MAE: 3.53

Plane 192 results (small dataset):
- Best model: `baseline_raw_soh_median_charge`
- Test MAE: 0.434, RMSE: 0.463, R²: −7.19

Notes:
- Plane 192 has only 40 target pairs; low variance makes R² unstable.
- The IV/ICA feature models show promise on plane 166 but need more events to generalize.

### 3) ICA‑Focused Exploration
Notebook: `ml_workspace/ICA/ica_soh_estimation.ipynb`  
This contains exploratory ICA curve analysis and plots used to guide feature engineering and charge‑event filtering. It is not yet in the production pipeline.

---

## SOH Forecasting (Event‑Based, Target = `delta_soh`)

### Target and Trajectory Simulation
The forecasting target is `delta_soh`, defined as the change in latent smooth SOH between consecutive events for a given `(plane_id, battery_id)` ordered by `event_datetime`.

Trajectory simulation:
- `soh_{t+1} = soh_t + predicted_delta_soh`
- Iterating for next `N` events yields a degradation curve over time, flights, or equivalent full cycles (EFC).

### Event Dataset Construction
Implementation: `ml_workspace/soh_forecast/build_event_dataset.py`.

Key engineered fields are computed per event:
- Delta labels: `delta_soh`, `delta_days`, `delta_soh_per_day`.
- Equivalent full cycles: `efc_increment = abs(soc_span_pct)/100`, `cumulative_efc`, `delta_efc`, `delta_soh_per_efc`.
- Amp‑hour throughput: `event_ah = current_abs_mean_a * event_duration_s / 3600`, `cumulative_ah`, `delta_ah`, `delta_soh_per_ah`.
- Lag features: `*_lag1`, `*_diff` for selected metrics.
- 7‑day window features: `idle_time_7d_hours`, `charge_to_flight_ratio_7d`, `thermal_soak_40c_min_7d`, `events_count_7d`, `flight_duration_7d_hours`, `charge_duration_7d_hours`, `time_since_last_event_hours`.

Training default filter:
- Events with `delta_days > 30` are excluded from training but kept for diagnostics (`gap_gt_max`).

### Feature Set and Model Configuration
Current training config from `ml_workspace/soh_forecast/output/model_metrics.json`:
- Train/valid/test split: 70% / 15% / 15% by time (plane 166).
- Out‑of‑plane test: plane 192.
- `feature_set`: `fe2_mission`.
- `target_name`: `delta_soh`.
- Sequence lookback: 20 events.

### Models Benchmarked
Baselines:
- `baseline_zero`: predicts zero delta SOH.
- `baseline_median_by_event_type`: median delta SOH per event type.

Supervised models:
- `throughput_linear`: linear model with core throughput and thermal features.
- `elastic_net`: linear + regularization over expanded feature set.
- `hist_gbdt`: non‑linear tree ensemble.
- `arx_ridge`: linear model with autoregressive lag features on `delta_soh`.
- `sequence_gru`: GRU sequence model.

Sequence model status:
- `sequence_gru` currently reports `status = "no_sequences"`, indicating insufficient contiguous sequences for the configured lookback.

### Benchmark Results (Delta SOH)
All results below are from the latest run with target = `delta_soh`.

Plane 166 test split:
| Model | Test MAE | Test RMSE | Test R² |
| --- | --- | --- | --- |
| baseline_zero | 0.160 | 0.790 | −0.043 |
| baseline_median_by_event_type | 0.159 | 0.788 | −0.038 |
| throughput_linear | 0.192 | 0.786 | −0.034 |
| elastic_net | 0.162 | 0.790 | −0.044 |
| hist_gbdt | 0.179 | 0.791 | −0.045 |
| arx_ridge | 5.642 | 23.156 | −895.656 |

Plane 192 out‑of‑plane metrics:
| Model | OOD MAE | OOD RMSE | OOD R² |
| --- | --- | --- | --- |
| throughput_linear | 0.051 | 0.055 | −20.023 |
| elastic_net | 0.091 | 0.092 | −57.340 |
| hist_gbdt | 0.193 | 0.212 | −309.935 |
| arx_ridge | 0.194 | 0.210 | −305.763 |

Source: `ml_workspace/soh_forecast/output/model_metrics.json`.

Interpretation notes:
- R² is frequently negative because delta SOH variance is very small and noise dominates.
- The best plane‑166 test MAE is currently ~0.159–0.162 depending on baseline vs. elastic net.
- Sequence models need more contiguous sequences or a shorter lookback to train.

### Forecasting Outputs and Artifacts
Outputs are stored under `ml_workspace/soh_forecast/output/`:
- `event_dataset.csv`
- `model_metrics.json`
- `models/*.joblib`

Primary notebooks:
- `ml_workspace/soh_forecast/soh_benchmark_walkthrough.ipynb`
- `ml_workspace/soh_forecast/feature_engineering_walkthrough.ipynb`

---

## SOC / RUL / Circuit Capacity Models

### POH‑Based Circuit Capacity
Goal: translate SOH and SOC into expected circuits per flight, respecting reserve SOC.

POH traffic pattern SOC per circuit (interpolated by SOH) from `ml_workspace/circuit_capacity/output/circuit_model.json`:
- SOH grid: `[0, 20, 40, 60, 80, 100]`
- SOC per circuit: `[20, 16, 13, 12, 10, 9]`

Calibration:
- Plane 166 `k_plane = 0.80`
- Plane 192 `k_plane = 0.74`
- Default `k = 1.0` when no calibration is available

Circuit capacity formula:
- `soc_per_circuit(soh) = k_plane * interp_poh(soh)`
- Reserve SOC at landing: 30%
- `circuits_max = floor((soc_start_pct - 30) / soc_per_circuit(soh))`

### SOC Rate Model
Goal: predict SOC drop rate (pct/min) during flights given operating conditions.

Model metrics from `ml_workspace/circuit_capacity/output/soc_rate_model_metrics.json`:
- Test MAE: 0.192 (SOC %/min)
- Test RMSE: 0.263
- Test R²: 0.555

Outputs:
- `ml_workspace/circuit_capacity/output/circuit_model.json`
- `ml_workspace/circuit_capacity/output/soc_rate_model.joblib`
- `ml_workspace/circuit_capacity/output/soc_rate_model_metrics.json`

---

## Scheduling and Recommendation System

### Purpose
Given flight demand and charging availability, choose flight times and charge sessions that minimize predicted SOH degradation while meeting operational constraints.

### Implementation Modules
- `ml_workspace/scheduling/simulate_schedule.py`
- `ml_workspace/scheduling/optimize_schedule.py`
- `ml_workspace/scheduling/optimize_with_windows.py` (supports flight and charging windows)

### State Evolution (Core Equations)
SOC evolution:
- `soc_drop = circuits * soc_per_circuit(soh)`
- `soc_charge = charge_rate * duration`

SOH evolution:
- `soh_next = soh + predicted_delta_soh(features_from_event)`

### Constraints
- Reserve SOC at landing: at least 30%.
- Charge rate limited by `ml_workspace/battery_specs.yaml`.
- Minimum turnaround time default: 30 minutes.
- Flight availability and charging windows enforced in `optimize_with_windows.py`.

### Objective and Baselines
Objective: minimize cumulative predicted SOH loss while meeting fixed circuit demand.

Baselines:
- Always charge to 100%.
- Cluster flights early.
- Evenly spread flights.

---

## Notebooks and Visualizations
Forecasting walkthrough: `ml_workspace/soh_forecast/soh_benchmark_walkthrough.ipynb`.  
Feature engineering walkthrough: `ml_workspace/soh_forecast/feature_engineering_walkthrough.ipynb`.  
ICA exploration: `ml_workspace/ICA/ica_soh_estimation.ipynb`.

---

## Reproducibility (Key Commands)
Build event dataset:
```bash
python ml_workspace/soh_forecast/build_event_dataset.py
```

Train forecasting models:
```bash
python ml_workspace/soh_forecast/train_degradation_models.py
```

Predict delta SOH with a trained model:
```bash
python ml_workspace/soh_forecast/predict_degradation.py \
  --model-path ml_workspace/soh_forecast/output/models/elastic_net.joblib \
  --input-csv ml_workspace/soh_forecast/output/event_dataset.csv
```

Fit circuit capacity and SOC rate models:
```bash
python ml_workspace/circuit_capacity/fit_circuit_model.py
```

Run scheduler with windows:
```bash
python ml_workspace/scheduling/optimize_with_windows.py
```

---

## Limitations and Known Gaps
- Delta SOH variance is small and noisy; R² is unstable and often negative.
- Plane 192 has sparse data, limiting OOD validation.
- Sequence model is not training with a 20‑event lookback; it needs shorter lookback or pooled sequences.
- The 30‑day gap filter can exclude long idle periods; this may be relaxed if needed.
- Forecasting performance depends on the quality of the latent SOH smoothing output.

---

## Next Steps (Recommended)
1. Reduce sequence lookback or pool planes to make GRU/LSTM viable.
2. Add continuous‑time degradation features based on cumulative EFC and temperature‑soak integration.
3. Add uncertainty estimates for delta SOH to support robust scheduling.
4. Expand plane 192 data or use synthetic augmentation to improve OOD evaluation.
