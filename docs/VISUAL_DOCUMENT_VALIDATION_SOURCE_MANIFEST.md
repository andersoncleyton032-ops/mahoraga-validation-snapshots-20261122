# Visual document core — curated validation source manifest

## Private source lineage
- Private repository: `andersoncleyton032-ops/mahoraga-core`.
- Source PR: #272, Draft, branch `feat/visual-document-model-20261125-rebased`.
- Private source head at import: `74390a8579a78d600a3fc7d1c43dc08c648c566e`.
- Public validation target: PR #9, branch `validation/android-capability-lab-main-20261125`, based on public mirror `main`.

## Selected modules
- `agent/__init__.py`, `agent/cancellation.py`.
- `agent/store.py`: canonical SQLite KnowledgeStore implementation used by visual-document persistence tests. Tests always supply a temporary database path; no user database is copied.
- `agent/cpu_path_tracer.py`, `agent/image_task.py`.
- `agent/visual_creation.py`, `agent/visual_scene_compiler.py`, `agent/visual_document_store.py`.
- `tests/test_visual_creation.py`: 39 tests.
- `tests/test_visual_scene_compiler.py`: 28 tests.
- `tests/test_visual_document_store.py`: 13 tests.

## Review and exclusions
- The selected modules use standard-library Python only in this test slice; the CPU tracer imports the local cancellation token. No subprocess, network client, dynamic code execution or arbitrary tool invocation is introduced by these modules.
- The KnowledgeStore is included only because VisualDocumentStore shares its SQLite path. Tests create isolated temporary databases; no memory files, DB, WAL/SHM, logs, model, dataset or artifact is copied.
- Fixtures are synthetic; no user/device identifiers or personal data are included.
- The three visual test files comprise 80 of the original 86 targeted tests. The remaining six (three executor, two image-generation/provenance and one full IntegratedCore integration test) are intentionally excluded because they require the full private integration dependency graph. Four new VisualDocumentLab tests are also excluded from this curated slice.
- This curated snapshot does not validate IntegratedCore, the governed renderer, the VisualDocumentLab harness, the full private test suite or Android/Realme runtime behavior.


## Validation corrections (25/11/2026)

- Updated visual source head: `a07b7f10493b316271753da25707275899e7dc77`.
- Corrected two stale test-message expectations to assert the actual parent-cycle and non-JSON-type errors; compiler-version message matching is now case-insensitive.
- Fixed a numerical edge case in `VisualSceneCompiler._rotate`: components with absolute value below `1e-12` are canonicalized to zero, preventing trigonometric residue from leaking into scene transforms/hashes.


## Governed executor and generation provenance slice

- Additional selected source: `agent/image_task.py`, `agent/image_generation.py`, `agent/image_task_executor.py`.
- Additional test file: `tests/test_visual_execution_provenance_slice.py`.
- Three executor tests exercise document-provenance persistence/reverification, task mismatch rejection before admission and stored-artifact provenance mismatch rejection. They use a deterministic test selector and fake admission callbacks; they do not validate the production global arbiter or manifest selector.
- Two ImageGenerationEngine tests exercise the provenance validator for matching records and scene/authentication mismatch.
- This raises original visual test coverage from 80/86 to 85/86. The remaining original test is the full IntegratedCore shared-store wiring test; it is excluded because it requires the complete private integration dependency graph. Four new VisualDocumentLab tests also remain outside this public slice.
- Combined Python suite in this snapshot now contains 85 original visual tests plus six auxiliary contract tests (five Android manifest/Activity + one source-manifest contract). Android JVM tests are separate Gradle tests.


## Stored artifact verifier dependency

- Added `agent/image_asset.py` and `agent/image_asset_verifier.py` because the selected executor calls the same verifier used by the production image-generation path. The verifier uses the local CPU path tracer, ImageGenerationEngine and cancellation token; no external service or arbitrary command is introduced.
- This closes a missing dependency in the first curated executor slice. The two executor tests that previously failed at import time can now reach the actual stored-artifact verification path.


## VisualDocumentLab headless harness slice

- Added `scripts/visual_document_lab.py` after moving IntegratedCore/KnowledgeStore imports into the CLI entrypoint. Importing the orchestration class no longer eagerly imports the full core graph; the CLI still constructs the real IntegratedCore at runtime.
- Added three headless harness tests in `tests/test_visual_document_lab.py`, using the real KnowledgeStore and VisualDocumentStore with an injected test core/blocked selector. They validate three immutable revisions and compile provenance, transform revision ancestry, and the guarantee that a blocked selector never calls the executor.
- The original full IntegratedCore provenance-forwarding test remains in the private suite as `tests/test_visual_document_lab_integration.py` and is not copied into this curated snapshot because it requires the full integration dependency graph.


The executor/generation provenance slice additionally requires `agent/artifact_store.py`; it is included alongside `agent/image_asset.py` and `agent/image_asset_verifier.py` so the exact ImageGenerationEngine persistence path can run. ArtifactStore writes only inside the test-provided temporary root in this curated test slice.


## ArtifactStore layout regression coverage

- Added `tests/test_artifact_store.py` (10 tests) and updated `agent/artifact_store.py` to create the private blob and descriptor directories before validating them.
- The previous 92-pass/2-fail run exposed that _ensure_layout created the root but checked blobs/descriptors before creating those child directories. The fix validates the root first (so insecure existing roots are not modified), creates each child with mode 0700, then validates canonical path, symlink state and permissions.
- This snapshot now includes the complete local ArtifactStore dependency and its focused security/round-trip regression suite.


## VisualDocumentLab lifecycle/positive-gate refresh — 25/11/2026

The curated branch now also mirrors private PR #276:
- CLI always closes `IntegratedCore` in `finally`, including command errors.
- The headless test suite adds a positive *delegation-only* path with a fake selector/executor, explicit resource estimates, and provenance forwarding.
- It verifies fail-closed behavior when the selector selected a backend but resource estimates are missing.
- It verifies CLI core cleanup on success and error.

The current headless file has seven pytest cases (including the two parameterized CLI cleanup outcomes). One full-core forwarding test remains excluded because it imports the private IntegratedCore graph. The visual-specific coverage represented by the current snapshot is 92/94 cases (85/86 original + 7/8 VisualDocumentLab). With 11 ArtifactStore tests, 5 Android contracts and 1 source-manifest contract, the refreshed Python snapshot is expected to contain 109 tests. The previous run #45555686041 only executed the older 105-test snapshot; no approval is claimed for the refreshed 109-test head.


## Run #45598428140 — 25/11/2026

The refreshed Python snapshot completed successfully:
- Python 3.12: 109 passed in 0.86s.
- Python 3.14: 109 passed in 0.66s.
- This includes the seven current VisualDocumentLab headless cases. Visual-specific coverage is 92/94 (85/86 original + 7/8 VisualDocumentLab); the two excluded full-core tests remain unexecuted.
- Android Capability Lab job was still running at this checkpoint; no current Gradle/JVM result is claimed here.
