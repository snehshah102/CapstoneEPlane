# Capstone (Plane)

## Goal
Create a reliable training label for battery SOH when the raw `bat 1 soh` / `bat 2 soh` fields are noisy or inconsistent.  
This repo uses two complementary label-generation approaches and then layers them for confidence.

## Source Reference for POH-Based Labeling
The flight-phase SOC-consumption table used for proxy labeling comes from:

- `documentation/POH-Velis-Pilot-operating-handbook.pdf`
- Handbook page: `10-5a-22` (Training sortie table with `%SOC` per flight phase vs `%SOH`)

Use this table as an operational reference model (proxy), not lab-certified electrochemical truth.

## Battery Type Inference
Battery type was inferred from charging-event telemetry using a plane-level capacity proxy with top-of-charge voltage as a cross-check.

- Plane `166`: inferred `PB345V119E-L`
  - Effective-capacity median: `26.13 Ah`
  - Confidence: `0.80`
- Plane `192`: inferred `PB345V119E-L`
  - Effective-capacity median: `28.74 Ah`
  - Confidence: `0.845`

Shared ML battery specs now live in:

- `ml_workspace/battery_specs.yaml`

## Data Files and Column Scope
Key raw files per flight:

- `csv-<id>.csv`: merged flight and powertrain stream
- `csv-<id>_1.csv`: battery 1 model-rich stream
- `csv-<id>_2.csv`: battery 2 model-rich stream
- `csv-<id>_warns.csv`: warnings/events

Primary columns from `csv-<id>.csv` (for segmentation + context):

- Time: `time(ms)`, `time(min)`, `TIMESTAMP`
- Battery usage: `bat 1 soc`, `bat 2 soc`, `bat 1 current`, `bat 2 current`, `bat 1 voltage`, `bat 2 voltage`
- Power/flight phase: `motor power`, `motor rpm`, `requested torque`, `IAS`, `PRESSURE_ALT`, `GROUND_SPEED`
- Conditions: `OAT`, `inverter temp`, `motor temp`, `bat 1 avg cell temp`, `bat 2 avg cell temp`

Primary columns from `csv-<id>_1.csv` and `_2.csv` (for normalization and diagnostics):

- Observed SOH: `bat 1 soh`, `bat 2 soh`
- SOC estimators: `bat 1 kalman soc`, `bat 1 coulomb soc out`, `bat 2 kalman soc`, `bat 2 coulomb soc out`
- Capacity/energy proxies: `bat 1 cap est`, `bat 2 cap est`, `bat 1 box avaliable energy`, `bat 2 box avaliable energy`
- Cell spread proxies: `bat 1 min cell volt`, `bat 1 max cell volt`, `bat 2 min cell volt`, `bat 2 max cell volt`
- Thermal spread proxies: min/max/avg cell temperatures per battery
- Optional (diagnostic only, not default training target): `B1 SOH CELL 0..95`, `B2 SOH CELL 0..95`

## Approach A: POH-Derived SOH Proxy Label (`soh_proxy_poh`)

### A1) Segment flight into POH-like phases
Map continuous telemetry to phase windows that correspond to handbook rows:

- Take off and initial climb to 300 ft AGL
- 1000 ft climb at Vy / ~48 kW
- 10 min cruise at 20 kW, 25 kW, 30 kW, 35 kW (choose closest motor-power bin)
- Touch and go + climb to 300 ft AGL
- First traffic pattern
- Generic traffic pattern
- Aborted landing + climb to 1000 ft AGL at Vy / ~64 kW

Operational segmentation signals:

- Power banding from `motor power`
- Climb/descent from derivative of `PRESSURE_ALT`
- Takeoff/landing transitions from low/high `IAS` + altitude trend
- Duration constraint for cruise rows (`~10 min`)

### A2) Compute observed phase SOC consumption
Per battery and phase:

- `delta_soc_obs = soc_start - soc_end`
- Use `bat 1 soc` and `bat 2 soc` separately
- Optional pack-average: `delta_soc_obs_pack = 0.5 * (delta_soc_obs_b1 + delta_soc_obs_b2)`

