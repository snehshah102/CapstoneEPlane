from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from ml_workspace.soh_forecast.common import ModelArtifacts, SplitFrames, TargetSpec, metric_table


@dataclass
class SequenceConfig:
    lookback: int = 12
    hidden_dim: int = 48
    batch_size: int = 32
    eval_batch_size: int = 64
    lr: float = 1e-3
    weight_decay: float = 1e-4
    max_epochs: int = 40
    patience: int = 8
    device: str = "cpu"


def build_sequence_rows(
    predictive_df: pd.DataFrame,
    feature_cols: list[str],
    target_spec: TargetSpec,
    lookback: int,
) -> list[dict]:
    rows = []
    for (_, _), group in predictive_df.groupby(["plane_id", "battery_id"], sort=False):
        g = group.sort_values(["event_datetime", "flight_id"]).reset_index(drop=True)
        if len(g) < lookback:
            continue
        for idx in range(lookback - 1, len(g)):
            split = g.loc[idx, "split"]
            if split not in {"train", "valid", "test", "holdout"}:
                continue
            if pd.isna(g.loc[idx, target_spec.next_col]) or pd.isna(g.loc[idx, target_spec.current_col]):
                continue
            window = g.loc[idx - lookback + 1 : idx, feature_cols].to_numpy(dtype=float)
            if np.isnan(window).any():
                continue
            rows.append(
                {
                    "event_id": g.loc[idx, "event_id"],
                    "split": split,
                    "X": window,
                    "y_level": float(g.loc[idx, target_spec.next_col]),
                    "current_level": float(g.loc[idx, target_spec.current_col]),
                }
            )
    return rows


def rows_to_loader(rows: list[dict], split_name: str, batch_size: int, shuffle: bool):
    subset = [row for row in rows if row["split"] == split_name]
    if not subset:
        return None, subset
    X = torch.tensor(np.stack([row["X"] for row in subset]), dtype=torch.float32)
    y = torch.tensor(np.array([row["y_level"] for row in subset], dtype=float), dtype=torch.float32)
    current = torch.tensor(np.array([row["current_level"] for row in subset], dtype=float), dtype=torch.float32)
    return DataLoader(TensorDataset(X, y, current), batch_size=batch_size, shuffle=shuffle), subset


def predict_sequence(loader, subset_rows, model: nn.Module, device: torch.device, model_name: str) -> pd.DataFrame:
    if loader is None or not subset_rows:
        return pd.DataFrame(columns=["event_id", "split", model_name])
    model.eval()
    preds = []
    with torch.no_grad():
        for xb, _yb, _current in loader:
            preds.append(model(xb.to(device)).cpu().numpy())
    pred_values = np.concatenate(preds) if preds else np.array([], dtype=float)
    return pd.DataFrame({"event_id": [row["event_id"] for row in subset_rows], "split": [row["split"] for row in subset_rows], model_name: pred_values})


def prepare_sequence_work(
    predictive_df: pd.DataFrame,
    split_frames: SplitFrames,
    feature_cols: list[str],
) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    seq_train_base = split_frames.train[feature_cols].apply(pd.to_numeric, errors="coerce")
    seq_medians = seq_train_base.median().fillna(0.0)
    seq_means = seq_train_base.fillna(seq_medians).mean()
    seq_stds = seq_train_base.fillna(seq_medians).std().replace(0.0, 1.0).fillna(1.0)

    seq_work = predictive_df.copy()
    seq_work[feature_cols] = seq_work[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(seq_medians)
    seq_work[feature_cols] = (seq_work[feature_cols] - seq_means) / seq_stds
    return seq_work, seq_medians, seq_means, seq_stds


def train_sequence_model(
    predictive_df: pd.DataFrame,
    split_frames: SplitFrames,
    target_spec: TargetSpec,
    feature_cols: list[str],
    model_name: str,
    config: SequenceConfig,
    model_builder,
) -> ModelArtifacts:
    device = torch.device(config.device)
    seq_work, seq_medians, seq_means, seq_stds = prepare_sequence_work(predictive_df, split_frames, feature_cols)
    rows = build_sequence_rows(seq_work, feature_cols, target_spec, config.lookback)
    train_loader, train_rows = rows_to_loader(rows, "train", config.batch_size, True)
    valid_loader, valid_rows = rows_to_loader(rows, "valid", config.eval_batch_size, False)
    test_loader, test_rows = rows_to_loader(rows, "test", config.eval_batch_size, False)
    holdout_loader, holdout_rows = rows_to_loader(rows, "holdout", config.eval_batch_size, False)

    if train_loader is None or valid_loader is None:
        return ModelArtifacts(model_name=model_name, predictions=pd.DataFrame(columns=["event_id", "split", model_name]), metrics=pd.DataFrame())

    model = model_builder(len(feature_cols), config.hidden_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.lr, weight_decay=config.weight_decay)
    loss_fn = nn.MSELoss()
    history = []
    best_state = None
    best_valid_mae = np.inf
    epochs_no_improve = 0

    for epoch in range(1, config.max_epochs + 1):
        model.train()
        train_losses = []
        for xb, yb, _current in train_loader:
            optimizer.zero_grad()
            pred = model(xb.to(device))
            loss = loss_fn(pred, yb.to(device))
            loss.backward()
            optimizer.step()
            train_losses.append(float(loss.item()))

        model.eval()
        with torch.no_grad():
            valid_pred = np.concatenate([model(xb.to(device)).cpu().numpy() for xb, _yb, _current in valid_loader])
            valid_true = np.concatenate([yb.numpy() for _xb, yb, _current in valid_loader])
        valid_mae = float(np.mean(np.abs(valid_true - valid_pred)))
        history.append({"epoch": epoch, "train_loss": float(np.mean(train_losses)), "valid_mae": valid_mae})
        if valid_mae < best_valid_mae:
            best_valid_mae = valid_mae
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1
            if epochs_no_improve >= config.patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    predictions = pd.concat(
        [
            predict_sequence(train_loader, train_rows, model, device, model_name),
            predict_sequence(valid_loader, valid_rows, model, device, model_name),
            predict_sequence(test_loader, test_rows, model, device, model_name),
            predict_sequence(holdout_loader, holdout_rows, model, device, model_name),
        ],
        ignore_index=True,
    )

    metrics_rows = []
    for split_name, split_frame in [
        ("train", split_frames.train),
        ("valid", split_frames.valid),
        ("test", split_frames.test),
        ("holdout", split_frames.holdout),
    ]:
        if split_frame.empty:
            continue
        pred_frame = predictions.loc[predictions["split"].eq(split_name), ["event_id", model_name]]
        if pred_frame.empty:
            continue
        eval_frame = split_frame.merge(pred_frame, on="event_id", how="inner")
        metrics_rows.append(
            {
                "model": model_name,
                "eval_split": split_name,
                **metric_table(
                    eval_frame[target_spec.next_col].to_numpy(dtype=float),
                    eval_frame[model_name].to_numpy(dtype=float),
                    eval_frame[target_spec.current_col].to_numpy(dtype=float),
                ),
            }
        )

    return ModelArtifacts(
        model_name=model_name,
        predictions=predictions,
        metrics=pd.DataFrame(metrics_rows),
        model=model,
        feature_names=list(feature_cols),
        diagnostics={
            "history": pd.DataFrame(history),
            "lookback": config.lookback,
            "seq_medians": seq_medians,
            "seq_means": seq_means,
            "seq_stds": seq_stds,
        },
    )
