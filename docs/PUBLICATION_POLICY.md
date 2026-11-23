# Public validation snapshot — publication policy

## Allowed
- Reviewed source modules needed for a defined experiment or integration test.
- Synthetic tests and fixtures with generic device names and no personal data.
- Non-sensitive configuration that keeps capabilities disabled and external access off by default.
- Technical documentation specifically written for this public validation workspace.

## Never copy without a separate review and explicit approval
- `memory/data.json`, activity logs, local databases, SQLite WAL/SHM files, backups, checkpoints, model weights, datasets or artifacts.
- Continuity, handoff, session, decision, audit and operational reports from the private repository.
- Device serials, account identifiers, private paths, personal contact details, credentials, tokens or signing material.
- Full private Git history, branch history or PR metadata.
- Modules that expose arbitrary code execution or privileged external effects unless the exact threat model, approval path and isolation are reviewed.

## Runtime command surface
The included hardware and deep-diagnostics collectors use fixed read-only command allowlists before spawning subprocesses. Shell execution is not enabled for these collectors. The local model adapter accepts only a loopback IP endpoint, disallows redirects, remote fallback and tool calls, and remains disabled by default. These controls reduce exposure but do not replace runtime review or prove the whole project safe.

## Import gate
For every proposed import:
1. Identify the exact source commit and file list.
2. Inspect imports, side effects, filesystem paths, network, subprocess and dynamic execution.
3. Scan for credentials, personal data, device-specific values and private operational details.
4. Check license and third-party dependencies.
5. Replace real identifiers in synthetic fixtures.
6. Add tests that exercise behavior, not only syntax or declarations.
7. Run the exact resulting snapshot on supported Python versions.
8. Record exclusions, deviations and limitations in the source manifest.

A clean static scan is not proof that a repository contains no secrets. A public CI pass is not proof of runtime safety or Android compatibility.
