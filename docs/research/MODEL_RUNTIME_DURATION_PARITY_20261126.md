# ModelRuntime duration parity validation snapshot — 26/11/2026

This public validation branch copies the exact `agent/model_runtime.py` and `tests/test_model_runtime.py` blobs from private Mahoraga Core PR #297 HEAD `d41be6c1db0aa1945610500f24bcbdd2efe96573`.

The scope is deliberately limited to the Python local model runtime contracts. The workflow's focused Python job executes the included tests under Python 3.12 and 3.14. This is not a full-core checkout or test collection and cannot validate Android Kotlin, WorkManager, Android provider IPC, VisualDocumentLab/IntegratedCore or device behavior.

The change makes the immutable Python `ResourceRequest` enforce the same per-task ceiling as the Android owner (2× default task durations) and hard-caps planner overrides after priority weighting, while preserving thermal/battery derating.

Previous public PR #30 had an independently observed stale-snapshot failure: its `runtime_overhead_mb=1152` version denied the 1,900 MB memory fixture (109 passed, 1 failed on Python 3.12 and 3.14). The private source copied here currently uses `runtime_overhead_mb=768`; this update is intended to validate the newer source rather than characterize the older snapshot. That earlier outcome must not be represented as a result for this revision.

No model artifact is included, no model is loaded and no Android app/device is operated.
