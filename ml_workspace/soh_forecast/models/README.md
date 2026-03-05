# SOH Forecast Models

This directory contains the forecasting models used by the `ml_workspace/soh_forecast` pipeline.

The forecasting setup in this repo is event-based. Each row represents one battery event for one aircraft battery, and every model predicts the **next SOH level** for that event sequence. In most of the tabular models, the model is trained on the **delta**

`target_delta = next_soh - current_soh`

and then converted back to a level prediction with

`predicted_next_soh = current_soh + predicted_delta`

This keeps the learning problem focused on incremental degradation instead of absolute SOH.

The forecast pipeline now also supports **multi-horizon targets**, not just the immediate next event. In the notebook runner, the active benchmark compares observed-SOH flight-count horizons such as the next flight, next 5 flights, and next 10 flights using the target-spec builder in [`feature_pipeline.py`](/Users/benfogerty/Desktop/EPlaneCapstone/CapstoneEPlane/ml_workspace/soh_forecast/feature_pipeline.py).

## Shared Concepts

### Inputs

All models consume features built upstream in the SOH forecast pipeline. These include:

- raw event summaries such as current, temperature, SOC, duration, and measurement noise
- latent SOH features from the smoother
- engineered operating-condition features
- stress proxies such as thermal, throughput, storage, and resistance indicators
- historical features such as lags, rolling means, and rolling stress summaries

Tabular models rely on `make_feature_frame(...)` from [`common.py`](/Users/benfogerty/Desktop/EPlaneCapstone/CapstoneEPlane/ml_workspace/soh_forecast/common.py). That helper:

- keeps the requested numeric feature columns
- coerces them to numeric and median-imputes missing values
- one-hot encodes `event_type`, `battery_id_str`, and `plane_id`

### Outputs

Every training function returns a `ModelArtifacts` object with:

- `predictions`: event-level predictions by split
- `metrics`: level and delta metrics by split
- `model`: the fitted estimator or neural network
- `feature_names`: final training feature names
- `diagnostics`: model-specific extras such as scalers, histories, or sequence normalization stats

### Splits

Models are trained on preassigned `train`, `valid`, `test`, and optional `holdout` frames. The split logic lives outside this folder in the feature pipeline and notebooks.

## Model Inventory

### `naive_zero_delta.py`

Purpose: a baseline that assumes no SOH change between the current event and the next event.

How it works:

- prediction is simply `current_soh`
- no fitting step exists
- this is the minimum bar that any learned model should beat

What it is useful for:

- sanity checking whether the target is too noisy
- understanding whether a model is just learning to stay near the previous value

### `ridge_delta.py`

Purpose: a linear baseline with L2 regularization.

How it works:

- builds the tabular feature frame
- standardizes features with `StandardScaler`
- trains on delta SOH using ridge regression
- selects `alpha` from a small validation grid
- adds the predicted delta back to the current SOH

What it captures:

- additive linear relationships between predictors and degradation
- stable behavior when many correlated features are present

Main limitation:

- it cannot express nonlinear thresholds or interactions unless those are engineered upstream

### `elastic_net_delta.py`

Purpose: a sparse linear baseline with both L1 and L2 regularization.

How it works:

- same data path as ridge
- standardizes features
- trains on delta SOH with `ElasticNet`
- validates over `alpha` and `l1_ratio`

What it captures:

- linear effects, with some automatic feature shrinkage or zeroing

Why keep it:

- it is often a good diagnostic model for identifying whether only a small subset of features carries signal

### `gam_spline_delta.py`

Purpose: a semi-parametric tabular model that is more flexible than linear regression but still structured.

How it works:

- splits features into binary and continuous columns
- applies cubic spline bases to continuous features
- passes binary features through unchanged
- fits a ridge model on the expanded spline representation
- chooses regularization strength on the validation split

What it captures:

- smooth nonlinear univariate effects
- more interpretable shape changes than tree ensembles or neural nets

Main limitation:

- interactions are still limited unless present in the raw features or spline-expanded representation indirectly

### `hist_gbdt_delta.py`

Purpose: a gradient-boosted tree model for nonlinear tabular forecasting.

How it works:

- uses the tabular feature frame directly
- trains a `HistGradientBoostingRegressor` on delta SOH
- selects among a few depth and learning-rate settings using validation MAE

