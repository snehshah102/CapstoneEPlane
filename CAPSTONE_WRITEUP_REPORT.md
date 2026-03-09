# Capstone Writeup: Battery Health Intelligence and Operational Decision Support for Electric Aircraft

## Executive Summary

This capstone addresses a practical problem in electric aviation: battery telemetry is available, but raw battery health signals are noisy, operationally unstable, and difficult to convert into usable maintenance or flight-planning decisions. In the Velis telemetry used in this repository, the embedded Battery Management System (BMS) State of Health (SOH) field exhibits large upward spikes, reset-like behavior, and strong sensitivity to charging conditions, especially near full state of charge. That makes the raw SOH field unsuitable as a clean ground-truth label for forecasting or scheduling.

Our solution is a full battery-health workflow that transforms noisy aircraft telemetry into a stable battery-health estimate, forecasts future degradation, translates SOH into practical flight capacity, and exposes the results through an interactive frontend for maintenance and operations decision support.

The implemented system has five major layers:

1. Exploratory analysis to understand the behavior and failure modes of raw SOH telemetry.
2. A condition-aware latent SOH model using Kalman filtering and RTS smoothing to estimate a stable hidden battery-health trajectory.
3. Event-based SOH forecasting models that predict future degradation from flight, charge, thermal, and throughput features.
4. A circuit-capacity and SOC-rate layer that converts health estimates into expected operational capacity.
5. A scheduling and recommendation layer, surfaced in a Next.js frontend, that helps users understand battery condition, plan lower-stress operations, and compare mission choices.

The current repository demonstrates that:

- Raw observed SOH should not be treated as trustworthy ground truth.
- Condition-aware latent SOH smoothing dramatically reduces unrealistic variation while preserving long-term degradation trends.
- Immediate next-event SOH change is a difficult prediction target because the signal is extremely small relative to noise.
- Multi-horizon prediction and operational decision support are more useful than raw one-step forecasting alone.
- A practical frontend can present the modeling outputs as interpretable dashboards, calendar-based recommendations, and interactive mission-planning tools.

This project therefore contributes not just a model, but a complete decision-support workflow for battery-aware electric aircraft operations.

---

## 1. Problem Definition and Motivation

### 1.1 Why battery health matters in electric aircraft

Battery health directly affects:

- achievable flight endurance,
- reserve margins,
- charging strategy,
- maintenance timing,
- aircraft availability,
- and long-term battery replacement cost.

For electric aircraft, these are not secondary concerns. They are central to whether the aircraft can be dispatched safely and economically.

The challenge is that battery-health monitoring in practice is often mediated through onboard estimators that are imperfect. Operators may have access to BMS-reported SOH, SOC, current, voltage, and temperature telemetry, but those signals are influenced by estimator resets, incomplete charge cycles, thermal effects, and changing operating conditions. A number that appears simple in the dashboard may hide substantial uncertainty.

### 1.2 The core problem in this capstone

The initial question behind the project was effectively:

Can we use aircraft telemetry to estimate battery health reliably enough to support forecasting and operational planning?

After exploratory analysis, that question sharpened into a more specific one:

How can we build a battery-health workflow that does not trust the raw SOH value blindly, but instead produces a stable internal health estimate, forecasts future degradation, and connects the result to real operational decisions?

### 1.3 Project goals

The goals of the capstone were:

- identify whether raw BMS SOH is reliable enough for modeling,
- build a more physically reasonable internal SOH reference,
- engineer event-level features from telemetry for degradation modeling,
- evaluate forecasting approaches for battery-health evolution,
- convert SOH into operational capacity such as circuits or loops,
- and present the outputs in an interactive system that is understandable to non-ML users.

### 1.4 High-level research question

The capstone can be summarized by the following research question:

Can noisy electric-aircraft telemetry be transformed into a stable, decision-useful battery-health intelligence system that supports both technical analysis and operational planning?

---

## 2. System Overview

The repository implements an end-to-end workflow with the following stages:

