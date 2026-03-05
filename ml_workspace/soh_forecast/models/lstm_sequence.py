from __future__ import annotations

import torch
from torch import nn

from ml_workspace.soh_forecast.common import ModelArtifacts, SplitFrames, TargetSpec
from ml_workspace.soh_forecast.models.sequence_common import SequenceConfig, train_sequence_model


class LSTMForecaster(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int = 48):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, batch_first=True)
        self.head = nn.Sequential(nn.Linear(hidden_dim, hidden_dim // 2), nn.ReLU(), nn.Linear(hidden_dim // 2, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, (h_n, _) = self.lstm(x)
        return self.head(h_n[-1]).squeeze(-1)


LSTMConfig = SequenceConfig


def train_lstm_sequence(
    predictive_df,
    split_frames: SplitFrames,
    target_spec: TargetSpec,
    feature_cols: list[str],
    model_name: str = "lstm_sequence",
    config: LSTMConfig | None = None,
) -> ModelArtifacts:
    config = config or LSTMConfig()
    return train_sequence_model(
        predictive_df=predictive_df,
        split_frames=split_frames,
        target_spec=target_spec,
        feature_cols=feature_cols,
        model_name=model_name,
        config=config,
        model_builder=lambda input_dim, hidden_dim: LSTMForecaster(input_dim, hidden_dim),
    )