What it captures:

- nonlinear effects
- feature thresholds
- moderate interactions between engineered predictors

Why it is useful:

- usually one of the stronger tabular baselines when the feature engineering is already good

Main limitation:

- predictions are harder to interpret physically than ridge or the PINN

### `random_forest_delta.py`

Purpose: a bagged tree baseline for nonlinear tabular forecasting.

How it works:

- uses a random forest regressor on delta SOH
- validates a few settings for tree depth, leaf size, and feature subsampling

What it captures:

- nonlinearities and interactions
- robust behavior without much tuning

Main limitation:

- tends to be less sample-efficient than boosting on structured tabular problems

### `sequence_common.py`

Purpose: shared infrastructure for sequential neural models.

What it does:

- normalizes sequence features using train-split statistics
- groups rows by `(plane_id, battery_id)`
- builds fixed-length lookback windows ordered by `event_datetime` and `flight_id`
- creates PyTorch loaders for train, validation, test, and holdout rows
- trains a sequence model with MSE loss on next SOH level
- tracks validation MAE and early stopping

Important detail:

- unlike the linear/tree models, the sequence models predict the **next SOH level directly**, not delta SOH explicitly
- temporal structure is carried by the sequence window itself

### `lstm_sequence.py`

Purpose: recurrent sequence model using an LSTM encoder.

How it works:

- uses the shared window-building pipeline from `sequence_common.py`
- passes the lookback window through an LSTM
- takes the final hidden state
- maps it through a small MLP head to predict next SOH

What it captures:

- order-dependent event history
- temporal accumulation patterns that are not easy to express in a single tabular row

### `gru_sequence.py`

Purpose: recurrent sequence model using a GRU encoder.

How it works:

- same training pipeline as the LSTM model
- replaces the LSTM cell with a GRU cell

Why keep both:

- GRUs can be simpler and sometimes easier to train on small datasets
- LSTMs can sometimes retain longer dependencies more stably

## Physics Hybrid Model

### File

[`physics_hybrid_nn.py`](/Users/benfogerty/Desktop/EPlaneCapstone/CapstoneEPlane/ml_workspace/soh_forecast/models/physics_hybrid_nn.py)

### Goal

This model is intended to sit between a pure black-box neural network and a full electrochemical PINN.

It is **not** a PDE solver like the parameterized SPM PINN in the reference paper. This repo’s data is event-level aircraft battery telemetry, not dense charge-curve trajectories with spatial coordinates. Because of that, the model borrows the paper’s most transferable ideas:

- represent latent degradation parameters explicitly
- use separate encoders for general observations and physics-related state
- factor degradation into interpretable channels
- encourage those latent parameters to evolve smoothly over the life of a battery
- handle different operating conditions through condition-aware parameter gating

So the model is better described as a **condition-aware damage-accumulation hybrid forecaster**.

### High-Level Structure

The network has three main parts:

1. A general feature encoder.
   It ingests the standard tabular feature frame used by the other models.

2. A physics-context encoder.
   It ingests a smaller, curated set of SOH state and operating-condition features, such as latent SOH, temperature, SOC, duration, rolling condition summaries, and cumulative usage.

3. A physics-informed degradation head.
   It converts the encoded context into nonnegative latent sensitivities and combines them with explicit degradation-drive channels.

### Explicit Degradation Channels

The model builds five nonnegative drive channels before training:

- `calendar_drive`
  Based mainly on `delta_days`, condition multiplier, and storage stress.

- `cycle_drive`
  Based mainly on throughput stress and a fallback cycle proxy from current, duration, and SOC span.

- `thermal_drive`
  Based mainly on Arrhenius temperature proxy, thermal severity, time-above-40C proxy, and current-temperature stress.

- `resistance_drive`
  Based mainly on internal resistance proxy, voltage sag, coulomb-gap magnitude, and reset risk.

- `history_drive`
  Based mainly on total degradation stress, rolling stress, cumulative EFC, and cumulative amp-hour throughput.

These channels are hand-structured so the network does not have to rediscover the broad battery-aging decomposition from scratch.

### Latent Physical Parameters

The physics encoder produces latent parameters through `parameter_head`. These are constrained with `softplus`, so they remain nonnegative.

Those latent parameters include:

