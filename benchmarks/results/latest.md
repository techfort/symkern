# Benchmark Results

Prompt: `Make up an array of 20 numbers with random numbers between 0-20 following a gaussian distribution. Produce the standard deviation, mean and median.`

## Scenario
- Symkern executes a mixed plan: the gaussian synthesis and statistics slice runs through a compiled backend, while the sink-facing orchestration remains in Symkern.
- The C paths remain standalone implementations of the same numeric workload, with and without artifact output.

## Summary
- Symkern core subprocess mean: 93.8967 ms
- Symkern CLI mean: 99.8888 ms
- C core mean: 1.264 ms
- C artifact mean: 2.8789 ms
- C core speedup vs Symkern core subprocess: 74.29x
- C artifact speedup vs Symkern CLI: 34.7x

## Phase Samples
- Symkern core sample timings: `{"plan_synthesis_ns": 24663, "backend_selection_ns": 28984, "invention_ns": 17170, "compiled_backend_target": "c.gaussian_array_statistics", "node_execute_ns": {"n1": 34933, "n2": 4098, "n3": 8970}, "execute_ns": 48001, "kernel_total_ns": 3037892, "compile_ns": 292847, "converge_ns": 3273984, "core_total_ns": 3570326}`
- Symkern CLI sample timings: `{"plan_synthesis_ns": 35306, "backend_selection_ns": 36353, "invention_ns": 106702, "compiled_backend_target": "c.gaussian_array_statistics", "node_execute_ns": {"n1": 29717, "n2": 3996, "n3": 9606}, "execute_ns": 43319, "kernel_total_ns": 2858923, "compile_ns": 312131, "converge_ns": 3188882, "persist_backend_artifacts_ns": 1416293, "persist_machine_code_ns": 1181562, "persist_artifact_initial_ns": 363247, "persist_periscope_render_ns": 195237, "persist_periscope_ns": 127523, "persist_total_ns": 3573428, "persist_artifact_final_ns": 276506, "submit_total_ns": 7259303}`
- C artifact sample timings: `{"generate_ns": 16626, "statistics_ns": 3742, "persist_ns": 218643, "total_ns": 255466}`
