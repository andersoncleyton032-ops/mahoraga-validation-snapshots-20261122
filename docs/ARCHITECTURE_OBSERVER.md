# Read-only architecture observer

## Purpose

`experiments.architecture_observer` is the first structural self-understanding
primitive in the public validation lab. It creates a deterministic inventory
of Python modules, top-level declarations, statically visible internal imports,
source hashes, parse failures, probable import cycles and agent modules for
which no direct test import was detected.

It is deliberately read-only. It does not import inspected modules, execute
project code, install dependencies, access the network, create workspaces or
write reports to the inspected repository.

## Boundaries

- Scans only `agent/`, `experiments/` and `tests/`.
- Skips symlinks and common generated/dependency directories.
- Defaults to at most 512 Python files and 1,000,000 bytes per file.
- Uses Python AST parsing; dynamic imports, reflection, dependency injection and
  runtime behavior are outside its model.
- A module without a direct test import is a heuristic lead, not proof of
  missing tests.
- Static import cycles are evidence for review, not automatic defects.
- The report records source SHA-256 digests for reproducibility. These hashes
  are integrity identifiers, not signed provenance.

## Why this is the first milestone

The lab already has bounded candidate admission, lifecycle metadata and a
persistent experiment ledger, but no reliable candidate-discovery mechanism.
Before generating patches, Mahoraga needs an inspectable baseline of its own
structure and explicit uncertainty about what the observer cannot see.

## Next engineering gates

1. Add a versioned capability/contract registry and map observed modules to
   declared responsibilities without treating names as proof of behavior.
2. Compare structural observations with test, CI and runtime evidence.
3. Generate falsifiable gap hypotheses with source references and confidence.
4. Persist observations and hypotheses in the canonical KnowledgeStore.
5. Only then design isolated patch generation and independently attested
   execution. A lifecycle label alone must never be accepted as proof of a
   real operating-system sandbox.
