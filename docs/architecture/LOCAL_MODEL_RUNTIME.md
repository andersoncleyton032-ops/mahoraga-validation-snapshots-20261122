# Local model runtime — governed integration

## Architectural decision

Qwen3-1.7B is an internal language-model capability of Mahoraga, not Mahoraga itself. The cognitive system owns memory, identity, attention, planning, learning, tools, evidence and safety policy. The model backend supplies language generation and reasoning tokens. Cognitive modules depend on the backend-neutral \`ModelRuntime\` contract; they do not import LiteRT-LM directly.

Model weights are external device files. Never commit them to Git or package them inside the APK.

## Model artifact identity matters

The official \`litert-community/Qwen3-1.7B\` repository currently documents two distinct artifacts. The exact user-reported INT4 filename currently resolves at upstream commit \`87603f0ff3fe74b9b77ed0477edb773b4b596f32\` to a file of 977,184,032 bytes with SHA-256 \`2a72330b504a6596d53a2c00923c57173b10f1b83e6a541213ffec08d1fc5de8\`. Treat this as the upstream reference digest, not proof that the local Realme file has matching bytes; compare on-device before loading.

| Artifact | Quantization | Published size | Context | Runtime note |
|---|---|---:|---:|---|
| \`Qwen3-1.7B_dynamic_wi4b32_afp32.litertlm\` | dynamic INT4 | 932 MB | 4096 | LiteRT-LM 0.18.0+ |
| \`Qwen3_1.7B.litertlm\` | dynamic INT8, GPU composite ops | 1674 MiB | 4096 | GPU path needs LiteRT-LM 0.19.0+; CPU path 0.18.0+ |

The repository changed its default INT8 export on 2026-10-31. Do not infer the exact artifact from the model name alone. Verify the filename, size and SHA-256 on the device. The model card reports CPU peak RSS around 3.25–3.46 GiB on Pixel 8a/Galaxy S26 for the newer INT8 export, under its stated test setup; these are reference measurements, not Realme 14 measurements.

## Runtime placement

- Preferred production backend on Android: official LiteRT-LM Kotlin API in the Mahoraga Android companion.
- Preferred Termux path: install the official Android ARM64 Python wheel with pip package litert-lm-api (Python import litert_lm). Google's Python API guide explicitly lists Android aarch64, and the Qwen model card reports the Android wheel benchmarked on CPython 3.14. The optional pin is requirements-model-android.txt (0.19.2); install it only after confirming the selected model artifact. The exact Termux pip tag/install/import remains a device validation gate; do not assume it works until tested on the Realme. The Android API 23+ ARM64 wheel SHA-256 is pinned in `requirements-model-android.txt` (`ba299b57381ba3974bff6459002caac2e1ed48629bb4a7f4d2bfda04ec04ce10`); install with `pip install --require-hashes -r requirements-model-android.txt`. PyPI reports no provenance attestation for this release, so the hash pins the published artifact but does not establish an independently attested build.
- The consolidated cognitive composition factory in PR #198 constructs the in-process Python LiteRT backend with `allow_android_fallback=False`. If the Python package or native engine cannot initialize, generation fails closed; it does not silently switch to Android IPC. The ContentProvider backend and its request-ID/ACK/cancellation protocol remain a separate candidate in the Android branch (#186/#190/#192), tracked by issue #199. No Android fallback is enabled until the structured-message contract and device validation are complete.
- The Kotlin API uses \`EngineConfig(modelPath = absolutePath)\`, \`Engine.initialize()\`, and \`createConversation()\`. Initialization must run off the Android main thread.
- A single-thread executor owns engine/conversation creation, streaming and close. The sole cross-thread operation is `Conversation.cancelProcess()` after a request-ID match, so an active stream can be interrupted without cancelling a different request. Close the conversation before the engine, exactly once. If initialization fails, do not call close on an engine that never initialized successfully.
- Keep the \`.litertlm\` file in app-accessible device storage, not in APK assets. The app already has minSdk 24.
- GPU acceleration needs the optional native-library declarations for \`libvndksupport.so\` and \`libOpenCL.so\` in the application manifest. GPU availability and performance must be tested on the target SoC; use CPU as a baseline. Do not assume the Qualcomm NPU is supported by the current device/runtime combination.

Official Android integration guide: https://developers.google.com/edge/litert-lm/android

## Cognitive composition

The optional configuration is `config/litert_model_runtime.json`. It is committed disabled by default. When `enabled=true`, the composition factory requires the exact approved Qwen3 INT4 model ID and upstream SHA-256, an absolute `.litertlm` file path, and the CPU backend. GPU is rejected until a Realme device test demonstrates support and stable behavior.

`IntegratedCore` constructs `ModelRuntimeGenerationAdapter` only after that explicit opt-in. Construction is lazy: it does not load weights or run inference. The existing `Dharma.evaluate("local_compute")` gate remains in front of generation. The runtime receives only a serialized prompt and a bounded `ResourceRequest`; it shares the existing `HardwareIntelligence` resource snapshot and `KnowledgeStore` event audit. It receives no database handle in its prompt, no tool executor, no credentials and no authority to persist conversation history or execute actions.

The configuration path is deliberately separate from the legacy `config/model_runtime.json` loopback provider. Missing or disabled LiteRT configuration preserves the existing disabled loopback adapter. An invalid enabled configuration fails closed rather than silently selecting another backend. The expected SHA is checked against the model file during lazy load; the repository's upstream digest is not evidence that the local file has already been verified.

In this integration candidate, Android ContentProvider fallback is explicitly disabled because the Android app/runtime branch has not yet been reconciled with the structured-message protocol. If the Python LiteRT wheel cannot initialize, generation fails closed; it does not send an incompatible JSON prompt to an older provider.

The default prompt budget is 9,000 characters, still subject to the runtime's conservative character-to-token estimate and the 4,096-token context window after thinking/output budgets are reserved. This is a heuristic, not tokenizer-exact admission; exact token accounting remains a validation gap. The generation adapter enforces the backend prompt character cap before invoking inference.

## Android wheel availability

PyPI release `litert-lm-api==0.19.2` (13 Nov 2026) publishes a `py3-none-android_23_arm64_v8a` wheel and declares Python >=3.10. This makes the Python LiteRT backend a plausible direct Termux/Android ARM64 path, without requiring the ContentProvider for the first device trial. However, Termux's actual pip tag acceptance, import, native library loading and inference have not been tested on the Realme 14 5G. The package remains optional and is not installed by this repository change.

## Chat-template and role preservation

The adapter's versioned JSON envelope is an internal transport format, not model-visible prompt text. The Python LiteRT backend decodes it into native role/content mappings, passes system and prior user/assistant turns to `Engine.create_conversation(messages=...)`, and sends only the final user turn for generation. LiteRT-LM then applies the canonical chat template embedded in the model metadata. Automatic tool calling is explicitly disabled and no tools are registered.

Do not replace this with a plain string containing JSON or manually injected ChatML tokens: a string is automatically wrapped as a user message, while the model's packaged template is the authoritative formatter. The Android provider path must implement equivalent role-preserving mapping with `ConversationConfig.systemInstruction` and `initialMessages` before it can be re-enabled. Until then, Android fallback remains disabled in the composition factory.

Official references:
- LiteRT-LM Python API: https://developers.google.com/edge/litert-lm/python
- LiteRT-LM Qwen3 chat-template metadata: https://github.com/google-ai-edge/LiteRT-LM/blob/main/models/README.md
- Qwen3-1.7B model card: https://huggingface.co/Qwen/Qwen3-1.7B

## Adaptive resource governance

There is no single universal RAM or duration limit. \`ResourceRequest\` carries task class, priority, estimated peak memory, minimum available memory, storage reserve, duration budget and explicit background permission.

\`AdaptiveBudgetPlanner\` supplies starting budgets by task class and adjusts them using model file size, thermal status and battery state when those signals are available. A caller or future executive policy can override the request for a specific task. These values are planning estimates, not measured guarantees.

Admission uses live \`HardwareIntelligence.resource_snapshot()\` data:
- available RAM from \`MemAvailable\`;
- free space on the actual mount containing the model file;
- current foreground/screen state unless the task is explicitly marked as background;
- thermal state when a trustworthy context provider supplies it.

Peak RAM is estimated from artifact size plus runtime/KV-cache overhead until measured. A request may ask for more resources for a high-value reasoning task, but the system reserve remains explicit. If current memory or thermal admission deteriorates during inference, the runtime unloads the model to release memory. Background loading is denied unless both the request explicitly allows it and its task class is \`background\`.

Time budgets are task-specific. LiteRT streaming can honor a cooperative deadline between yielded chunks. A backend blocked inside a native call may not be interruptible immediately; in that case the runtime detects and records an overrun after return. Hard cancellation requires a backend API that guarantees cancellation. Never describe a soft deadline as a hard kill.

## Lifecycle and privacy

- Load lazily on demand; do not reserve several gigabytes at application startup.
- Keep one engine owner, but create and close a fresh conversation for each inference. Mahoraga's KnowledgeStore and cognitive context remain the source of memory; hidden model chat history must not accumulate across unrelated tasks.
- Allocate bounded thinking and output tokens by task class (interactive, reasoning, maintenance, background). Thinking can be disabled explicitly; output and thinking budgets are checked against the model's 4096-token context window before inference.
- Qwen3 sampling defaults for the current thinking-enabled path follow the official Qwen3-1.7B guidance: `top_k=20`, `top_p=0.95`, `temperature=0.6`. Do not silently replace missing values with `top_k=1` (greedy decoding); partial overrides retain the other defaults. If a future task explicitly disables thinking, it may select the documented non-thinking profile (`top_k=20`, `top_p=0.8`, `temperature=0.7`). These are model-level starting points, not device-performance claims. Source: https://huggingface.co/Qwen/Qwen3-1.7B
- Serialize access; one engine/conversation owner at a time. Cancellation is request-ID-scoped, idempotent and produces a retained terminal `cancelled` outcome for ACK/TTL handling.
- Keep prompts and generated text out of SQLite audit events.
- Persist model ID, artifact size/hash status, admission decisions, elapsed time, token/text lengths and error class only.
- Unload to free memory while allowing later reload; permanently close only when the runtime owner is shutting down.
- Do not infer that the model is available merely because a file exists.

## Promotion gates

1. Identify the exact downloaded artifact and verify SHA-256.
2. Add and compile the Android Kotlin LiteRT-LM dependency in the companion app; pin a version compatible with the artifact (0.19.1 for the current INT8 GPU export).
3. Implement the single-thread engine/conversation owner and explicit cancellation/close lifecycle.
4. Validate the model path and storage permission without copying weights into the APK.
5. Run CPU and GPU benchmarks on the Realme 14 5G. Measure peak RSS, initialization time, time-to-first-token, decode tokens/s, thermal rise, battery drain, cancellation latency and unload/reload behavior.
6. Calibrate the planner from measured device traces. Until then, estimated budgets are provisional.
7. Connect the runtime to LanguageEngine/CognitiveEngine only through the backend-neutral contract and compare against a non-LLM baseline on held-out PT-BR tasks.
8. Keep the runtime disabled by default until the Android artifact, build, and on-device inference are proven.

## Evidence status

The Python lifecycle, adaptive resource admission, per-request conversation/token budgets, direct Android Python API backend, provider fallback and fake-backend tests are implemented on the integration branch. The Android companion branch also contains a Kotlin LiteRT-LM owner, SAF import, Termux-only provider, and device-side RAM/thermal/battery admission. Request-ID cancellation, terminal retention/ACK, and sampler-config propagation are implemented in stacked Draft PRs #190/#192; the Python deadline/ACK side is in #191/#194. Hosted CI has not executed their test steps because GitHub runners repeatedly failed before job initialization; see issue #196. No successful test run, Android APK, or Realme inference benchmark is claimed by this document.


## Additional source-review hardening — 2026-11-23

- The generation port and loopback adapter now both satisfy the same lifecycle contract, including explicit `close()`. Structured requests require the final message to be a user turn and system messages to precede conversation history.
- Load admission now checks free space on `ModelSpec.cache_dir`, where LiteRT compiled/runtime artifacts are written, rather than assuming the model file and cache share a mount.
- Python LiteRT inference uses a deadline watchdog that invokes the native `Conversation.cancel_process()` API, then closes the per-request conversation. Cancelled conversations are never reused.
- `ModelSpec` and `ResourceRequest` reject malformed numeric, digest, duration and background-policy types rather than accepting booleans/floats or leaking type errors.
- These are source-level corrections with regression tests added; CI has not executed them.
- The remaining cognitive gap is dynamic recruitment: the cognitive fabric currently records runtime status but does not select the LLM during ordinary request cycles. Issue #200 tracks the capability-recruitment architecture. Issue #201 tracks tokenizer-exact context accounting; the current character estimate is explicitly heuristic.


## Python/Android prompt protocol parity — 2026-11-23

The Android provider branch (#192) now has a structured parser and advertises prompt protocol version 1. Python verifies both the version and protocol string, plus the imported artifact SHA, before loading the provider. A source review found and corrected contract drift: both sides now enforce 32 messages, 20,000 characters per message, 50,000 total characters, system-before-history ordering and a final user turn. Recognized malformed envelopes fail closed. Python and Kotlin tests consume the same valid and invalid-order JSON fixtures under `android-runtime/app/src/test/resources/`.

This is source-level parity only. Android and Python CI workflows still fail before runner steps; no Gradle/Kotlin test or Python test has executed. Android context budgeting still uses `prompt.length`, while Python uses a character/token heuristic; neither is exact Qwen3 tokenization (issue #201). Android fallback remains disabled until the branch ancestry is reconciled and build/test/device gates pass.


## Token-count API audit — issue #201 (2026-11-23)

Upstream LiteRT-LM v0.19.1 source exposes C++ `Conversation::CountTokens(message)`, but the public Python wrapper does not expose that method. Python exposes `Conversation.token_count`, while `Engine.create_conversation()` does not expose `prefill_preface_on_init`; the C++/Kotlin default for prefill is false. Kotlin exposes `ConversationConfig.prefillPrefaceOnInit` and `Conversation.getTokenCount()`, so it can count a prefetched system/history prefix, but the pending final user turn and full rendered Qwen chat template are not counted by that read. No exact pre-generation count for the complete prompt has been proven in either binding.

Do not label `token_count` as exact preflight. Options under investigation: upstream API enhancement exposing exact CountTokens/rendered prompt count in both bindings; a tokenizer tied cryptographically to the exact model artifact; or conservative admission margin plus native overflow handling and disposal of the per-request Conversation. The last option is a safe interim, not exact token accounting.


## Exact context-token accounting — investigation 2026-11-23

The current runtime estimate `ceil(len(prompt) / 3)` is only a conservative heuristic. It must never be described as an exact Qwen3 token count.

The upstream LiteRT-LM v0.19.1 C++ API already has the correct primitive: `Conversation::CountTokens(messages, optional_args)`. Its contract counts the new messages against the active conversation/preface, includes prompt-template tokens and media soft tokens, and does not mutate the conversation or KV cache. The implementation uses the actual template rendering and model data processor in dry-run mode before calculating input tokens.

However, the v0.19.1 wrappers inspected do not expose that method:
- Python exposes `Engine.tokenize(text)`, `render_message_to_string` and post-prefill/decode `token_count`; it does not expose a message-aware, non-mutating `count_tokens` or preface-rendering method.
- Kotlin exposes `getTokenCount()`, `renderMessageIntoString()` and `renderPrefaceIntoString()`; it does not expose `countTokens()`.
- KV-cache token count is an observed post-prefill/decode measurement, not a pre-generation budget check.
- The exact `litert-lm-api==0.19.2` ARM64 wheel/artifact still requires inspection on the actual target; v0.19.1 source is not proof of 0.19.2 wrapper parity.

Decision: do not substitute `Engine.tokenize(raw_prompt)` for the complete message/template count. The long-term fix is to expose the existing native `Conversation::CountTokens` through supported Python and Kotlin bindings (or a stable C API) and run shared cross-runtime fixtures. Until then, keep the count explicitly estimated, use a conservative context reserve and native overflow as a final guard. No exact-count claim is allowed.

Tracking: issue #201. Upstream references:
- `runtime/conversation/conversation.h` and `conversation.cc` at LiteRT-LM v0.19.1
- `python/litert_lm/interfaces.py` at v0.19.1
- `kotlin/java/com/google/ai/edge/litertlm/Conversation.kt` at v0.19.1



### Artifact provenance — `litert-lm-api==0.19.2` (2026-11-23)

PyPI metadata confirms the Android ARM64 wheel `litert_lm_api-0.19.2-py3-none-android_23_arm64_v8a.whl` (10.0 MB, uploaded 2026-11-13) with SHA-256 `ba299b57381ba3974bff6459002caac2e1ed48629bb4a7f4d2bfda04ec04ce10`, matching the repository's hash pin. PyPI reports no build provenance/attestation. The inspected GitHub release page still lists v0.19.1 as the latest tagged release; no corresponding v0.19.2 source tag was found during this review. A direct wheel download from the research environment failed, so the exact 0.19.2 wheel's internal Python wrappers/native symbol exports remain uninspected.

Consequences:
- The v0.19.1 source inspection is evidence about that tag, not proof of the exact 0.19.2 wheel.
- The hash pin protects byte identity after acquisition but does not provide source/build provenance.
- Before enabling runtime on the Realme, inspect the pinned wheel in an isolated ARM64 environment without installing it into the user's Termux environment; record package metadata, `interfaces.py`, exported native symbols and dependency ABI.
- Do not change the version or hash pin without an explicit compatibility and provenance review.


## Provider branch reconciliation update — 2026-11-26

The previously separate Kotlin provider work from PR #192 has now been ported into integration branch `integration/android-model-provider-secure-20261126`, stacked on the Termux signer/wake hardening in PR #286. This is a source integration, not a merge or device validation.

The integrated provider now has these additional gates:
- Every `ContentProvider.call` verifies the Binder caller UID, installed `com.termux` UID/package membership, and the current Termux APK signer against the same pinned official release allowlist used by the WorkManager bridge.
- The app-private imported model file is re-hashed with streaming SHA-256 immediately before Engine initialization; missing, malformed or mismatched digests fail closed.
- The provider currently rejects GPU requests. CPU is the only permitted backend until the Realme demonstrates GPU backend availability, stability, thermal behavior and acceptable memory headroom.
- The Android owner independently checks screen state and the authenticated Termux caller. Screen-on operations may run while the companion Activity is background. Screen-off loading requires the user-enabled WorkManager cycle and charging; background inference additionally requires the explicit background task class, allow flag and enabled schedule. The API 34 authenticated-wake requirement is included when deciding whether a background schedule is valid.
- SAF import remains atomic and app-private. The provider does not accept arbitrary model paths from Termux.

The branch also merges the provider's Kotlin Engine owner, cancellation/result-retention protocol, prompt envelope and sampling defaults with the newer Java WorkManager bridge and signer policy. The direct Python Android ARM64 backend remains the preferred first device experiment; the Python ContentProvider fallback remains disabled by default.

**Evidence status:** source integration and tests have been authored; CI has not yet executed this integration branch. Do not describe the provider as validated or enable the Python fallback. Required next gates are public mirror Gradle/JUnit/Python execution, private runner recovery, and a controlled Realme CPU-only end-to-end test.

The native provider and the shared model-runtime config now use the same conservative CPU admission estimate for the 932 MiB Qwen3 INT4 artifact: 1.5× artifact size + 1,152 MiB runtime overhead + max(512 MiB, 8% of total RAM). This is calibrated against the upstream model card's approximately 2.5 GB CPU peak RSS, not against a Realme measurement. Device telemetry must determine whether the estimate can be safely refined.


## Android deadline authority — 26/11/2026

The Termux/Python runtime may select a task-specific requested duration, but Android does not trust a caller-supplied duration_policy_applied flag. The Android provider ignores that IPC field; ModelEngineOwner always calls ModelBudgetMath.durationSeconds, which validates finite positive values, validates task class even for explicit durations, caps requests at 2x task-class defaults, and applies local thermal/battery derating. The current caps are interactive 60s, reasoning 240s, maintenance 360s and background 600s. Python retains duration_policy_applied only as an internal planner marker and no longer forwards it to Android. Local derating may be applied conservatively after Python planning; this is intentional until a verifiable budget receipt exists. These are task-specific guardrails, not universal hardware assumptions. No LiteRT-LM model load or device execution is implied by unit-test evidence.


## Python/Android duration-ceiling parity — 26/11/2026

The native Android owner is not the only enforcement point. The Python in-process LiteRT-LM backend is normally the primary backend, so its immutable `ResourceRequest` now enforces the same maximum duration as Android: interactive 60s, reasoning 240s, maintenance 360s, background 600s. A caller-provided deadline is clamped at construction; the adaptive planner also clamps an override before priority weighting, caps again after weighting, and then applies thermal/battery derating. Smaller caller-selected deadlines remain valid.

This is a per-task guardrail, not a universal duration limit. Python LiteRT still relies on a cooperative watchdog and native Conversation cancellation; a backend/native call that does not return or honor cancellation cannot be equated with an OS-enforced hard kill. Android independently recomputes and applies its own cap and derating. Test coverage was added for all four task classes and for cap→priority→thermal ordering; these tests are not executed yet.
