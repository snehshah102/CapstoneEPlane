from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ml_workspace.soh_forecast.backbone_shape import (
    add_plane_backbone_points,
    build_evtol_backbone_points,
    build_plane_backbone_trajectory,
    calibrate_plane_battery,
    fit_backbone,
)
from ml_workspace.soh_forecast.external_backbone_common import (
    assign_plane_time_splits,
    build_evtol_pretrain_dataset,
    build_plane_flight_dataset,
    find_repo_root,
)


def main() -> None:
    repo_root = find_repo_root(Path.cwd())
    output_dir = repo_root / "ml_workspace" / "soh_forecast" / "output" / "backbone_curve_plane_166"
    output_dir.mkdir(parents=True, exist_ok=True)

    _evtol_interval_df, evtol_anchor_df = build_evtol_pretrain_dataset(repo_root / "data" / "eVTOLDataset")
    plane_df = build_plane_flight_dataset(repo_root / "ml_workspace" / "latent_soh" / "output" / "plane_166" / "latent_soh_event_table.csv")
    plane_df = assign_plane_time_splits(plane_df)

    evtol_points = build_evtol_backbone_points(evtol_anchor_df)
    external_backbone = fit_backbone(evtol_points)

    initial_calibrations = []
    for battery_id, g in plane_df.groupby("battery_id"):
        initial_calibrations.append(calibrate_plane_battery(g, external_backbone))

    plane_points = add_plane_backbone_points(plane_df, initial_calibrations, plane_weight=3.0)
    combined_points = pd.concat([evtol_points, plane_points], ignore_index=True)
    combined_backbone = fit_backbone(combined_points)

    final_calibrations = []
    for battery_id, g in plane_df.groupby("battery_id"):
        final_calibrations.append(calibrate_plane_battery(g, combined_backbone))
    final_calibration_df = pd.DataFrame([c.__dict__ for c in final_calibrations])

    trajectory_frames = []
    for battery_id, g in plane_df.groupby("battery_id"):
        calib = next(c for c in final_calibrations if str(c.battery_id) == str(battery_id))
        trajectory_frames.append(build_plane_backbone_trajectory(g, combined_backbone, calib))
    trajectory_df = pd.concat(trajectory_frames, ignore_index=True)

    evtol_points.to_csv(output_dir / "evtol_backbone_points.csv", index=False)
    plane_points.to_csv(output_dir / "plane_backbone_points.csv", index=False)
    combined_points.to_csv(output_dir / "combined_backbone_points.csv", index=False)
    external_backbone.grid.to_csv(output_dir / "external_backbone_curve.csv", index=False)
    combined_backbone.grid.to_csv(output_dir / "combined_backbone_curve.csv", index=False)
    plane_df.to_csv(output_dir / "plane166_backbone_dataset.csv", index=False)
    final_calibration_df.to_csv(output_dir / "plane166_backbone_calibration.csv", index=False)
    trajectory_df.to_csv(output_dir / "plane166_backbone_trajectory.csv", index=False)

    summary = {
        "evtol_point_count": int(len(evtol_points)),
        "plane_point_count": int(len(plane_points)),
        "combined_point_count": int(len(combined_points)),
        "calibration_rows": final_calibration_df.to_dict(orient="records"),
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2))

    print("Saved backbone outputs to:", output_dir)
    print(final_calibration_df.to_string(index=False))


if __name__ == "__main__":
    main()
