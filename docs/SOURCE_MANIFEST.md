# Source and provenance manifest

- Private source repository: `andersoncleyton032-ops/mahoraga-core`
- Source `main` snapshot: `498fea2c52c374c8bb661d8ead42a5bf5c55be16`
- Original source PR #143 head: `520a3cae969845dc382b3031a10a8a71072bd322`
- Validated experimental snapshot PR #2 head at import: `e5d4ab21548df65fb589c5c645276c4dfaa3a1bd`

## Scope warning
The private repository has a substantially newer integrated architecture on research/integration branches. This public snapshot deliberately does **not** copy that entire architecture. The small `agent/` baseline below is not the current production/core architecture and should not be used as its representation.

## Curated source files
Core files copied from private `main`: `agent/actions.py`, `agent/device_core.py`, `agent/dharma.py`, `agent/lab.py`, `agent/main.py`, `agent/memory.py`, `agent/physics.py`, `tests/test_dharma.py`, `tests/test_physics.py`, and `.gitignore`.

Lab-only adaptations and fixes:
- package-relative imports in `agent/main.py`;
- default persistence paths in `agent/actions.py`, `agent/lab.py` and `agent/memory.py` point inside this checkout rather than `~/mahoraga`;
- missing `os` imports in the memory and experiment-log modules were found by behavioral tests and fixed in this snapshot;
- the physics simulation received a maximum-step budget and numeric-domain checks;
- path-isolation, persistence and adversarial regression tests were added.

The four cognitive/physiology/evolution modules and their focused tests were imported from validated snapshot PR #2. They include validation-only fixes and are not byte-identical to source PR #143.

New lab-only components:
- `experiments/evolution_governor.py`: bounded candidate lifecycle; lexical scope is limited to `experiments/`, `tests/` and `docs/`. It records state and caller-supplied evidence; it does not execute or authenticate evidence.
- `experiments/autonomous_lab_cycle.py`: one-step integration of simulated physiology, interest selection and the lab-only governor; planning/admission only.
- corresponding tests cover quotas, dependency admission, path constraints and non-execution declarations.

## Deliberately excluded
- `memory/data.json`: project/user memory contents.
- `logs/activity.log`: operational activity history.
- `agent/physics.py.pre_*`: historical backups remain only in the private source repository.
- Original Git history and commit metadata: provenance is recorded here, not by importing private history.
- Private continuity records, audit logs, local databases, device reports, credentials and user-specific files.

This is a curated experimental baseline, not proof that all private branches or files have been copied. Further imports require inspection for personal data, credentials, operational state, side effects, dependencies and license compatibility.