1. Data ingestion and event-level telemetry assembly.
2. Exploratory data analysis on observed SOH behavior.
3. Latent SOH estimation using a condition-aware state-space model.
4. Feature engineering for event-based degradation forecasting.
5. Benchmarking of forecasting models.
6. Conversion of SOH to operational capacity using circuit and SOC models.
7. Schedule simulation and optimization using predicted degradation.
8. Frontend dashboards and interactive tools for interpretation and planning.

The main workspaces in the repository are:

- `ml_workspace/EDA`
- `ml_workspace/latent_soh`
- `ml_workspace/soh_forecast`
- `ml_workspace/circuit_capacity`
- `ml_workspace/scheduling`
- `frontend`

The top-level repository description in `readME.md` aligns with this structure and defines the project as a full battery-health workflow rather than a single-model experiment.

---

## 3. Data and Problem Formulation

### 3.1 Data sources

The pipeline uses event-level and timeseries telemetry derived from the aircraft data:

- `data/event_manifest.parquet`
- `data/event_timeseries.parquet`
- `ml_workspace/latent_soh/output/plane_166/latent_soh_event_table.csv`
- `ml_workspace/latent_soh/output/plane_192/latent_soh_event_table.csv`
- `ml_workspace/battery_specs.yaml`

The latent SOH event tables are especially important because they act as the canonical event-level modeling tables after telemetry cleaning and state estimation.

### 3.2 Dataset size

From `ml_workspace/soh_forecast/output/dataset_summary.json`, the current event dataset contains:

- 1204 total event rows,
- 1200 rows with a next event available,
- 10 rows with event gaps greater than 30 days.

Per aircraft:

- Plane 166: 1106 rows, spanning 2023-05-16 to 2025-12-02.
- Plane 192: 98 rows, spanning 2025-06-03 to 2025-07-05.

This immediately reveals an important modeling constraint: the dataset is highly imbalanced across aircraft. Plane 166 is the primary training source, while plane 192 functions more like an out-of-distribution or small holdout domain than a full second training population.

### 3.3 Event-based framing

The project is not framed as high-frequency time-series forecasting at the raw telemetry sample level. Instead, it uses an event-based representation, where each row corresponds to a meaningful battery event such as:

- flight,
- charge,
- or other operational intervals.

This framing is appropriate because:

- maintenance and scheduling decisions happen at event scale,
- degradation is slow and cumulative,
- and event summaries are easier to interpret and align with operations than second-by-second raw data.

### 3.4 Forecasting target

The active forecasting target is `delta_soh`, defined as the change in SOH between consecutive events. The repo also supports multi-horizon targets such as future SOH after 1, 5, 10, 15, or 20 flights. This shift from absolute SOH to incremental change is important because it turns forecasting into a degradation modeling problem rather than a static regression problem.

---

## 4. Exploratory Data Analysis and Problem Analysis

### 4.1 Why EDA was necessary

Before fitting any model, the team first had to answer a foundational question:

Is the raw BMS-reported SOH even usable as truth?

That was not a minor preprocessing check. It became the central modeling issue in the project.

### 4.2 Observed behavior of raw SOH

EDA showed that the observed SOH signal contains:

- sudden upward jumps that are not physically plausible as true battery recovery,
- local discontinuities across nearby events,
- behavior suggestive of estimator resets,
- and instability around charging and near-full-SOC regimes.

These findings motivated a shift away from treating raw SOH as a direct label.

### 4.3 Evidence from spike diagnostics

The strongest evidence comes from the plane 166 latent-SOH diagnostics:

- In `spike_feature_summary.csv`, spike events are about 71% to 73% charge events, while non-spike events are about 53% to 54% charge events.
- In `top_raw_spike_events.csv`, roughly 72.2% of the top raw spike events are charge events.
- Roughly 68.1% of those spike events reach `soc_max_pct >= 99`.
- Roughly 51.4% are both charge events and near-full-charge events.

This matters because true battery degradation should not exhibit large positive jumps simply because the battery was recently charged to the top of the SOC range.

