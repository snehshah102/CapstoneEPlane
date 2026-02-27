# Data-Driven Workspace

This directory contains the newer data-driven SOH labeling workflows.

## Core scripts

- `soh_code/flight_segmentation.py`  
  Reusable module + CLI for splitting flights into POH-like phase segments.
- `soh_code/poh_proxy_label.py`  
  Approach A POH-proxy SOH label builder.

## Quick start

Segment only:

```powershell
python ml_workspace/data_driven/soh_code/flight_segmentation.py --raw-root data/raw_csv/by_plane/166
```

Build Approach A labels:

```powershell
python ml_workspace/data_driven/soh_code/poh_proxy_label.py --raw-root data/raw_csv/by_plane/166 --plane-id 166 --segment-plot-count 12
```
