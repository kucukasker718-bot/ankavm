# Security Policy

This document describes how to report a security vulnerability in ankavm and
what to expect after you report it.

---

## Supported Versions

Only the latest minor release receives security patches.

| Version | Status                  |
|---------|-------------------------|
| 2.7.x   | Supported (current)     |
| 2.6.x   | Supported               |
| 2.5.x   | End of life 2026-09-01  |
| 2.4.x   | End of life             |
| older   | End of life             |

If you are running an unsupported version, upgrade before reporting an issue.
We will not produce patches for end-of-life branches.

---

## Reporting a Vulnerability

Do not open a public GitHub issue for a security vulnerability.

Send a report to `root@ankavm.local`.

If you prefer encrypted email, use our PGP key. The current fingerprint is:

```
PGP fingerprint: TBD (will be published before 2.7.1)
```

Include in your report:

- A description of the vulnerability.
- A minimal proof of concept, if you have one.
- The affected version (`ankavm --version`).
- Your name or handle if you would like to be credited.

You may also submit privately through GitHub Security Advisories:
https://github.com/ShinnAsukha/ankavm-hypervisor/security/advisories/new

---

## Response Timeline

- Acknowledgement within 72 hours of receipt.
- Initial triage and severity assessment within 7 days.
- Patch for critical issues within 14 days.
- Patch for high-severity issues within 30 days.
- Patch for medium and low severity within 90 days.

These are targets, not guarantees. We will keep you informed if a fix takes
longer.

---

## Disclosure Policy

We follow coordinated disclosure with a 90-day deadline.

- We will work with you on a fix and a disclosure date.
- If we are unable to release a fix within 90 days, you may publish your
  findings. We ask that you tell us first.
- After a fix is released we publish a GitHub Security Advisory and note the
  issue in `CHANGELOG.md`.

---

## Hall of Fame

We credit researchers who report vulnerabilities responsibly.

| Researcher | Issue | Year |
|------------|-------|------|
| _(placeholder)_ | _(placeholder)_ | _(placeholder)_ |

If you want to be listed, say so in your report.

---

## Past Advisories

Published advisories are listed at:
https://github.com/ShinnAsukha/ankavm-hypervisor/security/advisories

### Security Patch Summary

The following hardening was issued in the 2.7.0 release:

- **SEC-009 â€” OAuth2 token leak via URL**: callback now responds with a tiny
  HTML bridge page that stashes the JWT in `sessionStorage` and immediately
  calls `history.replaceState("/", â€¦)`. The token never appears in the URL
  (query or fragment), the Referer header, the browser back-button history,
  or proxy access logs. The bridge page itself is `Cache-Control: no-store,
  Referrer-Policy: no-referrer`. CI has a regression check (`?oauth2_token=`
  patterns are now a hard build failure).
- **SEC-010 â€” Setup endpoint takeover**: `/api/setup/init` now returns 403
  for any non-loopback `request.remote_addr`. A fresh node bound to a public
  interface can no longer be claimed by whoever reaches port 8006 first;
  the first admin must be created from the host itself (over SSH or the
  serial console) via `curl -X POST http://127.0.0.1:8006/api/setup/init`.
  Override (development only): `ankavm_SETUP_ALLOW_REMOTE=1`, which is
  logged at WARN level every time it triggers.
- **SEC-011 â€” High-risk feature default-off**: `feature_registry` now
  defines a `HIGH_RISK_FEATURES` set (plugin_sdk, marketplace,
  container_runtime, os_branding, oxupdate, bare_metal, cloud_burst,
  kubevirt, gitops, k8s_operator, k8s_csi, federation). These features are
  shipped *disabled* regardless of `status`. An operator must explicitly
  enable each one via the Settings â†’ Features panel or the
  `oxctl feature enable <id>` command, which writes an audit-log entry.