### 4.4 Interpretation

The EDA supports the following interpretation:

- Raw SOH is not a pure physical state measurement.
- It behaves like an estimator output whose reliability changes with operating conditions.
- Charge events, estimator resets, and SOC-edge behavior strongly affect observation quality.

That interpretation directly motivated the latent-state approach used in the next stage.

---

## 5. Latent SOH Modeling

### 5.1 Modeling rationale

The central modeling choice in this capstone is to treat SOH as a hidden latent state rather than a directly observed truth value.

The conceptual model is:

- there exists a true underlying battery-health state,
- the BMS-reported SOH is a noisy observation of that state,
- and the noise level changes depending on telemetry conditions.

This is a stronger and more realistic assumption than fitting a forecasting model directly to raw observed SOH.

### 5.2 State-space formulation

The latent SOH model in `ml_workspace/latent_soh` uses a 1D Kalman state-space system:

- state: latent SOH,
- process model: latent SOH evolves gradually over time,
- measurement model: observed SOH is a noisy observation of latent SOH.

The repository README documents the structure as:

- latent transition with process noise `Q_t`,
- measurement model with observation noise `R_t`,
- FilterPy as the canonical backend,
- RTS smoothing for retrospective latent trajectories.

### 5.3 Condition-aware measurement noise

The key idea is not just Kalman smoothing by itself, but condition-aware measurement noise.

Observation trust is reduced when the telemetry suggests instability. The noise model uses condition scores derived from features such as:

- current severity,
- `dI/dt`,
- `dT/dt`,
- SOC edge behavior,
- observation instability,
- Kalman-vs-coulomb SOC disagreement,
- estimator reset flags,
- and event-type effects.

This is one of the strongest technical contributions in the project because it turns smoothing from a generic denoising step into a telemetry-aware estimation method.

### 5.4 Canonical outputs

The latent SOH pipeline produces:

- `latent_soh_smooth_pct`
- `latent_soh_smooth_std_pct`
- `latent_soh_filter_pct`
- `latent_soh_filter_std_pct`

The smoothed series is the clean retrospective reference. The causal filter-only series is the forecasting-safe version.

### 5.5 Data leakage handling

The repository explicitly notes a critical issue: RTS smoothing uses future observations and is therefore not causal. If the smoothed series were used directly as a training label for forecasting, that would leak future information.

To prevent leakage:

- forecasting targets are built from the causal filter series,
- features are restricted to information available at time `t`,
- and splits are chronological.

This is important to emphasize in the report because it shows the project addressed one of the most common failure modes in time-aware ML evaluation.

### 5.6 Selected latent-SOH configuration

For plane 166, the current canonical latent smoother uses:

- `rt_profile = current`
- `q_day_sigma_pct = 0.1`
- base sigma per battery = 0.75

For plane 192, the current summary shows:

- `rt_profile = balanced`
- `q_day_sigma_pct = 0.05`
- base sigma per battery = 0.55

### 5.7 Quantitative smoothing results

For plane 166:

- raw total variation: 484.0 and 469.0,
- smoothed total variation: 46.89 and 45.48,
- raw max upward jump: 29.0 and 25.0,
- smoothed max upward jump: 0.70 and 0.73.

For plane 192:

- raw total variation: 5.0 and 5.0,
- smoothed total variation: 0.856 and 0.798.

These are large improvements. The model does not simply smooth a little; it removes an order of magnitude of unrealistic variation while preserving the degradation trend.

### 5.8 Why this matters

The latent SOH model is the foundation of the rest of the project. Without it:

- the forecasting targets would be contaminated by observation artifacts,
- the frontend health metrics would be misleading,
- and the scheduling layer would optimize against noise instead of health.

---

## 6. Feature Engineering and Degradation Modeling

### 6.1 Forecasting philosophy

The forecasting task is hard because event-to-event SOH change is very small. In such settings:

- naive models can perform competitively,
- variance is tiny,
- and standard metrics like R-squared can become strongly negative even when MAE appears reasonable.

