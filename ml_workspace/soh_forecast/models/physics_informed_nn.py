from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from sklearn.metrics import mean_absolute_error
from sklearn.preprocessing import StandardScaler
from torch import nn

from ml_workspace.soh_forecast.common import ModelArtifacts, SplitFrames, TargetSpec, metric_table
from ml_workspace.soh_forecast.models.physics_hybrid_nn import _build_drive_frame


@dataclass
class PhysicsInformedConfig:
    hidden_dim: int = 96
    lr: float = 1e-3
    weight_decay: float = 1e-5
    max_epochs: int = 150
    patience: int = 12
    device: str = "cpu"
    stress_col: str = "rolling_stress_index_mean_5"
    data_weight: float = 1.0
    step_weight: float = 1.0
    residual_weight: float = 0.5
    monotonic_weight: float = 0.15
    initial_weight: float = 0.25
    state_residual_scale: float = 8.0
    context_feature_candidates: tuple[str, ...] = (
        "observed_soh_pct",
        "latent_soh_filter_pct",
        "measurement_sigma_pct",
        "condition_multiplier",
        "current_abs_mean_a",
        "p95_abs_current_a",
        "avg_cell_temp_mean_c",
        "avg_cell_temp_span_c",
        "soc_mean_pct",
        "soc_span_pct",
        "event_duration_s",
        "rolling_condition_mean_5",
        "rolling_temp_mean_5",
        "rolling_soc_mean_5",
        "rolling_duration_mean_5",
        "rolling_sigma_mean_5",
        "rolling_gap_days_mean_5",
        "rolling_stress_index_mean_5",
        "rolling_stress_index_max_5",
        "cumulative_efc",
        "cumulative_ah",
        "cumulative_flight_count",
    )