### A3) Invert POH table to infer SOH per phase
Given a phase row with POH SOC values at SOH grid `[100, 80, 60, 40, 20, 0]`:

1. Find adjacent POH points around `delta_soc_obs`
2. Linearly interpolate SOH between those two points
3. Clamp to `[0, 100]`

If outside table bounds, clamp to nearest endpoint SOH.

### A3b) POH training-sortie numeric lookup (page `10-5a-22`)
`%SOC` consumed by phase at each `%SOH`:

| Flight phase | SOH 100 | SOH 80 | SOH 60 | SOH 40 | SOH 20 | SOH 0 |
|---|---:|---:|---:|---:|---:|---:|
| Take off and initial climb to 300 ft AGL | 4 | 4 | 5 | 6 | 7 | 8 |
| 1000 ft climb at Vy - 48 kW | 7 | 7 | 8 | 10 | 12 | 14 |
| 10 min cruise - 20 kW (69 KCAS) | 15 | 17 | 19 | 22 | 26 | 32 |
| 10 min cruise - 25 kW (78 KCAS) | 19 | 22 | 25 | 28 | 34 | 41 |
| 10 min cruise - 30 kW (86 KCAS) | 24 | 26 | 30 | 35 | 41 | 50 |
| 10 min cruise - 35 kW (92 KCAS) | 28 | 31 | 36 | 41 | 49 | 59 |
| Touch and go and climb to 300 ft AGL | 3 | 3 | 4 | 4 | 5 | 6 |
| Energy for the first traffic pattern | 10 | 11 | 13 | 15 | 18 | 22 |
| Energy for a generic traffic pattern | 9 | 10 | 12 | 13 | 16 | 20 |
| Aborted landing and climb to 1000 ft AGL at Vy - 64 kW | 7 | 8 | 9 | 10 | 12 | 15 |

### A4) Aggregate to flight-level label
Weighted aggregation recommended:

- `soh_proxy_poh_flight = sum(w_i * soh_proxy_poh_phase_i) / sum(w_i)`
- Default weight: `w_i = delta_soc_obs_phase_i` (energy-weighted)
- Alternative weight: segment duration if energy is noisy

### A5) Output fields
Write at minimum:

- `flight_id`
- `battery_id` (`1`, `2`, `pack_avg`)
- `soh_proxy_poh_flight`
- `soh_proxy_poh_phase_*`
- `phase_count_used`
- `poh_fit_mae` (mean absolute error between observed phase SOC and POH SOC at inferred SOH)

## Approach B: Normalized Observed SOH Label (`soh_observed_norm`)

Purpose: de-noise the sporadic `bat X soh` stream by removing operating-condition effects and transient artifacts.

### B1) Build cleaning mask
Drop or down-weight rows where:

- Major battery fields are all zero (startup/inactive block)
- SOC out of range (`<0` or `>100`)
- Impossible jumps in `bat X soh` over short intervals
- Reset flags suggest estimator reset: `bat X cell flg rst coulomb`, `bat X cell flg new est batt cap`

### B2) Compute confounder features
Per sample or window:

- Temperature state: `bat X avg cell temp`, `(max-min) cell temp`, `OAT`
- Load state: `motor power`, `bat X current`, C-rate proxy `abs(current) / cap_est`
- Voltage stress: `(max cell volt - min cell volt)`
- Estimator mismatch: `kalman_soc - coulomb_soc_out`
- Dynamic regime: climb/cruise/pattern class from Approach A segmentation

### B3) Normalize observed SOH
Fit a correction model on within-flight or cross-flight data:

- Example linear mixed model:
  - `batX_soh ~ beta0 + beta1*temp + beta2*power + beta3*c_rate + beta4*soc_window + beta5*kalman_coulomb_gap + flight_random_effect`
- Define:
  - `soh_observed_norm = batX_soh - estimated_confounder_component`

Practical alternative: robust regression (Huber) or GAM if nonlinearity is strong.

### B4) Smooth to stable label
Convert corrected stream to one label per flight:

