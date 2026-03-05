# Capstone E-Plane Battery Health Workflow

This repository now contains the full working pipeline we built for battery-health analysis on the Velis telemetry:

- exploratory data analysis to understand when SOH spikes happen
- condition-aware latent SOH smoothing with a Kalman state-space model
- multiple SOH estimation methods for cross-checking battery health
- event-based SOH forecasting benchmarks
- a circuit-capacity model that translates SOH into expected loops or circuits

The main goal is no longer just to trust the raw BMS SOH fields. The goal is to build a battery-health workflow that is:

- more physically reasonable
- less sensitive to telemetry spikes and estimator resets
- usable for downstream forecasting and operational planning

## Current High-Level Conclusion

The main project conclusions at this point are:

- raw observed SOH contains large upward spikes and reset-like behavior, so it should not be treated as clean ground truth
- those spikes are disproportionately associated with charge events and near-top-of-charge behavior
- a condition-aware Kalman smoother in latent space produces a much more stable SOH trajectory and is the best internal SOH reference we currently have
- charge-event capacity estimates and ICA-based indicators broadly follow the same long-term degradation direction, even if they differ in noise level and local stability
- forecasting very small next-event SOH deltas is hard because the signal is tiny, so we moved the active benchmark toward next-flight, next-5-flight, and next-10-flight targets
- the current circuit-capacity model gives a practical way to convert SOH and SOC into an estimated number of loops or circuits

## Data and Main Outputs

Core data sources used by the current workflow:

- `data/event_manifest.parquet`
- `data/event_timeseries.parquet`
- `ml_workspace/latent_soh/output/plane_166/latent_soh_event_table.csv`
- `ml_workspace/latent_soh/output/plane_192/latent_soh_event_table.csv`
- `ml_workspace/battery_specs.yaml`

Current event-dataset summary from `ml_workspace/soh_forecast/output/dataset_summary.json`:

- total event rows: `1204`
- rows with a next event available: `1200`
- rows with event gaps greater than 30 days: `10`
- plane `166`: `1106` rows from `2023-05-16` to `2025-12-02`
- plane `192`: `98` rows from `2025-06-03` to `2025-07-05`

The main workspaces are:

- `ml_workspace/EDA`: exploratory notebooks
- `ml_workspace/latent_soh`: latent SOH smoothing pipeline
- `ml_workspace/soh_estimation`: alternative SOH estimators and comparisons
- `ml_workspace/soh_forecast`: forecasting models and benchmarks
- `ml_workspace/circuit_capacity`: loops or circuits model

## 1. EDA: What We Found

The first stage of work was exploratory analysis to understand whether the raw BMS SOH field could be trusted directly.

Main finding:

- most of the large raw SOH spikes happen around charge events, especially near the top of charge

This is supported directly by the latent-SOH diagnostics in `ml_workspace/latent_soh/output/plane_166/diagnostics/`:

- in `spike_feature_summary.csv`, the spike group is about `71%` to `73%` charge events, versus about `53%` to `54%` charge events in the non-spike group
- in `top_raw_spike_events.csv`, about `72.2%` of the top raw spike events are charge events
- about `68.1%` of those top spike events reach `soc_max_pct >= 99`
- about `51.4%` of those top spike events are both charge events and near full charge

Interpretation:

- charging to or near `100%` is one of the main regimes where the observed BMS SOH estimate becomes unstable
- this is consistent with estimator resets, top-of-charge correction behavior, and disagreement between embedded SOC or capacity estimators
- that is why the rest of the project stopped treating raw observed SOH as clean truth

Relevant EDA notebooks include:

- `ml_workspace/EDA/observed_soh_event_timeseries.ipynb`
- `ml_workspace/EDA/soh_visualization.ipynb`
- `ml_workspace/EDA/soh_vs_soc_throughput.ipynb`
- `ml_workspace/EDA/soh_without_charging_and_charge_event_diagnostics.ipynb`

## 2. Latent SOH Smoothing with a Kalman Model

