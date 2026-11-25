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