The project recognizes this and expands the problem beyond one-step prediction into multi-horizon forecasting and decision support.

### 6.2 Event features

The forecasting pipeline computes event-level features including:

- delta labels such as `delta_soh`, `delta_days`, `delta_soh_per_day`,
- equivalent full cycles and cumulative EFC,
- amp-hour throughput,
- lag features,
- 7-day rolling activity and charging summaries,
- thermal and current stress proxies,
- internal resistance and voltage sag proxies,
- idle-time and high-SOC exposure features,
- latent-SOH derived features.

This feature design reflects battery-aging intuition: degradation depends not only on time, but on throughput, temperature, usage intensity, storage conditions, and recent history.

### 6.3 Selected observed-feature families

From `selected_feature_family_summary.csv`, the selected feature families include:

- physics features,
- operating-condition features,
- latent features,
- static categorical features,
- and history features.

The highest mean contribution among families comes from history and latent features, which is consistent with the project’s claim that raw SOH alone is not enough.

### 6.4 Example selected features

The selected features include variables such as:

- observed SOH rolling min and max,
- latent filter state and short-term latent deltas,
- event count,
- stress-index summaries,
- internal-resistance rolling statistics,
- SOC disagreement metrics,
- temperature severity,
- current RMS proxies,
- event type indicators.

This mix shows the model is not purely data-driven in a black-box sense. It uses physically motivated and operationally meaningful engineered signals.

---

## 7. Forecasting Models and Benchmarking

### 7.1 Models benchmarked

The current forecasting benchmark includes:

- `baseline_zero`
- `baseline_median_by_event_type`
- `throughput_linear`
- `elastic_net`
- `hist_gbdt`
- `arx_ridge`
- `sequence_gru`

The repository also contains additional model files such as:

- ridge,
- GAM spline,
- random forest,
- physics-informed neural models,
- LSTM and GRU sequence models,
- and physics-hybrid variants.

### 7.2 Training configuration

From `model_metrics.json`, the active benchmark uses:

- time-based split,
- train fraction 0.70,
- validation fraction 0.15,
- max gap days 30,
- lookback 20,
- target `delta_soh`,
- feature set `fe2_mission`,
- lag features enabled,
- interaction features enabled.

### 7.3 Immediate next-event forecasting results

For the test split on plane 166:

- `baseline_zero`: MAE 0.160, RMSE 0.790, R2 -0.043
- `baseline_median_by_event_type`: MAE 0.159, RMSE 0.788, R2 -0.038
- `throughput_linear`: MAE 0.192, RMSE 0.786, R2 -0.034
- `elastic_net`: MAE 0.162, RMSE 0.790, R2 -0.044
- `hist_gbdt`: MAE 0.179, RMSE 0.791, R2 -0.045
- `arx_ridge`: MAE 5.642, RMSE 23.156, R2 -895.656

For out-of-distribution evaluation on plane 192:

- `throughput_linear`: OOD MAE 0.051, RMSE 0.055, R2 -20.023
- `elastic_net`: OOD MAE 0.091, RMSE 0.092, R2 -57.340
- `hist_gbdt`: OOD MAE 0.193, RMSE 0.212, R2 -309.935
- `arx_ridge`: OOD MAE 0.194, RMSE 0.210, R2 -305.763

### 7.4 Interpretation of these results

The most important conclusion is not that one tabular model clearly wins. It is that immediate next-event degradation is intrinsically difficult to predict with high explanatory power because:

- the delta is small,
- measurement and process noise are large relative to the signal,
- and the holdout data is limited.

This explains why baseline MAE can be competitive and why many R2 values are negative.

The project handles this correctly by not overselling the one-step forecast benchmark.

### 7.5 Sequence model limitation

The GRU sequence model currently reports `status = "no_sequences"`, meaning the configured lookback and contiguous sequence constraints left insufficient usable training sequences. That is a real limitation and should be stated honestly in the report.

### 7.6 Multi-horizon forecasting results

The multi-horizon outputs are stronger as a practical story.