- **SEC-012 â€” Token storage migration to sessionStorage**: the panel now
  reads tokens from `sessionStorage` first, falling back to `localStorage`
  only for password-login sessions that pre-date this release. Logout
  clears both storages. A cookie-based HttpOnly/Secure/SameSite session is
  planned for v2.8 (large refactor â€” tracked separately).
- **SEC-014 â€” HttpOnly cookie session**: login responses (`/api/auth/login`,
  `/api/auth/2fa/verify-login`, `/api/setup/init`, OAuth2 callback) now
  attach the JWT in an `HttpOnly; Secure; SameSite=Strict` cookie
  (`ankavm_access`) alongside the JSON response. A readable double-submit
  CSRF cookie (`ankavm_csrf`) is issued at the same time; the panel echoes
  it in the `X-CSRF-TOKEN` header on every state-changing call. JS cannot
  read the access cookie, so an XSS payload cannot exfiltrate the session.
  Legacy Bearer header is still accepted for backward compatibility with
  out-of-panel clients. New `/api/auth/logout` endpoint unsets the cookies
  and revokes the session record.
- **SEC-015 â€” SSO fail-closed**: `sso_manager.oidc_handle_callback` and
  `sso_manager.saml_process_acs` now refuse to trust an assertion unless
  the appropriate signature-verification library is installed
  (`python-jose` for OIDC, `python3-saml` for SAML). With the library
  present, OIDC ID tokens are verified against the issuer's JWKS, with
  audience and issuer claims enforced. Without it, the callback returns
  an error instead of silently decoding base64. Dev override:
  `ankavm_ALLOW_UNVERIFIED_SSO=1`, WARN-logged on every callback.
  `sso_manager.crypto_status()` lets the panel surface a clear banner.
- **SEC-016 â€” Modularization seed**: a new `bp_v270.py` Flask Blueprint
  hosts the v2.7 Confidential VM / Runbook / Federation endpoints under
  `/api/v2/...` instead of growing `app.py`. The blueprint imports nothing
  from `app.py`; dependencies (decorators, response helpers) are wired
  via `init_bp_v270(...)`. This is the first concrete step toward the
  larger app.py split flagged in the external review.
- **SEC-013 â€” CI hardening**: the GitHub Actions pipeline now hard-fails
  on (a) any module that does not compile, (b) Flake8 critical errors
  (E9/F63/F7/F82) in `app.py`, (c) Bandit findings at HIGH severity,
  (d) duplicate Flask routes or endpoint functions in `app.py`, and
  (e) regression of the token-in-URL pattern. Style nits, mypy hints, and
  shellcheck warnings remain informational by design.

The following patches were issued in the 2.7.2 release:

- **SEC-029 â€” Safe archive extraction (HIGH)**: All `tarfile.extractall()` and
  `zipfile.extractall()` call sites in `app.py` now route through
  `security_utils.safe_tar_extract` / `safe_zip_extract`, which reject any
  member that is an absolute path, contains a `..` parent reference, points
  at a device file, or is a symlink/hardlink that escapes the destination
  directory. On Python 3.12+ we also apply `tarfile`'s built-in `data` filter
  for setuid/setgid stripping. Replaces the unguarded extracts that Bandit
  flagged as B202.
- **SEC-030 â€” DNS rebinding mitigation (MEDIUM)**: New
  `security_utils.resolve_safe_host()` performs a single DNS resolve, runs
  the result through the SSRF block list, and returns the literal IP for the
  caller to connect to. Outbound federation, runbook, and SSO callers now
  bind to the resolved IP so a rebinding response between resolve and connect
  cannot redirect the connection.
- **SEC-031 â€” FTP backup hardening (MEDIUM, B321/B402)**: `backup_scheduler`
  no longer unconditionally imports `ftplib`. Plaintext-FTP upload is gated
  by `ankavm_ENABLE_INSECURE_FTP=1`. When unset, `_upload_ftp` logs a warning
  and returns immediately; operators are pointed at SFTP. CI baseline drops
  the `--skip B321,B402` exemption.