### Why We Did It

The raw `bat 1 soh` and `bat 2 soh` telemetry behaves like a noisy observation, not like a clean physical state.

Problems with the raw signal:

- sudden upward jumps that are not physically plausible as true battery recovery
- inconsistent values across neighboring events
- instability around charging and reset-like events
- disagreement between Kalman SOC and coulomb-counting SOC

So instead of forecasting the raw observation directly, we built a latent SOH model that assumes:

- there is a hidden underlying SOH state
- the raw BMS SOH is only a noisy observation of that state
- observation trust should change with operating conditions

### What We Implemented

The latent SOH pipeline lives in `ml_workspace/latent_soh`.

The current canonical backend is `FilterPy`. `PyKalman` is only kept as a comparison backend.

The smoother uses:

- event-level SOH observations from the BMS
- a state-space model with latent level and trend behavior
- condition-aware observation noise `R_t`

The measurement noise is increased when the event looks unreliable. That reliability logic is driven by scores such as:

- current severity
- `dI/dt`
- `dT/dt`
- SOC edge behavior
- observation instability
- Kalman-vs-coulomb SOC disagreement
- estimator reset flags

This means we trust the observation less when the telemetry looks like a spike or reset regime, and we trust it more when conditions are clean.

### What the Result Was

The smoothing output is much more stable than the raw BMS SOH.

From `ml_workspace/latent_soh/output/plane_166/diagnostics/smoother_summary.json`:

- total events: `1106`
- sigma base per battery: `0.55`
- raw total variation:
  - battery `1`: `484.0`
  - battery `2`: `469.0`
- smoothed total variation:
  - battery `1`: `51.15`
  - battery `2`: `49.69`
- raw max upward jump:
  - battery `1`: `29.0`
  - battery `2`: `25.0`
- smoothed max upward jump:
  - battery `1`: about `1.02`
  - battery `2`: about `1.02`

From `ml_workspace/latent_soh/output/plane_192/diagnostics/smoother_summary.json`:

- total events: `98`
- smoothed total variation:
  - battery `1`: `0.856`
  - battery `2`: `0.798`

Practical result:

- the smoother removes most of the unrealistic step changes
- it preserves the slow degradation trend
- it gives us a far better internal SOH reference than raw observed SOH

That is why Kalman-smoothed latent SOH became the canonical internal SOH series for development and model-building.

## 3. SOH Estimation Methods We Tried

We did not rely on only one SOH estimate. We compared several methods and looked at whether they followed a similar long-term degradation trend.

### 3.1 Raw Observed SOH

This is the simplest signal:

- directly use the BMS-reported `observed_soh_pct`

Pros:

- always available in the event table
- easy to inspect

Cons:

- noisy
- spiky
- sensitive to charge behavior and resets

So this is useful as a reference signal, but not as a standalone truth signal.

### 3.2 Charge-Event Capacity Estimation from Current Integration

This method is implemented in `ml_workspace/soh_estimation/physics_based_soh.py` and demonstrated in:

- `ml_workspace/soh_estimation/physics_based_soh_from_charge_events.ipynb`
- `ml_workspace/soh_estimation/soh_capacity_vs_ica_anchor_comparison.ipynb`

This is the place where coulomb counting and capacity estimation meet, so the wording matters.

What we are doing here is:

- integrate charge current over time during a usable charge event to get delivered charge in amp-hours
- use the corresponding SOC window to infer the pack's effective total capacity
- convert that estimated capacity into an SOH percentage

So the accurate description is:

- `coulomb counting` is the mechanism used to measure charge throughput
- `capacity estimation` is the resulting model output
- `SOH estimation` is the final percent derived from that estimated capacity

This is not a separate standalone SOC-tracking model. It is a charge-event capacity-anchor method derived from current integration.

What it does:

- loads `charge_event_capacity_summary.csv`
- uses charge-event current and time integration to build `delivered_ah`
- uses the observed SOC span of that event to infer `capacity_est_ah`
- converts that into SOH