From `best_models_by_horizon.csv` for plane 166 validation:

- 1-flight horizon: random forest with latent features, level MAE 0.0465, level R2 0.9976
- 5-flight horizon: physics hybrid with latent features, level MAE 0.1605, level R2 0.9801
- 10-flight horizon: physics hybrid with latent features, level MAE 0.2325, level R2 0.9544
- 15-flight horizon: GRU without latent input, level MAE 0.3041, level R2 0.9353
- 20-flight horizon: elastic net with latent features, level MAE 0.2317, level R2 0.9635

These results suggest that the project becomes more useful when predicting over meaningful operating horizons instead of only immediate next-event changes.

### 7.7 Transfer-learning experiments

The repository also includes eVTOL transfer experiments. The comparison results show mixed outcomes:

- transfer and pretrained models do not consistently outperform plane-only models on test delta metrics,
- level prediction can remain strong while delta prediction stays weak,
- and transfer learning is not yet a clear operational win.

This is still valuable because it shows the team tested generalization hypotheses rather than assuming them.

---

## 8. Operational Capacity Modeling

### 8.1 Why SOH alone is not enough

Even a perfect SOH number is not directly useful to a pilot or planner unless it can be translated into something operational, such as:

- how many circuits can be flown,
- how much SOC a mission will consume,
- or whether reserve margins will be violated.

That is why the repository includes circuit-capacity and SOC-rate modeling.

### 8.2 Circuit-capacity model

The circuit-capacity model uses a POH-inspired SOC-per-circuit lookup over SOH:

- SOH grid: `[0, 20, 40, 60, 80, 100]`
- SOC per circuit: `[20, 16, 13, 12, 10, 9]`

Plane-specific calibration:

- plane 166: `k = 0.80`
- plane 192: `k = 0.74`
- default: `k = 1.0`

Reserve SOC is set to 30%.

This gives a simple but practical rule:

- estimate SOC consumed per circuit from health,
- subtract reserve,
- compute maximum circuits that can be flown.

### 8.3 SOC-rate model

The SOC-rate regressor provides a more data-driven operational layer.

From `soc_rate_model_metrics.json`:

- test MAE: 0.192 SOC %/min,
- test RMSE: 0.263,
- test R2: 0.555.

This is one of the stronger predictive components in the repository because the operational signal is larger and easier to model than tiny SOH deltas.

### 8.4 Role in the overall system

These models bridge the gap between battery analytics and operational planning. They make the capstone more applied and useful than a pure SOH forecasting study.

---

## 9. Scheduling and Optimization

### 9.1 Objective

The scheduling modules use predicted degradation and SOC dynamics to support lower-stress flight planning. The idea is to choose flight and charging schedules that:

- meet demand,
- maintain reserve SOC,
- obey charging and turnaround constraints,
- and reduce predicted battery wear.

### 9.2 Implemented scripts

The repository includes:

- `simulate_schedule.py`
- `optimize_schedule.py`
- `optimize_with_windows.py`

### 9.3 Core mechanics

The scheduler combines:

- a trained degradation model loaded from the forecast output directory,
- the circuit-capacity model,
- current SOH and SOC state,
- cumulative throughput and cycle counters,
- flight durations,
- charge windows,
- reserve SOC thresholds,
- and turnaround constraints.

The state update logic simulates:

- SOC before and after flights,
- SOC before and after charges,
- cumulative throughput and EFC,
- and predicted SOH change per event.

### 9.4 Optimization behavior

The `optimize_with_windows.py` implementation uses a lookahead over candidate flight windows and evaluates each candidate by:

- applying feasible charge windows up to that point,
- simulating the resulting SOC state,
- rejecting options that violate reserve SOC,
- predicting the flight’s degradation cost,
- and selecting the candidate with the smallest predicted SOH loss.

This is effectively a greedy decision-support optimizer with constraints, not a full mixed-integer global optimizer. That is a sensible capstone-level design choice because it is interpretable and deployable within the project scope.

### 9.5 Why this matters