- **SEC-032 â€” SSH known-hosts + first-contact UI (MEDIUM, B507)**: New
  `ssh_known_hosts` module replaces the `paramiko.AutoAddPolicy` pattern with
  a persistent `/var/lib/ankavm/known_hosts` file and a queue of pending
  fingerprint approvals visible in the panel (`Security â†’ SSH Known Hosts`).
  Trust-on-first-use is opt-in via `ankavm_SSH_TOFU=1` during migration.
  Backup-target SFTP is wired through this policy as the canonical example.
- **SEC-033 â€” pip-audit informational baseline (LOW)**: `make security` runs
  `pip-audit -r requirements.txt`; advisories with a clean upgrade path are
  tracked in CHANGELOG. CI artifact preserved every run.

The following patches were issued in the 2.7.1 release:

- **SEC-017 â€” Runbook api_call SSRF (CRITICAL)**: `runbook_executor._run_step`
  now passes every `api_call` step URL through `security_utils.validate_external_url`
  before invoking `urllib.request.urlopen`. Private (RFC 1918), loopback,
  link-local, CGNAT, and IPv6 ULA/link-local ranges are rejected. The cloud
  metadata addresses (`169.254.169.254`, IPv6 `fd00:ec2::/32`) and raw
  `localhost` are blocked. Operators who really need to call a loopback
  internal API from a runbook must opt-in per step with
  `allow_loopback: true` (the four default `DEFAULT_RUNBOOKS` are updated
  accordingly). Default scheme is `https`.
- **SEC-018 â€” Runbook vm_action argv injection (CRITICAL)**: `vm_id` extracted
  from `ctx["metric_key"]` is validated against
  `^[A-Za-z0-9._-]{1,128}$` via `security_utils.validate_vm_id` before being
  passed as a `virsh` argv element. The `action` field is also restricted to
  the libvirt verb allowlist (`start`, `shutdown`, `reboot`, `destroy`,
  `suspend`, `resume`). `virsh` is invoked by absolute path
  (`/usr/bin/virsh`, fallback `/usr/sbin/virsh`) so a poisoned `$PATH`
  cannot redirect the call.
- **SEC-019 â€” Federation member URL SSRF + TLS bypass (HIGH)**:
  `cluster_federation.add_member` and `cluster_federation.update_member`
  now validate URLs through `security_utils.validate_external_url`. The
  same private/loopback/link-local/metadata block list applies. `verify_tls=False`
  is silently coerced back to `True` unless `ankavm_FEDERATION_ALLOW_INSECURE=1`
  is set in the environment, which is for local-cluster testing only and
  produces a WARN log on every coercion.
- **SEC-020 â€” Federation forward path allowlist (MEDIUM)**:
  `cluster_federation.forward` and `cluster_federation.bulk_action` now
  validate the `path` argument against an allowlist (`/api/vms`,
  `/api/hosts`, `/api/alerts`, `/api/networks`, `/api/storage`,
  `/api/monitoring`, `/api/health`). Auth, setup, internal admin, user
  management, and session paths are explicitly blocked. A federation admin
  on this node can no longer proxy a request to the remote member's
  `/api/auth/*` or `/api/internal/*`.
- **SEC-021 â€” Federation add_member URL pre-validation (MEDIUM)**:
  `bp_v270.api_fed_add` pre-validates the URL before invoking
  `add_member`, so a malformed URL returns a clean `400` instead of a 500
  with a stack trace.
- **SEC-022 â€” Runbook shell allowlist + per-step rate limit (MEDIUM)**:
  Runbook `shell` steps may only invoke binaries on a fixed allowlist
  (`/usr/bin/virsh`, `/bin/systemctl`, `/usr/bin/nft`,
  `/usr/bin/journalctl`, plus a few diagnostics). Every argv element is
  scanned for shell metacharacters via
  `security_utils.safe_subprocess_arg`. `api_call` steps are additionally
  capped at 120 invocations per runbook per hour to prevent a single
  runbook from being used as a request-flooder against an internal API.
