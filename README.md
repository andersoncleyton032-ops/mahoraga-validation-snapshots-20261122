# Mahoraga — isolated validation snapshots

This public repository is an isolated validation workspace for selected experimental components from the private `mahoraga-core` repository.

The original repository remains private and is not modified by this snapshot workflow.

## Scope

Only explicitly selected source files and their focused tests will be copied here. This repository does not contain the complete Mahoraga project and does not validate full-system integration.

## Provenance

- Source PR #142 head: `e895fadb89865a14be9a61115f9af243eb58d250`
- Source PR #143 head: `520a3cae969845dc382b3031a10a8a71072bd322`

Snapshot commits have new Git SHAs and do not preserve the source branch history.

## Validation limits

Passing these focused tests demonstrates only that the included tests pass against the included snapshot in the declared CI environments. It does not establish safety, general intelligence, full regression coverage, or integration with the private runtime.