This stage turns the project from “battery health analytics” into “battery-aware operations.” It shows the system can inform decisions, not just describe the battery.

---

## 10. Frontend and User Experience

### 10.1 Why a frontend matters

A capstone of this type benefits from a user-facing layer because the real value of battery-health modeling lies in interpretability and decision support. The repository includes a substantial Next.js frontend rather than a minimal chart-only demo.

### 10.2 Frontend stack

The frontend uses:

- Next.js 15,
- React 18,
- TypeScript,
- Tailwind CSS,
- React Query,
- Zod,
- ECharts,
- Leaflet,
- Playwright.

### 10.3 Architecture

The UI uses:

- client-side React components,
- typed API adapters,
- Zod-validated contracts,
- snapshot-backed API routes,
- and React Query for data fetching and refresh behavior.

This gives the frontend a realistic service boundary even when some data is served from local snapshots.

### 10.4 Fleet and plane exploration

The `/planes` experience includes an “Electric Plane Explorer” that:

- visualizes aircraft subsystems,
- connects battery, powertrain, aerodynamics, and avionics concepts,
- and lets users navigate into plane-specific dashboards.

This is a strong presentation device because it links technical analytics to the physical aircraft.

### 10.5 Plane dashboard

The plane dashboard includes:

- current SOH and health label,
- trend visualization,
- replacement forecast,
- recommendation calendar,
- route and airport context,
- charging-cost estimation,
- glossary explanations,
- and forecast projection points derived from trend and replacement-date estimates.

The dashboard polls health data every 45 seconds, which makes it feel operational rather than static.

### 10.6 Recommendation calendar

The recommendation calendar displays:

- day-level scores,
- confidence tiers,
- breakdowns for weather, thermal, stress, and charging,
- and suggested charge timing windows.

This is an effective example of translating model outputs into actionable planning guidance.

### 10.7 Learn simulator

The `/learn` experience is an educational simulator that lets users adjust:

- temperature,
- flight duration,
- expected power,
- weather severity,
- charge target,
- charge lead time,
- high-SOC idle duration,
- flights per week,
- thermal-management quality,
- cell imbalance severity,
- and SOC estimator uncertainty.

It then updates projected health, expected range, and RUL shift. This is a simplified causal-explanation tool for non-specialists.

### 10.8 Mission game / FlightLab

The mission-planning interface allows users to:

- build a mission profile,
- evaluate battery impact, safety confidence, and cost efficiency,
- compare multiple planes,
- save runs locally,
- and receive strategy suggestions.

While some of the mission scoring is heuristic and snapshot-backed, it is still a strong capstone artifact because it demonstrates how analytics can be packaged into a decision-support workflow.

### 10.9 API and schema discipline

The frontend uses typed contracts for:

- plane summaries,
- live health,
- SOH trends,
- forecasts,
- recommendations,
- glossary items,
- learning simulator baselines,
- charging costs,
- and mission-game inputs/outputs.

This matters because it reduces the risk of silent UI/data mismatches and makes the system easier to evolve.

### 10.10 Frontend testing

The repository includes Playwright smoke tests that verify:

- landing page rendering,
- planes page navigation,
- plane dashboard rendering,
- recommendation calendar presence,
- and learn simulator availability.

For a capstone, this is a meaningful level of frontend validation.

---

## 11. Testing and Validation Strategy

### 11.1 Validation philosophy

Because this project combines estimation, forecasting, optimization, and UI, validation has to occur at multiple levels:

- signal validation,
- model validation,
- leakage prevention,
- operational sanity checks,
- and interface testing.

### 11.2 Signal validation

The latent-SOH diagnostics validate that:

- the smoother reduces unrealistic jumps,
- charge-related spikes are being down-weighted,
- and the resulting series is behaviorally more plausible.

### 11.3 Forecasting validation

Forecasting validation uses:

- chronological train/validation/test splits,
- holdout-plane evaluation,
- MAE, RMSE, R2, bias, and Spearman metrics,
- and comparisons against naive baselines.

