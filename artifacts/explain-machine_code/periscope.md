# Periscope

Run `explain-machine_code` converged with status `success`. The machine artifact contains 4 nodes and invented abstractions: opcode 1000 (Repeated anomaly scoring and thresholding can be compressed into a reusable schema.).

## What The Artifact Does
- Goals: detect_stream_anomalies
- Strategy: conservative
- Final detections: [1]
- Reason codes: goal_satisfied
## Inputs
- Passed input `events` enters from outside the machine plan.
## Outputs
- Output `windowed_events` = [[{'tick': 0, 'value': 10.0}, {'tick': 1, 'value': 9.8}, {'tick': 2, 'value': 10.1}, {'tick': 3, 'value': 10.2}, {'tick': 4, 'value': 9.9}], [{'tick': 5, 'value': 10.0}, {'tick': 6, 'value': 10.3}, {'tick': 7, 'value': 14.8}, {'tick': 8, 'value': 10.2}, {'tick': 9, 'value': 10.1}]]
- Output `baseline` = [10.0, 11.08]
- Output `scores` = [0.1999999999999993, 3.7200000000000006]
- Output `detections` = [1]
- Output `emitted` = {'detections': [1], 'sinks': ['artifact_store', 'stdout']}
## Reconstructed Strategy
- The machine resolves the goal through 4 execution stages.
- Stage `stream` uses opcode 101 transforms events into windowed_events.
- Stage `analytics` uses opcode 102 transforms windowed_events into baseline.
- Stage `opaque` uses opcode 1000 transforms windowed_events, baseline into scores, detections.
- Stage `sink` uses opcode 105 transforms detections into emitted.
- The resulting output surface is windowed_events, baseline, scores, detections, emitted.
## Machine Intent Narrative
- The machine chose a conservative anomaly envelope, raising the detection boundary before committing results.
- The machine fused scoring and threshold comparison into a reusable anomaly abstraction to reduce intermediate decision state.
- The machine terminates by materializing a sink-facing output surface rather than exposing its internal execution form.
## Machine Abstractions
- Opcode 1000 compresses source opcodes 103, 104. Purpose: Repeated anomaly scoring and thresholding can be compressed into a reusable schema.
## Execution Trace
- [replay] Loaded persisted machine language.
- [execute] Executed opcode 101.
- [execute] Executed opcode 102.
- [execute] Executed opcode 1000.
- [execute] Executed opcode 105.
- [converge] Replay finished execution.