- **SEC-023 â€” Force-run confirmation (MEDIUM)**: `POST /api/v2/runbooks/<id>/run`
  with `force: true` now requires a `confirm_token` derived from the
  runbook id, a 60-second time bucket, and a server-side rotation key.
  The first force call returns `409` with the expected token; the second
  call (within 60 seconds) executes. This stops a stolen admin session
  from chain-running a single runbook past its quota.
- **SEC-024 â€” Plugin SDK AST sandbox hardening (MEDIUM)**: The plugin
  validator now treats sandbox-escape patterns as **errors** instead of
  warnings, including `eval/exec/__import__/compile`,
  `getattr/setattr/delattr/globals/locals/vars`,
  `os.system/os.popen/subprocess.run(shell=True)`,
  `importlib/marshal` serialization calls (and `dill`/`cloudpickle`
  variants), and attribute chains through
  `__class__/__mro__/__subclasses__/__bases__/__globals__/__builtins__`.
  A plugin that hits any of these is rejected at upload and never
  written to `/opt/ankavm/plugins/<id>/plugin.py`.
- **SEC-027 â€” Plugin route namespace enforcement (MEDIUM)**: Plugins are
  no longer handed the live Flask app object. Instead they receive
  `plugin_sdk._PluginAppProxy`, which only allows `app.route(...)` /
  `app.add_url_rule(...)` for paths under `/plugins/<plugin_id>/*`.
  A malicious or buggy plugin can no longer overwrite `/api/auth/login`
  or any other core route. All other Flask attributes are read-only
  forwarded so the existing plugin API remains usable.
- **SEC-025 â€” Bulk-delete confirm token nonce (MEDIUM)**: The bulk-delete
  confirm token is now a server-side random nonce (`secrets.token_urlsafe(24)`)
  bound to the exact sorted VM-id set via HMAC-SHA256, single-use,
  five-minute expiry, and constant-time compared. The old
  `sha256(sorted_ids)[:16]` token was deterministic and brute-forceable
  offline.
- **SEC-026 â€” Per-VM bulk audit (MEDIUM)**: Bulk deletions now write
  one append-only audit line per VM to
  `/var/lib/ankavm/bulk_audit.jsonl` with `ts`, `op`, `vm_id`, `ok`,
  `message`, and `requester` fields. The single per-job summary in
  `bulk_jobs.json` is preserved for backwards compatibility, but
  per-VM traceability is now available for forensic review.
- **SEC-028 â€” confidential_vm CPUID read (LOW)**: `confidential_vm.detect_support`
  reads `/proc/cpuinfo` directly via `pathlib.Path.read_text` instead of
  spawning `cat /proc/cpuinfo` through a subprocess. Removes one
  unnecessary external command from the hot path.

The following patches were issued in the 2.6.1 release:

- SEC-001: API keys are read from `/etc/ankavm/ankavm.conf` (mode 0600)
  instead of process environment variables.
- SEC-002: WebSocket authentication tokens are no longer passed in the URL
  query string; they are sent in the first frame after connect.
- SEC-003: JWT revocation list is consulted on every request, not only at
  refresh time.
- SEC-004: Audit log entries are hash-chained with SHA-256 so deletion or
  reordering is detectable.
- SEC-005: Login timing is equalized between unknown user and incorrect
  password to prevent user enumeration.
- SEC-006: Console session recordings are stored in a directory with mode
  0700, owned by the `ankavm` user.
- SEC-007: Storage endpoints resolve paths with `os.path.realpath` and
  reject any path outside the configured root.
- SEC-008: All state-changing endpoints require a double-submit CSRF token.

---

## Hardening Backlog (v2.8)

The 2.7 CI pipeline blocks **new** Bandit HIGH findings. The following
pre-existing items are tracked, explicitly skipped in CI for now, and will
be addressed in 2.8. They are visible in `--skip B202,B321,B324,B402,B507`
on the security audit job.