This is the correct evaluation structure for a time-aware degradation problem.

### 11.4 Leakage prevention

A major validation contribution is explicit separation between:

- smoothed retrospective latent SOH for analysis,
- causal filter-only latent SOH for predictive modeling.

This protects the benchmark from future-information leakage.

### 11.5 Operational validation

The scheduling code validates:

- SOC reserve compliance,
- turnaround logic,
- charge-window feasibility,
- and degradation-aware ranking of candidate schedules.

### 11.6 Frontend validation

Frontend validation includes:

- Zod schema parsing on API boundaries,
- snapshot-backed deterministic data loading,
- and Playwright smoke tests across key user flows.

### 11.7 What the results say overall

The strongest validated conclusion is not that immediate SOH forecasting is solved. The strongest conclusion is that the system can:

- construct a trustworthy internal health reference,
- expose meaningful operational indicators,
- and support better-informed planning decisions.

That is a strong capstone outcome.

---

## 12. Key Results and Contributions

### 12.1 Technical results

The main technical results are:

- successful identification of raw SOH instability as a core data-quality problem,
- strong reduction in unrealistic SOH variation through condition-aware latent-state estimation,
- leakage-aware forecasting pipeline using causal latent targets,
- operational circuit and SOC models with useful predictive performance,
- and a scheduling framework that uses predicted degradation as an optimization signal.

### 12.2 Product/system results

The main system-level results are:

- a working frontend with dashboards, recommendations, education, and mission comparison,
- typed API contracts and snapshot-backed service endpoints,
- smoke-tested user flows,
- and a coherent bridge from telemetry analytics to user decision support.

### 12.3 What is novel about the project

The novelty is not a single new algorithm alone. It is the integration of:

- telemetry-aware latent health estimation,
- degradation forecasting,
- health-to-capacity translation,
- schedule-aware optimization,
- and user-facing operational interfaces

into one capstone system.

---

## 13. Limitations

The report should state the project limitations clearly.

### 13.1 Small and imbalanced dataset

Most training signal comes from plane 166, while plane 192 has only 98 rows. This limits generalization claims.

### 13.2 Difficult target

Immediate next-event SOH delta is extremely small, so strong predictive performance is inherently difficult.

### 13.3 Sequence model constraints

The current GRU benchmark did not have enough usable contiguous sequences under the selected configuration.

### 13.4 Transfer learning is inconclusive

The eVTOL transfer experiments do not yet show a consistent improvement over plane-only training.

### 13.5 Some frontend scores are heuristic

Parts of the recommendation and mission-game layers are designed for interpretability and UX, and not every displayed score is a direct output of the deepest forecasting models.

### 13.6 Scheduling approach is not globally optimal

The optimizer is a constrained greedy lookahead approach rather than a full optimal-control or mixed-integer solver.

These are not fatal weaknesses. They are honest scope boundaries for the current capstone stage.

---

## 14. Future Work

Logical next steps include:

- collecting more aircraft and battery histories,
- improving cross-plane generalization,
- building stronger causal sequence models,
- incorporating uncertainty-aware forecasting,
- extending transfer learning with better domain alignment,
- validating schedule recommendations against real operational outcomes,
- and replacing more heuristic frontend scoring logic with directly learned or calibrated models.

Other high-value extensions would include:

- maintenance threshold optimization,
- battery replacement economics,
- fleet-level allocation,
- and online updating as new telemetry arrives.

---

## 15. Final Conclusion

This capstone demonstrates that the main obstacle in electric-aircraft battery intelligence is not simply “predict SOH.” The harder and more important problem is to convert noisy operational telemetry into a trustworthy internal health representation and then make that representation useful for planning.

The repository accomplishes that in a credible way.

It shows that:

- raw BMS SOH is unreliable as direct truth,
- latent-state estimation provides a much better health reference,
- degradation forecasting is feasible but difficult at very short horizons,
- multi-horizon and operational-capacity views are more decision-relevant,
- and a user-facing decision-support system can integrate these outputs into interpretable dashboards and planning tools.

