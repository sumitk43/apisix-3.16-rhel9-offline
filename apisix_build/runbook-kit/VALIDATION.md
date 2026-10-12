# Validation performed on 11 October 2026

- All three public input archive hashes verified. OpenResty matched a fresh public download; both module archives were freshly downloaded from their public version-tag URLs.
- No earlier custom patch seed was an input to the generator.
- All 38 generated patches passed forward-only, zero-fuzz verification/application on a second fresh source tree.
- Entire final source contents matched the earlier verified seed-based source tree byte for byte.
- Revised build-offline.sh patches phase passed against a separate clean compilation source tree; its final source contents matched the generator verification tree byte for byte.
- Bash and Python syntax checks passed.
- A complete new compilation/runtime test and work RHEL9 deployment were not performed in this update. The previous Docker build and end-to-end results remain the main runbook's runtime evidence.