| ID    | Where                          | Status | Plan                                                                                |
|-------|--------------------------------|--------|-------------------------------------------------------------------------------------|
| B202  | archive extract paths in app.py | Open  | Add path-normalising filter (`tarfile.data_filter`) + reject absolute/`..` members. |
| B321  | `ftplib.FTP()` in backup_scheduler | Open | Move legacy FTP backup target behind `feature flag = off` and warn loudly.          |
| B324  | RFC 6455 WebSocket handshake    | Won't fix | SHA1 is mandated by the protocol; not a security choice.                         |
| B402  | `import ftplib` in backup_scheduler | Open | Removed together with B321.                                                       |
| B507  | `paramiko.AutoAddPolicy()`      | Open  | Add known-hosts pinning to the ankavm credential vault + first-contact prompt.      |
| dep-audit | pip-audit on requirements.txt | Open | Run informationally; bump pinned deps when an advisory has a clean upgrade path. Artifact uploaded every CI run. |

When an item lands, drop its skip from `.github/workflows/ci.yml`.

## Hardening Recommendations

See the "Security" section of the `README.md` for the recommended
configuration of nginx, sudo, file permissions, and operating system
hardening.

---

## Penetration Testing Scope

ankavm welcomes external penetration tests. The following are explicitly **in
scope**:

### In Scope

- Authentication: JWT signing, refresh-token flow, 2FA bypass, account lockout
  evasion, session fixation, OAuth2/SAML/OIDC binding attacks.
- Authorization: RBAC bypass, vertical/horizontal privilege escalation,
  cross-tenant data leakage in multi-tenant deployments.
- API: input validation, mass-assignment, IDOR on `/api/vms/*`, `/api/storage/*`,
  `/api/network/*`, SSRF in remote-fetch endpoints, RCE in webhook/plugin paths.
- Web panel: stored/reflected XSS, DOM clobbering, CSRF on state-changing
  endpoints (double-submit token), CSP bypass, prototype pollution.
- Console: noVNC token replay, WebSocket auth, VNC password leakage.
- Storage: path traversal in datastore browser, symlink attacks, ISO upload
  smuggling.
- Network: nftables/microsegmentation rule bypass, east-west traffic between
  tenants.
- Plugin sandbox: sandbox escape, audit-log forgery, malicious plugin upload
  flow (note: catalog is maintainer-curated; no public upload exists).
- Cryptographic: weak random, hardcoded secrets, LUKS2 key handling, vault
  unseal flow.
- Infrastructure: container escape on the controller host, hypervisor escape
  via QEMU/KVM device emulation, libvirt API privilege boundaries.

### Methodology Expectations

- Use rate-limited credential testing; do not flood the lockout system.
- Avoid destructive operations against production data. Use the demo
  environment at `pentest.ankavm.local` or your own self-hosted instance.
- Report multi-step exploit chains with PoC scripts (Python preferred).
- Provide CVSS v3.1 vector and a short remediation suggestion.

### Out of Scope

The following findings are not eligible for a security advisory:

- Denial of service against publicly available test instances.
- Missing security headers on `/docs` (Swagger UI) when the docs endpoint
  is enabled.
- Self-XSS that requires a user to paste content into their own browser
  console.
- Missing best-practice cookie flags on a development server running in
  debug mode.
- Reports generated solely by automated scanners without a working proof
  of concept.
- Issues in dependencies for which an upstream advisory already exists.
- CSP `unsafe-inline` for inline panel scripts (planned for nonce-based CSP
  in v2.8 â€” large refactor in progress).
- Social engineering against ankavm staff or community members.
- Physical attacks on hardware.

---

## Bounty Program

ankavm does not currently offer a paid bug bounty.

If a bounty program is established in a future release, it will be announced
on the project website and linked from this document.

---

## Contact

- Security email: `root@ankavm.local`
- General contact: `root@ankavm.local`
- GitHub: https://github.com/ShinnAsukha/ankavm-hypervisor






