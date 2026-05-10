from __future__ import annotations


def synthetic_anomaly_stream() -> list[dict[str, float | int]]:
    values = [10.0, 9.8, 10.1, 10.2, 9.9, 10.0, 10.3, 14.8, 10.2, 10.1]
    return [{"tick": index, "value": value} for index, value in enumerate(values)]
