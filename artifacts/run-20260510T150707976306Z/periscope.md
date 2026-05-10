# Periscope

Run `run-20260510T150707976306Z` converged with status `success`. The machine artifact contains 4 nodes and invented abstractions: invented.detect_stream_anomaly.

## What The Artifact Does
- Goals: detect_stream_anomalies
- Strategy: conservative
- Final detections: [1]
- Reason codes: goal_satisfied
## Execution Trace
- [replay] Loaded persisted machine language.
- [execute] Executed core.stream_window.
- [execute] Executed core.moving_baseline.
- [execute] Executed invented.detect_stream_anomaly.
- [execute] Executed core.emit_sink.
- [converge] Replay finished execution.
