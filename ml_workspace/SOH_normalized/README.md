# SOH_normalized

This directory contains an Approach B implementation from `readME.md`:
normalized observed SOH labels (`soh_observed_norm`).

## Scripts

- `soh_code/flight_segmentation.py`  
  Reusable flight-phase segmentation module and CLI.
- `soh_code/soh_observed_norm.py`  
  Full normalized-observed-SOH pipeline (cleaning mask, confounder features, robust normalization model, and flight-level labels).

## Run

Segment-only (reusable):

```powershell
python ml_workspace/SOH_normalized/soh_code/flight_segmentation.py --raw-root data/raw_csv/by_plane/166
```

Approach B full pipeline:

```powershell
python ml_workspace/SOH_normalized/soh_code/soh_observed_norm.py --raw-root data/raw_csv/by_plane/166 --plane-id 166
```

Outputs are written under:

- `ml_workspace/SOH_normalized/output/segments`
- `ml_workspace/SOH_normalized/output/observed_norm/plane_<plane_id>`
