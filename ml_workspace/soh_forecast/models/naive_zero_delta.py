from __future__ import annotations

import pandas as pd

from ml_workspace.soh_forecast.common import ModelArtifacts, SplitFrames, TargetSpec, concat_frames, metric_table


def train_naive_zero_delta(split_frames: SplitFrames, target_spec: TargetSpec, model_name: str = "naive_zero_delta") -> ModelArtifacts:
    prediction_parts = []
    metric_rows = []
    for split_name, frame in [
        ("train", split_frames.train),
        ("valid", split_frames.valid),
        ("test", split_frames.test),
        ("holdout", split_frames.holdout),
    ]:
        if frame.empty:
            continue
        pred = frame[target_spec.current_col].to_numpy(dtype=float)
        prediction_parts.append(pd.DataFrame({"event_id": frame["event_id"], "split": split_name, model_name: pred}))
        metric_rows.append(
            {
                "model": model_name,
                "eval_split": split_name,
                **metric_table(
                    frame[target_spec.next_col].to_numpy(dtype=float),
                    pred,
                    frame[target_spec.current_col].to_numpy(dtype=float),
                ),
            }
        )
    return ModelArtifacts(
        model_name=model_name,
        predictions=concat_frames(prediction_parts),
        metrics=pd.DataFrame(metric_rows),
    )