class StandardPINNForecastNet(nn.Module):
    def __init__(self, context_dim: int, n_drives: int, hidden_dim: int, time_scale_days: float, state_residual_scale: float):
        super().__init__()
        self.time_scale_days = max(float(time_scale_days), 1.0)
        self.state_residual_scale = float(state_residual_scale)
        self.state_net = nn.Sequential(
            nn.Linear(1 + context_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1),
        )
        self.physics_bias_raw = nn.Parameter(torch.tensor(-5.0))
        self.physics_weights_raw = nn.Parameter(torch.full((n_drives,), -4.0))
        self.health_weight_raw = nn.Parameter(torch.tensor(-3.0))

    def forward(self, age_days: torch.Tensor, context: torch.Tensor, current_anchor: torch.Tensor) -> torch.Tensor:
        scaled_time = age_days.unsqueeze(-1) / self.time_scale_days
        state_input = torch.cat([scaled_time, context], dim=1)
        correction = self.state_residual_scale * torch.tanh(self.state_net(state_input).squeeze(-1))
        return torch.clamp(current_anchor + correction, min=0.0, max=100.0)

    def physics_rate(self, drives: torch.Tensor, soh: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        weights = F.softplus(self.physics_weights_raw) + 1e-5
        health_gain = F.softplus(self.health_weight_raw)
        health_gap = torch.clamp((100.0 - soh) / 100.0, min=0.0)
        base_rate = F.softplus(self.physics_bias_raw) + torch.sum(weights.unsqueeze(0) * drives, dim=1)
        rate = base_rate * (1.0 + health_gain * health_gap)
        return rate, weights, health_gain


def _sort_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    if "event_datetime" in out.columns:
        out["event_datetime"] = pd.to_datetime(out["event_datetime"], errors="coerce")
    sort_cols = [col for col in ["plane_id", "battery_id", "event_datetime", "flight_id"] if col in out.columns]
    return out.sort_values(sort_cols).reset_index(drop=True)


def _build_context_frame(df: pd.DataFrame, config: PhysicsInformedConfig) -> tuple[pd.DataFrame, list[str]]:
    cols = [col for col in config.context_feature_candidates if col in df.columns]
    if not cols:
        return pd.DataFrame({"physics_context_bias": np.zeros(len(df), dtype=float)}, index=df.index), ["physics_context_bias"]
    return df[cols].apply(pd.to_numeric, errors="coerce"), cols


def _scale_context_frames(frames_by_split: dict[str, pd.DataFrame], config: PhysicsInformedConfig):
    train_ctx, context_cols = _build_context_frame(frames_by_split["train"], config)
    train_medians = train_ctx.median().fillna(0.0)
    train_ctx = train_ctx.fillna(train_medians).fillna(0.0)

    def transform(frame: pd.DataFrame) -> pd.DataFrame:
        ctx, _ = _build_context_frame(frame, config)
        for col in train_ctx.columns:
            if col not in ctx.columns:
                ctx[col] = np.nan
        return ctx[train_ctx.columns].fillna(train_medians).fillna(0.0)

    scaler = StandardScaler()
    transformed = {split: transform(frame) for split, frame in frames_by_split.items()}
    scaled = {}
    scaled["train"] = scaler.fit_transform(transformed["train"])
    for split, frame in transformed.items():
        if split == "train":
            continue
        scaled[split] = scaler.transform(frame) if not frame.empty else np.empty((0, train_ctx.shape[1]), dtype=float)
    return scaled, context_cols, scaler, train_medians


def _augment_time_coordinates(split_frames: SplitFrames) -> dict[str, pd.DataFrame]:
    parts: list[pd.DataFrame] = []
    for split_name, frame in [
        ("train", split_frames.train),
        ("valid", split_frames.valid),
        ("test", split_frames.test),
        ("holdout", split_frames.holdout),
    ]:
        if frame.empty:
            continue
        part = _sort_frame(frame).copy()
        part["split"] = split_name
        parts.append(part)

    if not parts:
        return {"train": pd.DataFrame(), "valid": pd.DataFrame(), "test": pd.DataFrame(), "holdout": pd.DataFrame()}

    all_df = pd.concat(parts, ignore_index=True)
    all_df["event_datetime"] = pd.to_datetime(all_df["event_datetime"], errors="coerce")
    augmented_parts: list[pd.DataFrame] = []
    for _, group in all_df.groupby(["plane_id", "battery_id"], sort=False):
        g = group.sort_values(["event_datetime", "flight_id"]).copy()
        age_days = (g["event_datetime"] - g["event_datetime"].iloc[0]).dt.total_seconds().div(86400.0)
        g["age_days"] = age_days.fillna(0.0)
        g["next_age_days"] = g["age_days"].shift(-1)
        g["delta_to_next_days"] = (g["next_age_days"] - g["age_days"]).clip(lower=1e-6)
        g["is_initial_event"] = 0
        if not g.empty:
            g.loc[g.index[0], "is_initial_event"] = 1
        augmented_parts.append(g)

    augmented = pd.concat(augmented_parts, ignore_index=True)
    frames = {}
    for split_name in ["train", "valid", "test", "holdout"]:
        frames[split_name] = _sort_frame(augmented.loc[augmented["split"].eq(split_name)].copy())
    return frames


def _to_tensors(df: pd.DataFrame, context_scaled: np.ndarray, config: PhysicsInformedConfig):
    if df.empty:
        return None
    drive_frame = _build_drive_frame(df, config)
    return {
        "age_days": torch.tensor(df["age_days"].to_numpy(dtype=float), dtype=torch.float32),
        "delta_to_next_days": torch.tensor(df["delta_to_next_days"].fillna(1e-6).to_numpy(dtype=float), dtype=torch.float32),
        "context": torch.tensor(context_scaled, dtype=torch.float32),
        "drives": torch.tensor(drive_frame.to_numpy(dtype=float), dtype=torch.float32),
        "current": torch.tensor(df["current_soh"].to_numpy(dtype=float), dtype=torch.float32),
        "target": torch.tensor(df["target_soh"].to_numpy(dtype=float), dtype=torch.float32),
        "is_initial_event": torch.tensor(df["is_initial_event"].to_numpy(dtype=float), dtype=torch.float32),
    }


def _forecast_from_outputs(soh: torch.Tensor, dsoh_dt: torch.Tensor, delta_to_next_days: torch.Tensor) -> torch.Tensor:
    return torch.clamp(soh + delta_to_next_days * dsoh_dt, min=0.0, max=100.0)


def _evaluate_split(model: StandardPINNForecastNet, tensors: dict[str, torch.Tensor] | None, device: torch.device, model_name: str, frame: pd.DataFrame):
    if tensors is None or frame.empty:
        return pd.DataFrame(columns=["event_id", "split", model_name]), {}
    age_days = tensors["age_days"].to(device).detach().clone().requires_grad_(True)
    context = tensors["context"].to(device)
    drives = tensors["drives"].to(device)
    current = tensors["current"].to(device)
    with torch.enable_grad():
        soh = model(age_days, context, current)
        dsoh_dt = torch.autograd.grad(soh.sum(), age_days, create_graph=False)[0]
        next_soh = _forecast_from_outputs(soh, dsoh_dt, tensors["delta_to_next_days"].to(device))
        rate, weights, health_gain = model.physics_rate(drives, soh)
        residual = dsoh_dt + rate
    predictions = pd.DataFrame({"event_id": frame["event_id"], "split": frame["split"], model_name: next_soh.detach().cpu().numpy()})
    diagnostics = {
        "mean_state": float(soh.detach().mean().cpu().item()),
        "mean_rate": float(rate.detach().mean().cpu().item()),
        "mean_residual_abs": float(residual.detach().abs().mean().cpu().item()),
        "weights": weights.detach().cpu().numpy(),
        "health_gain": float(health_gain.detach().cpu().item()),
    }
    return predictions, diagnostics


def train_physics_informed_nn(
    split_frames: SplitFrames,
    target_spec: TargetSpec,
    feature_cols: list[str],
    model_name: str = "physics_informed_pinn",
    config: PhysicsInformedConfig | None = None,
) -> ModelArtifacts:
    del feature_cols
    config = config or PhysicsInformedConfig()
    device = torch.device(config.device)

    augmented_frames = _augment_time_coordinates(split_frames)
    for split_name, frame in augmented_frames.items():
        if frame.empty:
            continue
        frame["current_soh"] = frame[target_spec.current_col].to_numpy(dtype=float)
        frame["target_soh"] = frame[target_spec.next_col].to_numpy(dtype=float)

    scaled_context, context_cols, context_scaler, context_medians = _scale_context_frames(augmented_frames, config)
    train_tensors = _to_tensors(augmented_frames["train"], scaled_context["train"], config)
    valid_tensors = _to_tensors(augmented_frames["valid"], scaled_context["valid"], config)
    test_tensors = _to_tensors(augmented_frames["test"], scaled_context["test"], config)
    holdout_tensors = _to_tensors(augmented_frames["holdout"], scaled_context["holdout"], config) if not augmented_frames["holdout"].empty else None

    if train_tensors is None or valid_tensors is None:
        return ModelArtifacts(model_name=model_name, predictions=pd.DataFrame(columns=["event_id", "split", model_name]), metrics=pd.DataFrame())

    time_scale_days = max(float(np.nanmax(augmented_frames["train"]["age_days"].to_numpy(dtype=float))), 1.0)
    model = StandardPINNForecastNet(
        context_dim=train_tensors["context"].shape[1],
        n_drives=train_tensors["drives"].shape[1],
        hidden_dim=config.hidden_dim,
        time_scale_days=time_scale_days,
        state_residual_scale=config.state_residual_scale,
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.lr, weight_decay=config.weight_decay)

    history: list[dict[str, float]] = []
    best_state = None
    best_valid_mae = np.inf
    epochs_no_improve = 0

    for epoch in range(1, config.max_epochs + 1):
        model.train()
        optimizer.zero_grad()
        age_days = train_tensors["age_days"].to(device).detach().clone().requires_grad_(True)
        context = train_tensors["context"].to(device)
        drives = train_tensors["drives"].to(device)
        current = train_tensors["current"].to(device)
        target = train_tensors["target"].to(device)
        delta_to_next = train_tensors["delta_to_next_days"].to(device)
        is_initial = train_tensors["is_initial_event"].to(device)

        soh = model(age_days, context, current)
        dsoh_dt = torch.autograd.grad(soh.sum(), age_days, create_graph=True)[0]
        forecast_next = _forecast_from_outputs(soh, dsoh_dt, delta_to_next)
        rate, weights, health_gain = model.physics_rate(drives, soh)

        data_loss = F.mse_loss(soh, current)
        step_loss = F.mse_loss(forecast_next, target)
        residual_loss = torch.mean((dsoh_dt + rate) ** 2)
        monotonic_loss = torch.mean(F.relu(dsoh_dt) ** 2)
        if torch.any(is_initial > 0):
            initial_loss = torch.sum(((soh - current) ** 2) * is_initial) / torch.sum(is_initial)
        else:
            initial_loss = torch.tensor(0.0, device=device)
        loss = (
            config.data_weight * data_loss
            + config.step_weight * step_loss
            + config.residual_weight * residual_loss
            + config.monotonic_weight * monotonic_loss
            + config.initial_weight * initial_loss
        )
        loss.backward()
        optimizer.step()

        model.eval()
        with torch.no_grad():
            valid_predictions, valid_diag = _evaluate_split(model, valid_tensors, device, model_name, augmented_frames["valid"])
        valid_mae = mean_absolute_error(augmented_frames["valid"]["target_soh"].to_numpy(dtype=float), valid_predictions[model_name].to_numpy(dtype=float))
        history.append(
            {
                "epoch": epoch,
                "train_loss": float(loss.item()),
                "train_data_loss": float(data_loss.item()),
                "train_step_loss": float(step_loss.item()),
                "train_residual_loss": float(residual_loss.item()),
                "train_monotonic_loss": float(monotonic_loss.item()),
                "train_initial_loss": float(initial_loss.item()),
                "valid_mae": float(valid_mae),
                "calendar_weight": float(weights[0].detach().cpu().item()),
                "cycle_weight": float(weights[1].detach().cpu().item()),
                "thermal_weight": float(weights[2].detach().cpu().item()),
                "resistance_weight": float(weights[3].detach().cpu().item()),
                "history_weight": float(weights[4].detach().cpu().item()),
                "health_gain": float(health_gain.detach().cpu().item()),
                "valid_mean_residual_abs": float(valid_diag.get("mean_residual_abs", np.nan)),
            }
        )

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

    train_predictions, train_diag = _evaluate_split(model, train_tensors, device, model_name, augmented_frames["train"])
    valid_predictions, valid_diag = _evaluate_split(model, valid_tensors, device, model_name, augmented_frames["valid"])
    test_predictions, test_diag = _evaluate_split(model, test_tensors, device, model_name, augmented_frames["test"])
    holdout_predictions, holdout_diag = _evaluate_split(model, holdout_tensors, device, model_name, augmented_frames["holdout"]) if holdout_tensors is not None else (pd.DataFrame(columns=["event_id", "split", model_name]), {})
    predictions = pd.concat([df for df in [train_predictions, valid_predictions, test_predictions, holdout_predictions] if not df.empty], ignore_index=True)

    metrics_rows = []
    for split_name, frame in [
        ("train", augmented_frames["train"]),
        ("valid", augmented_frames["valid"]),
        ("test", augmented_frames["test"]),
        ("holdout", augmented_frames["holdout"]),
    ]:
        if frame.empty:
            continue
        pred_frame = predictions.loc[predictions["split"].eq(split_name), ["event_id", model_name]]
        eval_frame = frame.merge(pred_frame, on="event_id", how="inner")
        metrics_rows.append(
            {
                "model": model_name,
                "eval_split": split_name,
                **metric_table(
                    eval_frame["target_soh"].to_numpy(dtype=float),
                    eval_frame[model_name].to_numpy(dtype=float),
                    eval_frame["current_soh"].to_numpy(dtype=float),
                ),
            }
        )

    return ModelArtifacts(
        model_name=model_name,
        predictions=predictions,
        metrics=pd.DataFrame(metrics_rows),
        model=model,
        feature_names=context_cols,
        diagnostics={
            "history": pd.DataFrame(history),
            "context_feature_names": context_cols,
            "context_scaler": context_scaler,
            "context_medians": context_medians,
            "time_scale_days": time_scale_days,
            "train_eval": train_diag,
            "valid_eval": valid_diag,
            "test_eval": test_diag,
            "holdout_eval": holdout_diag,
            "drive_feature_names": ["calendar_drive", "cycle_drive", "thermal_drive", "resistance_drive", "history_drive"],
        },
    )