- one sensitivity per degradation channel
- one interaction gain for cross-channel degradation terms
- one aging gain that increases sensitivity as the battery moves further away from fresh condition

This is the closest part of the model to the paper’s “parameterized” idea. Instead of identifying electrochemical parameters such as active-material fractions from a single-particle model, this repo learns event-level latent degradation sensitivities from observed usage and SOH history.

### Condition-Aware Gating

The model also learns a gate for each degradation channel.

The gate depends on both:

- the general feature embedding
- the physics-context embedding

This means the same raw stress magnitude can have a different effect depending on the operating regime and the battery’s current health state. That is important in this project because the user requirement is explicitly that the battery has seen different conditions over its life.

### Degradation Equation

At inference time, the model computes:

- base degradation from the weighted sum of the five channels
- interaction degradation from multiplicative channel pairs
- a small residual degradation term from a separate residual head

The next SOH is then:

`next_soh = clamp(current_soh - total_degradation, 0, 100)`

This hard-codes the directional prior that degradation should reduce available health rather than arbitrarily increase or decrease it on every event.

### Why This Is Hybrid Rather Than A Standard PINN

The physics-informed part comes from structure and constraints rather than from PDE residuals:

- degradation channels correspond to known aging mechanisms
- channel sensitivities are constrained nonnegative
- total degradation is subtractive from current SOH
- the model separates mechanism-like drives from residual correction
- the learned sensitivities are regularized to vary smoothly along the timeline of each battery

This makes the model more physically disciplined than a standard MLP, but it is still not a classical PINN because it does not enforce governing differential-equation residuals through automatic differentiation over physical coordinates.

### Loss Function

The training loss has three pieces:

1. Data loss.
   MSE between predicted next SOH and observed next SOH.

2. Degradation consistency loss.
   MSE between predicted total degradation and empirical degradation
   `relu(current_soh - target_soh)`.
   This pushes the internal damage estimate to match the observed SOH drop.

3. Residual penalty.
   Penalizes the magnitude of the residual degradation branch so the model prefers to explain change through the explicit degradation channels.

There is also a separate smoothness penalty:

- consecutive rows from the same battery are compared
- latent channel sensitivities are encouraged to change smoothly
- the penalty decays with larger time gaps between events

That smoothness term is important because latent physical parameters should not jump violently from one nearby event to the next unless the data strongly demands it.

### Data Preparation Path

The PINN uses two parallel input representations:

- `features`
  The full feature frame from `make_feature_frame(...)`, standardized with a feature scaler.

- `physics_context`
  A curated subset of physically meaningful state and condition features, separately median-filled and standardized.

These are bundled with:

- explicit degradation drives
- current SOH
- target next SOH
- `delta_days`
- battery identity codes for smoothness regularization

### Training Loop

Training proceeds as follows:

1. Sort each split chronologically by battery.
2. Build tabular features and physics-context features.
3. Standardize each representation separately.
4. Build explicit degradation-drive channels.
5. Train with Adam.
6. Monitor validation MAE.
7. Keep the best checkpoint by validation MAE.
8. Store learning history and scalers in diagnostics.

### Diagnostics Returned

The diagnostics for this model include:

- training history by epoch
- feature scaler and context scaler
- tabular feature medians and dummy columns
- context medians and context feature names
- names of the five degradation-drive channels

The history table also tracks the mean learned sensitivity for each degradation channel. That is useful when checking whether the model is putting most of its weight on calendar aging, cycling stress, thermal stress, or history effects.

### Interpretation Guidance

When reading this model, think of it as:

- a learned degradation law over engineered stress channels
- with latent parameters that drift over battery life
- under condition-aware modulation
- plus a small residual correction

That framing is much closer to the battery-aging intuition in the paper than a plain recurrent or tabular network, while still fitting this repo’s event-level dataset.

### Main Limitations

- It does not solve the SPM or DFN equations.
- It does not use raw voltage tail segments directly.
- It depends heavily on the quality of upstream engineered stress proxies.
- If the latent SOH labels are noisy, the learned channel sensitivities can still be biased.

So this model should be treated as a structured hybrid forecaster, not as a full electrochemical digital twin.

## Standard PINN

### File

[`physics_informed_nn.py`](/Users/benfogerty/Desktop/EPlaneCapstone/CapstoneEPlane/ml_workspace/soh_forecast/models/physics_informed_nn.py)

