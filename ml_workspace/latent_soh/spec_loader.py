from __future__ import annotations

from pathlib import Path


def _parse_scalar(text: str):
    value = text.strip()
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        return value[1:-1]
    low = value.lower()
    if low in {"null", "none"}:
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        if any(ch in value for ch in [".", "e", "E"]):
            return float(value)
        return int(value)
    except ValueError:
        return value


def _load_simple_yaml(path: str | Path) -> dict:
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = line.lstrip()
        if ":" not in stripped:
            raise ValueError(f"Unsupported YAML line: {raw_line}")
        key, raw_value = stripped.split(":", 1)
        key = key.strip().strip('"').strip("'")
        value = raw_value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if not value:
            node: dict = {}
            parent[key] = node
            stack.append((indent, node))
        else:
            parent[key] = _parse_scalar(value)
    return root


def load_plane_battery_spec(spec_path: str | Path, plane_id: str) -> dict[str, object]:
    data = _load_simple_yaml(spec_path)
    plane = data.get("planes", {}).get(str(plane_id))
    if not isinstance(plane, dict):
        raise KeyError(f"Plane {plane_id} not found in {spec_path}")

    rated_23 = plane["rated_capacity"]["c23_discharge_20a"]
    return {
        "plane_id": str(plane_id),
        "battery_type": plane["battery_type"],
        "cell_type": plane.get("cell_type"),
        "series_cells": plane["configuration"]["series_cells"],
        "parallel_cells": plane["configuration"]["parallel_cells"],
        "configuration_label": plane["configuration"]["label"],
        "rated_capacity_ah": float(rated_23["capacity_ah"]),
        "rated_energy_kwh": float(rated_23["energy_kwh"]),
        "min_voltage_v": float(plane["voltage"]["min_v"]),
        "nominal_voltage_v": float(plane["voltage"]["nominal_v"]),
        "max_voltage_v": float(plane["voltage"]["max_v"]),
        "max_charge_a": float(plane["current_limits"]["max_charge_a"]),
        "max_discharge_a": float(plane["current_limits"]["max_discharge_a"]),
        "charge_temp_min_c": float(plane["temperature_limits"]["charge_c"]["min"]),
        "charge_temp_max_c": float(plane["temperature_limits"]["charge_c"]["max"]),
        "discharge_temp_min_c": float(plane["temperature_limits"]["discharge_c"]["min"]),
        "discharge_temp_max_c": float(plane["temperature_limits"]["discharge_c"]["max"]),
    }
