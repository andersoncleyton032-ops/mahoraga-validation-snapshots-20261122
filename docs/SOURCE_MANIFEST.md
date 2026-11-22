# Source and provenance manifest

- Private source repository: `andersoncleyton032-ops/mahoraga-core`
- Source `main`: `498fea2c52c374c8bb661d8ead42a5bf5c55be16`
- Original source PR #143 head: `520a3cae969845dc382b3031a10a8a71072bd322`
- Validated snapshot PR #2 branch at import: `snapshot/pr-143`, head `e5d4ab21548df65fb589c5c645276c4dfaa3a1bd`

## Curated source files
Core files copied from private `main`: `agent/actions.py`, `agent/device_core.py`, `agent/dharma.py`, `agent/lab.py`, `agent/main.py`, `agent/memory.py`, `agent/physics.py`, `tests/test_dharma.py`, `tests/test_physics.py`, and `.gitignore`.

Lab-only adaptations: package-relative imports in `agent/main.py); default persistence paths in `agent/actions.py`, `agent/lab.py` and `agent/memory.py` now point inside this checkout rather than `~/mahoraga`. Added package initialization and path-isolation tests.

The four `experiments/*.py` modules and their focused tests were imported from the validated snapshot PR #2 branch. They include validation-only fixes and are not byte-identical to source PR #143.

## Deliberately excluded
- `memory/data.json`: project/user memory contents.
- `logs/activity.log`: operational activity history.
- `agent/physics.py.pre_*`: historical backups remain only in the private source repository.
- Original Git history and commit metadata: provenance is recorded here, not by importing private history.

This is a curated baseline, not proof that all private branches or files have been copied. Further imports require inspection for personal data, credentials, operational state, side effects and license compatibility.