The capstone therefore delivers both technical insight and a working applied system. It is best presented not as “we built one model,” but as “we built a battery-health intelligence workflow for electric aircraft.”

---

## 16. How to Turn This Into a Presentation

### Suggested slide structure

1. Title slide
   Battery Health Intelligence for Electric Aircraft

2. Motivation
   Why battery health matters for safety, endurance, cost, and dispatch planning

3. Problem statement
   Raw BMS SOH is noisy and operationally unstable

4. Data and system overview
   Aircraft, telemetry tables, event-based framing, overall pipeline diagram

5. EDA findings
   Show raw SOH spikes and charge-event concentration

6. Latent SOH model
   Explain hidden-state idea and condition-aware measurement noise

7. Latent SOH results
   Raw vs smoothed trajectories, total variation reduction, max jump reduction

8. Forecasting pipeline
   Features, train/validation/test split, leakage prevention, model families

9. Forecasting results
   Immediate delta results plus multi-horizon results

10. Operational modeling
    Circuit capacity, SOC-rate model, reserve constraints

11. Scheduling layer
    How degradation-aware planning works

12. Frontend/demo
    Fleet explorer, plane dashboard, recommendation calendar, learn simulator, FlightLab

13. Limitations
    Small holdout set, hard target, transfer-learning uncertainty

14. Future work
    More aircraft, stronger sequence models, uncertainty, real deployment

15. Conclusion
    Full battery-health workflow for electric aircraft decision support

### Best figures to include

- Raw observed SOH vs latent smoothed SOH for plane 166.
- Example top spike events around charge and near-full SOC.
- A pipeline diagram from telemetry to dashboard.
- A bar chart comparing model MAE values.
- A multi-horizon performance chart.
- Circuit-capacity curve vs SOH.
- A screenshot of the plane dashboard and recommendation calendar.

### Oral presentation emphasis

During the presentation, emphasize:

- the problem of trusting raw telemetry,
- the choice to model latent health instead,
- how you prevented leakage,
- and how the final product supports operational decisions rather than only offline analysis.

---

## 17. How to Turn This Into a Poster

### Recommended poster layout

Use a three-column structure:

Column 1:

- Motivation
- Problem statement
- Dataset
- EDA findings

Column 2:

- Methodology
- Latent SOH model
- Forecasting pipeline
- Operational models

Column 3:

- Results
- Frontend/system demonstration
- Limitations
- Future work
- QR code / repository / contact

### Poster headline

Battery Health Intelligence for Electric Aircraft:
From Noisy Telemetry to Forecasting, Capacity Estimation, and Flight Planning Support

### Poster takeaway sentence

A condition-aware latent-SOH workflow can convert unstable battery telemetry into practical health estimates and decision-support tools for electric aircraft operations.

### Poster visual priorities

The poster should favor visuals over text:

- one pipeline figure,
- one raw-vs-smoothed figure,
- one forecasting-results figure,
- one operational-capacity figure,
- and one screenshot of the frontend.

The text should focus on:

- what problem you solved,
- how you solved it,
- what improved,
- and why it matters operationally.

---

## 18. Short Abstract Version

This capstone presents a battery-health intelligence workflow for electric aircraft using Velis telemetry. Exploratory analysis showed that raw BMS-reported SOH contains large charge-related spikes and reset-like artifacts, making it unreliable as direct ground truth. To address this, we developed a condition-aware latent SOH model using Kalman filtering and smoothing, where measurement noise adapts to telemetry instability, SOC-edge behavior, and estimator disagreement. The resulting latent SOH series is more physically plausible and is used to support event-based degradation forecasting, operational circuit-capacity estimation, and schedule-aware decision support. The project also includes a Next.js frontend with fleet dashboards, recommendation calendars, an educational simulator, and a mission-planning interface. Overall, the work demonstrates that battery telemetry can be transformed into a practical decision-support system for electric-aircraft operations when the estimation problem is treated as latent-state inference rather than direct regression on noisy observed SOH.