- Median over valid cruise/pattern windows, or
- Tukey-trimmed mean (for outlier resistance)

Write:

- `soh_observed_norm_flight`
- `soh_observed_norm_iqr`
- `valid_samples_ratio`

## Layered Confidence Strategy (Recommended)
Use both labels together to increase trust and detect bias.

### C1) Agreement metrics
Per flight:

- `delta_labels = abs(soh_proxy_poh_flight - soh_observed_norm_flight)`
- Correlation over recent flights by tail/pack
- Drift consistency over time (monotonic decline expectation)

### C2) Confidence score
Example score in `[0,1]`:

- `c1`: POH fit quality from `poh_fit_mae`
- `c2`: normalization stability from `soh_observed_norm_iqr`
- `c3`: label agreement from `delta_labels`
- `confidence = 0.4*c1 + 0.3*c2 + 0.3*c3`

Store both labels and confidence, do not collapse to one scalar too early.

### C3) Label policy

- High confidence: train on blend target  
  - `soh_target = alpha*soh_proxy_poh + (1-alpha)*soh_observed_norm`
  - with `alpha` based on POH fit quality
- Medium confidence: train with sample weights from `confidence`
- Low confidence: keep for inference-only monitoring, exclude from core training

## Leakage Controls for ML
If target is derived from SOC drop and phase power profile, avoid giving the model the exact same information at the same horizon.

Recommended:

- Define prediction time `t0` (e.g., pre-flight or early climb)
- Use only features available at `t0` (or in a fixed short window before `t0`)
- Predict future flight-level label, not same-window reconstructed label

Avoid trivial leakage features for the same target window:

- Direct full-flight `delta_soc`
- Direct phase-integrated power over the same period used to construct label

## Suggested Dataset Schema for Training
One row per `(flight_id, battery_id)`:

- IDs: `flight_id`, `battery_id`, `aircraft_id`, `date_utc`
- Targets:
  - `soh_proxy_poh_flight`
  - `soh_observed_norm_flight`
  - `soh_target_blend`
  - `confidence`
- Feature groups:
  - Thermal: avg/min/max/spread
  - Electrical: current/voltage summaries
  - Dynamics: power/rpm/torque summaries
  - Estimator diagnostics: kalman-coulomb gap stats
  - Optional cell-statistics summaries from per-cell arrays (mean/std/min/max), not raw 96-cell columns unless needed

## QA Checks Before Training

- Time monotonicity per file (`time(ms)`)
- SOC boundedness and discontinuity checks
- Reasonable phase coverage count per flight
- Missing-data rate by critical column
- Distribution shift checks by aircraft and date

## Existing Project Areas
- `data/`: raw and intermediate flight data
- `ml_workspace/EDA/`: exploratory SOH/SOC notebooks and rollups
- `ml_workspace/data_driven/`: current data-driven SOH labeling and segmentation code
- `ml_workspace/SOH_normalized/`: Approach B normalized-observed-SOH implementation with separate outputs
- `ml_workspace/physics_soh`: simplified notebook-based SOH baseline
- `scraping_pipeline/`: web/data ingestion scripts

## Scraping Pipeline
The scraper is now CSV-first. It does not use SQLite.

Primary script:
- `scraping_pipeline/pipistrel_scraper.py`

Outputs:
- `data/raw_zips/by_plane/<plane_id>/Event_YYYY-MM-DD_HHMM_<flight_id>/<bundle>.zip`
- `data/raw_csv/by_plane/<plane_id>/Event_YYYY-MM-DD_HHMM_<flight_id>/*.csv`
- `data/raw_csv/by_plane/<plane_id>/Event_YYYY-MM-DD_HHMM_<flight_id>/event_metadata.json`
- `data/raw_csv/by_plane/<plane_id>/Event_YYYY-MM-DD_HHMM_<flight_id>/note.txt` when a detail-page note exists
- `data/processed/scrape_manifest.csv`