The two main forms are:

- `physics_soh_absolute_pct = 100 * capacity_est_ah / rated_capacity_ah`
- `physics_soh_relative_pct = 100 * capacity_est_ah / reference_capacity_ah`

The absolute version is the more physically direct one because it compares to rated capacity. The relative version compares against the early-event reference capacity for that battery.

Verified current results from the code on the local artifacts:

Plane `166`, overall:

- `physics_soh_absolute_pct`: `MAE = 7.90`, `RMSE = 9.92`, `R2 = 0.106`
- `physics_soh_relative_pct`: `MAE = 10.42`, `RMSE = 12.18`, `R2 = -0.348`

Plane `192`, overall:

- `physics_soh_absolute_pct`: `MAE = 1.17`, `RMSE = 1.25`, `R2 = 0.472`
- `physics_soh_relative_pct`: `MAE = 2.64`, `RMSE = 2.88`, `R2 = -1.822`

Interpretation:

- the absolute charge-event capacity anchor performs better than the relative anchor on the current data
- it is useful as a physics-based cross-check, especially on charge events
- it is not as smooth or as broadly available as the latent SOH series, since it depends on charge-event quality and coverage

### 3.3 ICA-Based Methods

ICA work lives mainly in:

- `ml_workspace/soh_estimation/soh_capacity_vs_ica_anchor_comparison.ipynb`

What we did:

- extracted ICA-style candidate features over multiple charge-voltage windows
- compared those windows against the capacity-anchor trajectory
- ranked windows by how well they followed the temperature-normalized capacity anchor

Main takeaway:

- the better ICA windows broadly track the same long-term degradation trend as the capacity anchors
- they look reasonable when compared via best-fit or trend-line views over event index
- they are promising as an auxiliary electrochemical indicator, but not yet the primary production SOH label

### 3.4 IV Method

We also explored IV-style windows in the same anchor-comparison notebook.

Current conclusion:

- IV estimates were less reliable than the best ICA windows in this workflow
- IV was removed from the final axis-comparison view in the notebook because the estimations were too unstable to trust equally

### 3.5 Combined Interpretation of the Estimation Stage

At a high level, the following methods broadly lined up in trend, even if their noise levels differed:

- raw observed SOH
- charge-event capacity anchors derived from current integration
- best ICA windows

That agreement is important because it suggests we are not inventing the degradation trend with one model only. Different estimation views point in roughly the same direction, even though the latent Kalman-smoothed series is the cleanest version for downstream modeling.

## 4. SOH Forecasting

### Why Forecasting Needed Its Own Pipeline

Once we had a better SOH reference, the next goal was forecasting:

- given the current battery state and event history, estimate future SOH

We first tested very small next-event delta targets. That exposed a practical issue:

- if the target is only the next tiny SOH change, the signal is often comparable to the noise

That makes:

- `R2` unstable
- zero-change baselines unusually strong
- model ranking sensitive to minor errors

Because of that, the active benchmark was shifted toward multi-horizon flight targets:

- next flight
- next 5 flights
- next 10 flights

The current runner is:

- `ml_workspace/soh_forecast/soh_forecast_model_runner.ipynb`

The current benchmark output folder is:

- `ml_workspace/soh_forecast/output/observed_target_runner_plane_166`

### Models We Benchmarked

We benchmarked a broad set of forecasting models in `ml_workspace/soh_forecast/models`:

- `naive_zero_delta`
- `ridge_raw_only`
- `ridge_raw_plus_latent`
- `elastic_raw_plus_latent_plus_history`
- `ridge_raw_plus_latent_plus_history`
- `gbdt_raw_plus_latent_plus_history`
- `random_forest_raw_plus_latent_plus_history`
- `gam_spline_raw_plus_latent_plus_history`
- `lstm_sequence`
- `gru_sequence`
- `physics_hybrid_nn`
- `physics_informed_pinn`

Notes:

- the active benchmark now forecasts observed SOH horizons only
- some feature-set variants still include latent-derived features as inputs for comparison
- the old structured physics model has been renamed to `physics_hybrid_nn`
- the newer `physics_informed_pinn` is the more standard ODE-style PINN

### Current Active Results

The current active benchmark is observed-SOH forecasting over flight-count horizons.

#### Next Flight

From `observed_flight_1_metrics_common_subset.csv`, the best test MAE is:

- `naive_zero_delta`: `MAE = 1.9125`, `RMSE = 4.6864`, `R2 = 0.7656`

Among learned models:

- `physics_informed_pinn`: `MAE = 2.0659`, `RMSE = 4.5337`, `R2 = 0.7806`
- `physics_hybrid_nn`: `MAE = 2.4171`, `RMSE = 3.9391`, `R2 = 0.8344`

Interpretation:

- next-flight SOH change is still small enough that the no-change baseline remains hard to beat on MAE
- the learned physics models can still improve fit quality in terms of trajectory shape or `R2`

#### Next 5 Flights

From `observed_flight_5_metrics_common_subset.csv`, the best test MAE is:

- `ridge_raw_only`: `MAE = 5.1457`, `RMSE = 6.5981`, `R2 = 0.4832`

Other notable test results:

- `physics_hybrid_nn`: `MAE = 5.1787`, `RMSE = 7.5586`, `R2 = 0.3217`
- `physics_informed_pinn`: `MAE = 5.6731`, `RMSE = 7.8948`, `R2 = 0.2601`
- `naive_zero_delta`: `MAE = 5.4779`, `RMSE = 7.8819`, `R2 = 0.2625`

Interpretation:

- the 5-flight horizon has a stronger signal than next-flight delta forecasting
- simple linear models are still competitive
- the physics models are plausible but not yet dominant on this horizon

#### Next 10 Flights

The long-horizon comparison has now been changed from `observed_flight_30` to `observed_flight_10`.

At the time of this README update, the benchmark configuration and target pipeline have been updated, but the notebook outputs have not yet been regenerated for the new 10-flight horizon. So the current repo state is:

- `next 10 flights` is the active long horizon in the method comparison
- the old `next 30 flights` result files should be treated as stale historical artifacts
- the benchmark notebook should be rerun to refresh the metrics and plots for `observed_flight_10`

### Benchmarking Scheme: How Metrics Were Computed

The current benchmarking logic is in:

- `ml_workspace/soh_forecast/common.py`
- `ml_workspace/soh_forecast/benchmarking.py`

The evaluation scheme is:

- chronological split on plane `166`
- `70%` train, `15%` validation, `15%` test
- plane `192` used as a separate `holdout` split when available

Why the holdout split exists:

- it is a stronger generalization check than the in-plane test split
- train, validation, and test all come from the primary plane chronology
- holdout uses an entirely different plane stream, so it tells us whether the model generalizes beyond the development plane

For every model, we compute both:

- level metrics on predicted next SOH
- delta metrics on implied SOH change from current SOH

The metric function returns:

- `level_mae`
- `level_rmse`
- `level_r2`
- `delta_mae`
- `delta_rmse`
- `delta_r2`

We also keep two comparison tables:

- `metrics_by_available_predictions`: each model is scored on the rows where it actually produced a prediction
- `metrics_common_subset`: all models are scored only on the shared subset of rows where every compared model produced a prediction

The common-subset table is the fairest model-to-model comparison, because it removes row-coverage differences as a source of bias.

## 5. Circuit Capacity / Number of Loops per SOH

The current loops or circuits model lives in:

- `ml_workspace/circuit_capacity/fit_circuit_model.py`
- `ml_workspace/circuit_capacity/predict_circuits.py`

We also added a demonstration notebook:

- `ml_workspace/circuit_capacity/circuit_capacity_model_demo.ipynb`

### What the Circuit Model Is For

This model answers an operational question:

- given a battery SOH and a starting SOC, how many circuits or loops can the battery complete before hitting the reserve floor?

### How It Works

It has two pieces.

#### 5.1 SOC Consumed Per Circuit

This uses a POH-based SOC-per-circuit curve, calibrated by plane.

Saved calibration from `ml_workspace/circuit_capacity/output/circuit_model.json`:

- SOH grid: `[0, 20, 40, 60, 80, 100]`
- base SOC per circuit: `[20, 16, 13, 12, 10, 9]`
- reserve SOC: `30%`
- plane calibration:
  - plane `166`: `k_plane = 0.80`
  - plane `192`: `k_plane = 0.74`

The main formula is:

- `soc_per_circuit(soh) = k_plane * interp_poh(soh)`
- `circuits_max = floor((soc_start_pct - reserve_soc_pct) / soc_per_circuit(soh))`

This is the direct loops-per-SOH model.

#### 5.2 SOC Depletion Rate Model

We also fit a linear regression to predict SOC depletion rate during flights from operating conditions.

Saved metrics from `ml_workspace/circuit_capacity/output/soc_rate_model_metrics.json`:

- train:
  - `MAE = 0.128`
  - `RMSE = 0.187`
  - `R2 = 0.683`
- validation:
  - `MAE = 0.093`
  - `RMSE = 0.121`
  - `R2 = 0.702`
- test:
  - `MAE = 0.192`
  - `RMSE = 0.263`
  - `R2 = 0.555`
- OOD:
  - `MAE = 0.196`
  - `RMSE = 0.242`
  - `R2 = 0.541`

That makes the circuit-capacity workspace useful for both:

- static planning from SOH and SOC
- more context-aware SOC consumption estimates under typical mission conditions

## 6. Current Practical Position

If someone asks what the current recommended workflow is, the answer is:

1. Use EDA to identify problematic regimes, especially charge-related and full-charge spike behavior.
2. Use the condition-aware latent SOH smoother as the cleanest internal SOH trajectory.
3. Use charge-event capacity anchors and ICA methods as cross-check estimators, not as the only truth source.
4. Forecast observed SOH over flight-count horizons instead of relying only on tiny next-event deltas.
5. Use the circuit-capacity model to translate SOH into estimated loops or circuits for operations planning.

## 7. Most Important Files

If you want the shortest path through the project, start here:

- `readME.md`
- `SOH_REPORT.md`
- `ml_workspace/latent_soh/README.md`
- `ml_workspace/soh_forecast/models/README.md`
- `ml_workspace/soh_forecast/soh_forecast_model_runner.ipynb`
- `ml_workspace/circuit_capacity/circuit_capacity_model_demo.ipynb`

Key code entry points:

- `ml_workspace/latent_soh/build_latent_soh.py`
- `ml_workspace/soh_estimation/physics_based_soh.py`
- `ml_workspace/soh_forecast/feature_pipeline.py`
- `ml_workspace/soh_forecast/benchmarking.py`
- `ml_workspace/circuit_capacity/fit_circuit_model.py`
- `ml_workspace/circuit_capacity/predict_circuits.py`

## 8. Summary of the Updates We Made

The major updates completed in this repository are:

- documented and confirmed that raw SOH spikes are mainly a charging and high-SOC problem
- built and validated a condition-aware latent SOH Kalman smoothing pipeline
- kept `FilterPy` as the canonical latent SOH backend
- verified a charge-event coulomb-counted capacity SOH estimator
- compared capacity-anchor and ICA-style estimation approaches
- clarified that IV estimates were not reliable enough to keep in the final ICA comparison view
- expanded SOH forecasting into a reusable benchmarking framework
- renamed the old physics model to `physics_hybrid_nn`
- added a separate standard `physics_informed_pinn`
- moved the active benchmark to observed SOH over next-flight, next-5-flight, and next-30-flight horizons
- documented how metrics are computed and why the holdout split exists
- added and cleaned up the circuit-capacity model and created a demo notebook for it

That is the current project state.
