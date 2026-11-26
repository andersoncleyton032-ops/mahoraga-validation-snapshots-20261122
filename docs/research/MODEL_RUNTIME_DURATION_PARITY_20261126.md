# ModelRuntime duration ceiling parity — 26/11/2026

## Finding

PR #290 adds an Android-side duration cap in `ModelBudgetMath.durationSeconds()`, but its Python caller path remained unbounded by task class:

- `ResourceRequest.max_duration_seconds` accepted any finite positive number.
- `ModelRuntime._select_request()` returns an explicit request without consulting the budget planner when a deadline is already present.
- `AdaptiveModelBackend` normally selects the in-process `LiteRTLMBackend` first; the Android fallback is disabled by default.
- `LiteRTLMBackend.generate()` uses the request deadline for its watchdog and native `Conversation.cancel_process()`.
- Therefore an explicit large deadline could bypass the new native Android ceiling when the primary Python backend was used. The outer runtime checks elapsed time only after backend return, which is not a substitute for a bounded watchdog.

## Change in this follow-up

One shared Python policy mirrors Android's task defaults and multiplier:

| Task class | Default | Maximum (2×) |
|---|---:|---:|
| interactive | 30 s | 60 s |
| reasoning | 120 s | 240 s |
| maintenance | 180 s | 360 s |
| background | 300 s | 600 s |

The immutable `ResourceRequest` clamps any explicit duration above the task-class ceiling, so direct requests and copied requests cannot opt out. `AdaptiveBudgetPlanner` clamps custom overrides before priority weighting and caps again after priority weighting; thermal and battery derating are applied afterward. Smaller explicit deadlines remain supported. The Android owner continues to apply its own independent cap.

## Regression coverage added

- Four parameterized task classes confirm the request-boundary cap.
- One planner case verifies the order: hard cap → priority weighting (cannot exceed cap) → thermal derating.\n- One ModelRuntime dispatch test verifies the already-clamped deadline reaches the selected backend.
- Existing deadline/cancellation tests remain in place.

## Configuration/default distinction\n\nThe production configuration `config/litert_model_runtime.json` deliberately keeps `runtime_overhead_mb=1152`, aligned with Android `ModelBudgetMath`. `ModelSpec`'s constructor fallback is 768 MB and applies only to direct constructions that do not use the production JSON. `build_configured_model_generation_port()` reads the configured value explicitly; it does not silently substitute the dataclass default. Keep the conservative 1152 MB production setting until device telemetry justifies a change. The earlier public PR #30 memory-fixture failure came from a prior snapshot whose dataclass default was 1152 MB; that run is not evidence about this current private source or the new duration patch.\n\n## Validation state

**IMPLEMENTED / TESTS_ADDED / NOT_EXECUTED.** No Python/pytest/Gradle test was run in this session. The private runner issue #196 remains a pre-step infrastructure blocker. No Android device or model runtime was activated. PR #290 remains Draft and is not merged; this follow-up is stacked on its current HEAD for separate review.

## Safety interpretation

The cap is a policy limit for each task class, not a universal hardware limit. Python LiteRT cancellation remains cooperative via the native Conversation API; it must not be described as a guaranteed process kill. Android enforces a second, independent ceiling at its native boundary.