Important behavior:
- Flight detail page `Date` is stored for every event.
- Charging events are preserved even when no CSV exists.
- Charging/no-CSV notes are stored in `event_metadata.json` and `note.txt`.
- ZIP extraction keeps only CSV files; `TRC` files are ignored.

Example scrape commands:

1. Smoke test one event:
   - `python scraping_pipeline/pipistrel_scraper.py --max-pages 1 --max-flights 1 --no-skip-existing`
2. Normal scrape using `.env` credentials:
   - `python scraping_pipeline/pipistrel_scraper.py`
3. Re-download and overwrite extracted CSVs:
   - `python scraping_pipeline/pipistrel_scraper.py --force-redownload --overwrite-extracted`

## Extract ZIPs to `raw_csv`
Use this script when you already have ZIP bundles and want to extract them again:

- Script: `scraping_pipeline/extract_zips_to_raw_csv.py`
- Supported layouts:
  - `data/raw_zips/by_plane/<plane_id>/<event_dir>/<bundle>.zip`
  - `data/raw_zips/by_plane/<plane_id>/<legacy_bundle>.zip`

Examples:

1. Dry-run (preview only):
   - `python scraping_pipeline/extract_zips_to_raw_csv.py --dry-run`
2. Extract all planes under `data/raw_zips/by_plane`:
   - `python scraping_pipeline/extract_zips_to_raw_csv.py`
3. Plane `166` only:
   - `python scraping_pipeline/extract_zips_to_raw_csv.py --zip-root data/raw_zips/by_plane/166 --out-root data/raw_csv/by_plane/166`
4. Re-extract and overwrite existing CSVs:
   - `python scraping_pipeline/extract_zips_to_raw_csv.py --overwrite`

Notes:
- New scrapes already extract CSVs automatically.
- Existing CSV files are skipped unless `--overwrite` is provided.
- Metadata sidecars (`event_metadata.json`, `note.txt`) are copied when available.

## Parquet Datasets for Analysis
The main analysis layer for the rest of the project is the parquet export built from the raw event folders.

Primary parquet files:

- `data/processed/event_manifest.parquet`: one row per event
- `data/processed/event_timeseries.parquet`: one row per telemetry sample

These are the preferred files to load for plotting, time-series analysis, feature engineering, and later model development.

### Why use these parquet files
They are easier to work with than the raw event folders because they:

- combine all events into one analysis-ready table
- preserve the original raw telemetry columns
- keep numeric telemetry numeric instead of converting everything to strings
- attach event metadata to each telemetry row
- add canonical helper columns for pack-level analysis

Use `event_manifest.parquet` when you want event-level filtering or summaries.
Use `event_timeseries.parquet` when you want sample-level traces such as SOC, current, voltage, or temperature over time.

### Event Manifest Structure
`data/processed/event_manifest.parquet` contains one row per event folder.

Typical columns:

- `flight_id`
- `plane_id`
- `registration`
- `event_dir_name`
- `event_dir_path`
- `event_datetime`
- `event_date`
- `detail_date`
- `detail_flight_type`
- `detail_duration`
- `detail_note`
- `route`
- `pilot`
- `departure_airport`
- `destination_airport`
- `csv_found`
- `csv_file_count`
- `csv_files`
- `csv_zip_url`
- `csv_zip_path`
- `event_type_main`
- `is_charging_event`
- `is_flight_event`
- `is_ground_test_event`

Use this file for questions like:

- how many charging events exist per plane?
- what date range is covered?
- which events have notes but no CSV?
- which events belong to plane `166` vs `192`?

### Event Timeseries Structure
`data/processed/event_timeseries.parquet` contains one row per telemetry sample from the raw event CSV files.

It includes three types of columns.

Raw telemetry columns:

- original columns from the vendor CSVs are preserved
- examples: `time(ms)`, `bat 1 current`, `bat 1 voltage`, `bat 1 soc`, `motor power`, `OAT`
- these remain numeric when the source data is numeric

Event metadata columns:

- repeated on every row so filtering is easy
- examples: `flight_id`, `plane_id`, `registration`, `event_datetime`, `detail_flight_type`, `event_type_main`, `source_csv_name`, `source_csv_kind`

