# Generate patches from public sources and build in work RHEL9

Target: APISIX 3.18.0 with OpenResty 1.31.1.1, x86_64 EL9.

This kit replaces the old patch-archive/earlier-seed procedure. Its patch generator reads only three public source archives. It does not read an earlier custom-patches directory, download from the network, clone Git, or require a prepared custom patch archive. Generate and apply your patches on the work machine.

## What to put in your Git repository

Commit this kit's scripts, README, download-urls.tsv and checksum files. The essential scripts are generate-patches.py, build-offline.sh and e2e-test.py. No custom patch payload or generated patch archive needs to be committed to use this patch workflow. Keep a commit/tag for the exact script version used.

## Download the three patch inputs through your browser

Save with the exact names below into /tmp/apisix_build_dryrun/downloads/.

| Filename | Browser download URL |
| --- | --- |
| openresty-1.31.1.1.tar.gz | https://openresty.org/download/openresty-1.31.1.1.tar.gz |
| apisix-nginx-module-1.19.10.tar.gz | https://github.com/api7/apisix-nginx-module/archive/refs/tags/1.19.10.tar.gz |
| ngx_multi_upstream_module-1.3.4.tar.gz | https://github.com/api7/ngx_multi_upstream_module/archive/refs/tags/1.3.4.tar.gz |

These are public upstream archives, not our custom bundles. For the later OpenResty/APISIX build, acquire all the other archives listed in download-urls.tsv as well. Wasmtime uses the public prebuilt C API archive; Rust/Cargo and a Wasmtime source build are unnecessary.

## Prepare the work directory

Install the build prerequisite RPMs using your approved RHEL repositories as listed in the main runbook. Python3, patch, tar and gzip are sufficient for generating patches; compilation needs the other build tools and development headers. Git/curl/wget are not required to run this kit when files arrive through browser transfer.

Extract the kit archive into repo/ so the scripts are under repo/runbook-kit/. If transferring the scripts through your own Git repository instead, copy that directory into the same location.

```bash
mkdir -p /tmp/apisix_build_dryrun/{downloads,work,logs,repo,transfer}
cd /tmp/apisix_build_dryrun
tar -xzf downloads/APISIX_318_OpenResty_1311_Public_Source_Kit.tar.gz -C repo
(cd repo/runbook-kit && sha256sum -c SHA256SUMS)
```

Since your input archives are in downloads/, run the public-input check from that directory:

```bash
cd /tmp/apisix_build_dryrun/downloads
sha256sum -c ../repo/runbook-kit/PUBLIC_INPUT_SHA256SUMS
cd ..
```

The generator independently enforces these three input checksums. A mismatch stops before patch creation; preserve the input and investigate instead of disabling the check.

## Generate all 38 patches locally

```bash
cd /tmp/apisix_build_dryrun
set -o pipefail
bash repo/runbook-kit/build-offline.sh generate "$PWD" \
  2>&1 | tee logs/00-generate-patches.log
```

Alternatively invoke the generator directly:

```bash
python3 repo/runbook-kit/generate-patches.py "$PWD" \
  2>&1 | tee logs/00-generate-patches.log
```

Run one of these commands, not both. Expected final generator line: `ALL 38 PATCHES VERIFIED ON FRESH SOURCES`.

The generator:

1. Reads the public Nginx 1.29.2 multi-upstream patch and the 37 public APISIX patches under patch/1.29.2.4/.
2. Adapts multi-upstream for the response_received field in Nginx 1.31.1.
3. Ports the APISIX include/context changes, Lua socket install rules, request-header success notifications, shared dictionaries, stream TLS and xRPC changes.
4. Regenerates the entire old shared-dictionary deletion hunk from the current source, preserving the intended deletion despite the new source lines.
5. Applies patches in order on a disposable source tree. Partial application happens only in this disposable adaptation tree, with exact expected reject filenames/counts checked before any repair.
6. Consolidates repeated-file TLS diffs and excludes .orig/.rej files.
7. Verifies every final patch with forward-only, zero-fuzz dry-run and application on a second fresh OpenResty tree.
8. Records input and output checksums and creates a patch archive locally.

Outputs:

```text
repo/generated-patches/custom-patches/nginx-1.31.1.patch
repo/generated-patches/custom-patches/apisix-nginx-module-1.31.1-full/  (37 files)
repo/generated-patches/SHA256SUMS
repo/generated-patches/INPUT_SHA256SUMS
downloads/apisix318-openresty1311-generated-patches.tar.gz
work/generate-patches/port/openresty-1.31.1.1/
work/generate-patches/verify/openresty-1.31.1.1/
```