### Goal

This is the repo's more traditional physics-informed neural network.

It is still tailored to this dataset, so it is an **ODE-style PINN over continuous battery age**, not a full PDE battery-model PINN with spatial coordinates. That is the most standard PINN formulation the current event-level telemetry can support.

### Core Idea

The model learns a continuous SOH field

`SOH = u_theta(t_age, context)`

where:

- `t_age` is continuous event age in days for each battery
- `context` is a standardized set of operating-condition and battery-state features

It then uses automatic differentiation to compute

`du_theta / dt_age`

and enforces an explicit degradation ODE residual.

### Physics Residual

The network builds the same five degradation drives used by the hybrid model:

- calendar
- cycle
- thermal
- resistance
- history

But instead of directly summing them to produce the next SOH prediction, the standard PINN treats them as the right-hand side of a degradation law:

`dSOH/dt + g(drives, SOH) = 0`

where `g(...)` is constrained to be nonnegative with learned positive weights.

That makes the model PINN-like in the standard sense:

- the network predicts a state field
- the derivative of that state with respect to a continuous coordinate is computed with autograd
- the derivative is forced to satisfy a physics residual

### Architecture

The standard PINN has two pieces:

1. A state network.
   It maps `(t_age, context)` to the current SOH state.

2. A physics-rate module.
   It maps degradation drives and current SOH to a nonnegative degradation rate.

The predicted next SOH is then produced with a one-step Euler update:

`SOH_next = SOH_current_pred + delta_t * dSOH/dt`

Since the derivative is usually negative, this moves SOH downward over time.

### Training Loss

The standard PINN optimizes several terms:

1. State data loss.
   Fits the network's state prediction to the observed current SOH at each event.

2. Step forecast loss.
   Fits the one-step forecast to the observed next SOH.

3. Physics residual loss.
   Penalizes violations of
   `dSOH/dt + g(drives, SOH) = 0`.

4. Monotonic penalty.
   Penalizes positive `dSOH/dt`, since SOH should not systematically increase over life.

5. Initial-condition penalty.
   Gives extra weight to the first event of each battery trajectory.

This is much closer to a standard PINN training recipe than the hybrid model because the derivative constraint is part of the objective directly.

### Why It Is More “Standard”

Compared with the hybrid model, this file does the thing classical PINNs are known for:

- it defines a continuous state approximation
- it differentiates that approximation with respect to a physical coordinate
- it minimizes a physics residual based on a governing differential relation

What it does not do:

- solve a spatial battery PDE
- enforce SPM or DFN boundary conditions

So it is a **standard PINN in ODE form**, not a full electrochemical PDE PINN.

### Practical Interpretation

Use the standard PINN when you want:

- a benchmark that is genuinely PINN-style
- explicit derivative-based physics regularization
- a model that treats SOH as a continuous-time state rather than just a one-step regression target

Use the hybrid model when you want:

- stronger hand-structured battery-aging inductive bias
- easier integration of engineered degradation channels
- usually simpler and more stable training on this tabular event dataset

## Which Model To Use

As a practical default:

- use `naive_zero_delta` as a floor
- use `ridge_delta` or `elastic_net_delta` as interpretable linear baselines
- use `hist_gbdt_delta` or `random_forest_delta` for strong nonlinear tabular baselines
- use `lstm_sequence` or `gru_sequence` when event order is expected to matter materially
- use `physics_hybrid_nn` when you want the strongest structured battery-aging inductive bias and want the model to account for changing operating conditions across the battery life
- use `physics_informed_pinn` when you specifically want a more standard autograd-based PINN benchmark in the comparison

## Exported Training Functions

The exported entrypoints from this folder are listed in [`__init__.py`](/Users/benfogerty/Desktop/EPlaneCapstone/CapstoneEPlane/ml_workspace/soh_forecast/models/__init__.py):

- `train_naive_zero_delta`
- `train_ridge_delta`
- `train_elastic_net_delta`
- `train_gam_spline_delta`
- `train_hist_gbdt_delta`
- `train_random_forest_delta`
- `train_lstm_sequence`
- `train_gru_sequence`
- `train_physics_hybrid_nn`
- `train_physics_informed_nn`