Canonical helper columns:

- added to make analysis easier across different CSV file variants
- examples:
  - `time_ms`
  - `time_min`
  - `source_pack_id`
  - `pack_current`
  - `pack_voltage`
  - `pack_soc`
  - `pack_temp_min`
  - `pack_temp_max`
  - `pack_temp_avg`
  - `pack_cell_v_min`
  - `pack_cell_v_max`
  - `bat_1_current`, `bat_2_current`
  - `bat_1_soc`, `bat_2_soc`

### Recommended Columns for Most Analysis
For most notebooks and plots, start with these columns instead of the raw vendor-specific ones:

- `plane_id`
- `registration`
- `flight_id`
- `event_datetime`
- `detail_flight_type`
- `event_type_main`
- `is_charging_event`
- `is_flight_event`
- `source_csv_name`
- `source_csv_kind`
- `source_pack_id`
- `time_ms`
- `time_min`
- `pack_soc`
- `pack_current`
- `pack_voltage`
- `pack_temp_avg`
- `pack_temp_max`
- `motor_power`
- `oat`

These are the easiest columns to use for:

- SOC over time
- charging-event temperature traces
- pack 1 vs pack 2 comparisons
- charging vs flight comparisons
- cumulative battery usage and degradation studies

### CSV File Variants and `source_csv_kind`
Each event can contain multiple CSV files.

Common patterns:

- `csv-<id>.csv`: main merged stream
- `csv-<id>_1.csv`: battery 1 model-rich stream
- `csv-<id>_2.csv`: battery 2 model-rich stream
- `csv-<id>_warns.csv`: warnings/events stream

In parquet, these are labeled with:

- `source_csv_name`: original file name
- `source_csv_kind`:
  - `raw` for the main merged stream
  - `aux` for `_1.csv` or `_2.csv`
  - `warns` for `_warns.csv`
- `source_pack_id`:
  - `1` for `_1.csv`
  - `2` for `_2.csv`
  - `0` when the file is not pack-specific

### Default Column Filtering Rules
By default, the parquet builder keeps almost all telemetry columns but removes the noisiest cell-level diagnostic columns.

Default behavior:

- keeps `bat 1 soh` and `bat 2 soh`
- drops cell-specific SOH columns such as `B1 SOH CELL *` and `B2 SOH CELL *`
- drops cell-specific `FSK` columns
- drops cell-specific `KFL` columns
- excludes `*_warns.csv` unless `--include-warns` is used

If you want warning rows included:

```powershell
python scraping_pipeline/build_event_timeseries_parquet.py --include-warns
```

If you want to keep all SOH columns, including per-cell SOH:

```powershell
python scraping_pipeline/build_event_timeseries_parquet.py --include-warns --include-soh-columns
```

### Rebuilding the Parquet Files
Standard rebuild command:

```powershell
python scraping_pipeline/build_event_timeseries_parquet.py --include-warns
```

Outputs:

- `data/processed/event_manifest.parquet`
- `data/processed/event_timeseries.parquet`

Useful options:

```powershell
python scraping_pipeline/build_event_timeseries_parquet.py --include-warns --chunk-rows 5000
```

```powershell
python scraping_pipeline/build_event_timeseries_parquet.py --include-warns --no-progress
```

```powershell
python scraping_pipeline/build_event_timeseries_parquet.py --max-events 50
```

Notes:

- the builder streams large CSVs in chunks to avoid memory failures
- the script shows a progress bar by default
- numeric telemetry columns are preserved as numeric types in parquet

### Recommended Analysis Workflow
Suggested workflow for the rest of the project:

1. Use `event_manifest.parquet` to inspect coverage and filter event subsets.
2. Use `event_timeseries.parquet` for sample-level analysis and plotting.
3. Build smaller derived tables from parquet for specific modeling tasks if needed.
4. Keep raw CSVs as the source of truth, but do most analysis from parquet.

### Example Python Usage
Load both parquet files:

```python
import pandas as pd

manifest = pd.read_parquet('data/processed/event_manifest.parquet')
timeseries = pd.read_parquet('data/processed/event_timeseries.parquet')
```