The archive is created in your work environment; it is not an input to transfer from the personal machine. Do not apply the original upstream patch.sh scripts afterward: they do not recognize this OpenResty version and would duplicate changes.

## Extract the compilation sources and apply the generated patches

Download all remaining public archives in download-urls.tsv before extracting. Use fresh compilation directories; the scripts stop if their guarded output directories already exist.

```bash
cd /tmp/apisix_build_dryrun
set -o pipefail
bash repo/runbook-kit/build-offline.sh extract "$PWD" \
  2>&1 | tee logs/01-extract.log
bash repo/runbook-kit/build-offline.sh patches "$PWD" \
  2>&1 | tee logs/02-patches.log
```

Run the second command only after the first succeeds. The patches phase reads the locally generated archive from downloads/, verifies its patch checksums, applies multi-upstream first, then Nginx, Lua core, HTTP Lua and stream Lua groups. Every patch gets a zero-fuzz forward dry-run before application. Expected: `ALL 38 PATCHES APPLIED` and `PHASE PASSED: patches`.

The compilation source is work/openresty-offline/openresty-1.31.1.1. Keep the verification trees separate from this compilation source.

## Compile OpenSSL and OpenResty

Run one phase at a time and stop on a nonzero exit status. These phases install under /usr/local/openresty and require the same installation privileges as the main runbook.

```bash
bash repo/runbook-kit/build-offline.sh openssl "$PWD" \
  2>&1 | tee logs/03-openssl.log
```

After that succeeds:

```bash
bash repo/runbook-kit/build-offline.sh openresty "$PWD" \
  2>&1 | tee logs/04-openresty.log
```

System OpenSSL 3.5 may remain installed. This script reproduces the tested private OpenSSL 3.4.1 installation under /usr/local/openresty/openssl; it does not switch the build to system OpenSSL 3.5. The configure flags, module versions, Wasmtime staging, Lua-header fallback symlink and runtime Lua copies follow the corrected main runbook.

Check nginx -V and ldd. Expected OpenResty 1.31.1.1, built with OpenSSL 3.4.1, private libssl/libcrypto and Wasmtime resolved, and system PCRE8/zlib resolved. No entry may report not found.

## APISIX dependencies and installation

This change removes the custom patch-seed/archive transfer requirement. It does not recreate the 79 Lua dependency packages from source. The `apisix` phase still restores the verified apisix-lua-dependencies.tar.gz and openresty-site-lualib.tar.gz from transfer/, as described in the main runbook. Those dependency archives are separate from patch generation.

If you instead rebuild dependencies on the work machine, follow the main runbook's connected LuaRocks dependency-build procedure with standard Lua and LuaJIT-targeted headers. That operation needs access to package/source downloads; it is not an offline browser-only dependency recipe in this kit.

For the existing offline dependency-bundle method, verify the transfer checksum manifest, then:

```bash
bash repo/runbook-kit/build-offline.sh luarocks "$PWD" \
  2>&1 | tee logs/05-luarocks.log
```

After that succeeds:

```bash
(cd transfer && sha256sum -c SHA256SUMS)
bash repo/runbook-kit/build-offline.sh apisix "$PWD" \
  2>&1 | tee logs/06-apisix-install.log
```

Check every native Lua dependency with ldd on the destination. Use the main runbook's standalone YAML configuration and startup steps, then:

```bash
python3 repo/runbook-kit/e2e-test.py \
  "$PWD/work/apisix-3.18.0" "$PWD/logs/final-e2e" \
  2>&1 | tee logs/apisix-final-e2e.log
```

## Validation and reruns

The generator was executed using the public module archives downloaded for this update and the OpenResty archive, whose bytes were checked against a fresh public download. All 38 patches passed on a fresh verification tree. The complete resulting source-file contents matched the prior verified seed-based source tree byte for byte. The shipped generator's release check repeated this process with input checksum enforcement enabled.

This validates patch generation and source equivalence. The revised build script passed Bash syntax checks; this update did not repeat a complete OpenResty compilation or deploy to your RHEL9 machine. Run the build and end-to-end checks there before marking destination reproduction complete.

The generator refuses to overwrite repo/generated-patches/, work/generate-patches/ or its output archive. After a failure, preserve logs and use a new workspace. Initial porting logs can contain the expected rejected hunks; only the final fresh-tree verification and final success message establish successful patch generation. Never ignore an unexpected reject, checksum mismatch, reversed-patch message or nonzero status.