Charging events only:

```python
charging = timeseries[timeseries['is_charging_event'] == 1].copy()
charging = charging.sort_values(['plane_id', 'event_datetime', 'source_csv_name', 'time_ms'])
```

Plane `166`, pack 1 SOC traces:

```python
plane_166_pack1 = timeseries[
    (timeseries['plane_id'] == '166') &
    (timeseries['source_pack_id'] == 1)
].copy()
```

Daily or monthly event counts:

```python
counts = (
    manifest
    .groupby(['plane_id', 'event_type_main'])
    .size()
    .reset_index(name='event_count')
)
```

Plot pack SOC through a charging event:

```python
sample = timeseries[
    (timeseries['flight_id'] == 12405) &
    (timeseries['source_pack_id'] == 1)
].sort_values('time_ms')

sample.plot(x='time_min', y='pack_soc')
```

Plot average charging temperature over time:

```python
charging_temp = timeseries[
    (timeseries['is_charging_event'] == 1) &
    (timeseries['pack_temp_avg'].notna())
].copy()

charging_temp = charging_temp.sort_values(['event_datetime', 'time_ms'])
```

### Best Practices
Use parquet as the default working layer for analysis.

Recommended:

- filter by `plane_id` early when working on one aircraft
- use `event_datetime` plus `time_ms` to sort traces
- prefer `pack_*` columns for pack-specific work
- fall back to raw vendor columns only when you need a field not already canonicalized
- use `event_manifest.parquet` for event-level filtering before loading large subsets from `event_timeseries.parquet`

### What not to use as the main analysis layer
Do not use these as your primary analysis tables:

- the raw `Event_*` folders directly for large-scale analysis
- individual CSV files one at a time unless debugging a specific event
- generated CSV exports from downstream notebooks as a system-of-record

The parquet files are the intended common analysis layer for the rest of the project.

## Physics SOH Baseline Notebook
Start here for existing baseline assets:

1. Install dependencies:
   - `python -m pip install -r ml_workspace/physics_soh/requirements.txt`
2. Open and run:
   - `ml_workspace/physics_soh/notebooks/01_physics_soh_baseline.ipynb`

Outputs:

- `ml_workspace/physics_soh/output/flight_pack_features.csv`
- `ml_workspace/physics_soh/output/pack_model_params.csv`
- `ml_workspace/physics_soh/output/pack_soh_predictions.csv`
- `ml_workspace/physics_soh/output/qa_report.csv`

## Approach A Implementation (POH Proxy Label Builder)
Implemented script:

- `ml_workspace/data_driven/soh_code/poh_proxy_label.py`

Reusable segmentation module/script:

- `ml_workspace/data_driven/soh_code/flight_segmentation.py`

What it does:

- Loads extracted flight CSVs from `data/raw_csv/by_plane/<plane_id>`
- Finds active-flight windows (filters out all-zero / inactive logs)
- Segments POH-like phases from `motor power`, `IAS`, and `PRESSURE_ALT`
- Computes `delta_soc_obs` per phase for battery 1, battery 2, and pack average
- Inverts the POH phase table to infer phase SOH and aggregates to flight-level `soh_proxy_poh_flight`
- Writes CSV outputs and QA visualizations

Run for plane `166`:

```powershell
python ml_workspace/data_driven/soh_code/poh_proxy_label.py --raw-root data/raw_csv/by_plane/166 --plane-id 166 --segment-plot-count 12
```

Run for any future plane:

```powershell
python ml_workspace/data_driven/soh_code/poh_proxy_label.py --raw-root data/raw_csv/by_plane/<plane_id> --plane-id <plane_id> --segment-plot-count 12
```

Optional subset run (quick debug):

```powershell
python ml_workspace/data_driven/soh_code/poh_proxy_label.py --raw-root data/raw_csv/by_plane/166 --plane-id 166 --max-flights 50 --segment-plot-count 6
```

Outputs for each plane are written to:

- `ml_workspace/data_driven/output/poh_proxy/plane_<plane_id>/soh_proxy_poh_phase_labels.csv`
- `ml_workspace/data_driven/output/poh_proxy/plane_<plane_id>/soh_proxy_poh_flight_labels.csv`
- `ml_workspace/data_driven/output/poh_proxy/plane_<plane_id>/phase_segments.csv`
- `ml_workspace/data_driven/output/poh_proxy/plane_<plane_id>/pipeline_issues.csv`
- `ml_workspace/data_driven/output/poh_proxy/plane_<plane_id>/run_summary.csv`

Indexing note:

- Output tables now include `flight_index` (1..N, contiguous by sorted flight folder order) in addition to raw `flight_id`.
- Mapping file: `ml_workspace/data_driven/output/poh_proxy/plane_<plane_id>/flight_index_lookup.csv`

Visualization outputs:

- Segment QA plots (for manual phase verification):  
  `ml_workspace/data_driven/output/poh_proxy/plane_<plane_id>/plots/segments/flight_<flight_id>_segments.png`
- POH inversion ground-truth chart (inverted table + observed inferred points):  
  `ml_workspace/data_driven/output/poh_proxy/plane_<plane_id>/plots/poh_inversion_ground_truth.png`
- Flight-level inferred SOH trend chart:  
  `ml_workspace/data_driven/output/poh_proxy/plane_<plane_id>/plots/inferred_flight_soh_trend.png`

Segment-only run (reusable module CLI):

```powershell
python ml_workspace/data_driven/soh_code/flight_segmentation.py --raw-root data/raw_csv/by_plane/166
```

## Approach B Workspace (`SOH_normalized`)
Implemented scripts:

- `ml_workspace/SOH_normalized/soh_code/flight_segmentation.py`
- `ml_workspace/SOH_normalized/soh_code/soh_observed_norm.py`

Run full Approach B:

```powershell
python ml_workspace/SOH_normalized/soh_code/soh_observed_norm.py --raw-root data/raw_csv/by_plane/166 --plane-id 166
```

Run segmentation-only:

```powershell
python ml_workspace/SOH_normalized/soh_code/flight_segmentation.py --raw-root data/raw_csv/by_plane/166
```

Approach B outputs are written to:

- `ml_workspace/SOH_normalized/output/observed_norm/plane_<plane_id>/soh_observed_norm_flight_labels.csv`
- `ml_workspace/SOH_normalized/output/observed_norm/plane_<plane_id>/soh_observed_norm_samples.csv`
- `ml_workspace/SOH_normalized/output/observed_norm/plane_<plane_id>/normalization_model_coefficients.csv`
- `ml_workspace/SOH_normalized/output/observed_norm/plane_<plane_id>/cleaning_metrics.csv`
- `ml_workspace/SOH_normalized/output/observed_norm/plane_<plane_id>/pipeline_issues.csv`
- `ml_workspace/SOH_normalized/output/observed_norm/plane_<plane_id>/qa_summary.csv`

Indexing note:

- Approach B output tables include `flight_index` (1..N contiguous) in addition to `flight_id`.
- Mapping file: `ml_workspace/SOH_normalized/output/observed_norm/plane_<plane_id>/flight_index_lookup.csv`

Cleaning note:

- `soh_observed_norm_flight_labels.csv` now includes a cleaned series:
  - `soh_observed_norm_flight_clean`
  - `delta_soh_raw`, `delta_soh_clean`
  - `clean_jump_flag`
  - `feature_outlier_ratio`, `invalid_ratio`

## Frontend (Next.js)
Production-grade frontend scaffold now lives in:

- `frontend/`

It includes:

- Interactive homepage (`/`)
- Plane index (`/planes`)
- Per-plane dashboard (`/planes/[planeId]`)
- Mock API routes under `frontend/app/api/v1/*`
- Typed contracts in `frontend/lib/contracts/schemas.ts`
- Snapshot builder script: `frontend/scripts/build_snapshots.py`

Quick start:

```powershell
cd frontend
npm install
npm run snapshots
npm run dev
```
