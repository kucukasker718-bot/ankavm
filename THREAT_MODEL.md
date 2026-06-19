# Threat Model

Threat model v1.0 - applies to ankavm 2.6.x.

This document describes the security threat model for the ankavm Hypervisor management
stack using the STRIDE methodology. It is written for operators deploying ankavm in a
small to medium environment, and for contributors reviewing security-sensitive code.

The threat model is not a security guarantee. It enumerates threats we have considered
and the mitigations currently in place. Threats we have not yet addressed are listed
under "Known unmitigated risks".

---

## 1. Scope and Assumptions

### In scope

- A single ankavm host running Ubuntu 22.04 LTS or Debian 12.
- Hypervisor stack: libvirt + KVM/QEMU.
- A single Flask process (uWSGI or built-in development server) listening on the
  loopback interface, fronted by nginx as a reverse proxy with TLS termination.
- The web UI served from the same Flask process.
- The local audit log at `/var/lib/ankavm/audit.log`.
- Local state directory `/var/lib/ankavm/` and configuration in `/etc/ankavm/`.

### Out of scope

- Physical access to the host. An attacker with physical access can read disks,
  attach a debugger, or extract memory. We do not defend against this.
- A malicious administrator with root on the host. Root can read every secret,
  modify every binary, and forge any audit entry.
- Supply chain attacks against the git repository, PyPI, or the Debian/Ubuntu
  package archives. We assume upstream packages are not malicious.
- Side-channel attacks on the CPU (Spectre, Meltdown, MDS). Operators must apply
  microcode updates from their distribution.

### Assumptions

- The host kernel is patched within 30 days of upstream advisories.
- nginx is configured with TLS 1.2 or higher and a current cipher suite.
- The Flask process runs as an unprivileged user (`ankavm`) and uses `sudo` with a
  narrow allowlist for libvirt and disk operations.
- Operators rotate JWT secrets at install time and store them in
  `/etc/ankavm/ankavm.conf` with mode 0600.

---

## 2. Trust Boundaries

```
[ Browser ]
     |  HTTPS, TLS 1.2+
     v
[ nginx ]  <-- trust boundary 1: external network to host
     |  HTTP loopback
     v
[ Flask process (user: ankavm) ]  <-- trust boundary 2: web layer to backend
     |  Unix socket / sudo
     v
[ libvirtd, qemu, host shell ]  <-- trust boundary 3: backend to privileged ops
     |
     v
[ VM disks, snapshots, host filesystem ]
```

Each arrow crosses a trust boundary. Input crossing a boundary is validated on the
receiving side; secrets do not cross outward except where required.

---

## 3. Assets

| Asset | Location | Sensitivity |
|-------|----------|-------------|
| VM disk images | `/var/lib/libvirt/images/` | High - contain guest data |
| VM snapshots | `/var/lib/libvirt/qemu/snapshot/` | High |
| API keys for cloud providers | `/etc/ankavm/ankavm.conf` | High |
| JWT signing secret | `/etc/ankavm/ankavm.conf` | Critical |
| Audit log | `/var/lib/ankavm/audit.log` | High - integrity |
| Session cookies | Browser, server memory | Medium |
| User password hashes | `/var/lib/ankavm/users.json` | High |
| OAuth client secrets | `/etc/ankavm/ankavm.conf` | High |
| Backup encryption keys | `/etc/ankavm/backup.key` | Critical |

---

## 4. Threats by STRIDE Category

### 4.1 Spoofing

| ID | Threat | Mitigation |
|----|--------|------------|
| S-1 | Stolen JWT used to impersonate user | Short TTL (15 min access, 8 h refresh); refresh rotation; revocation list checked on each request |
| S-2 | Token replay after logout | Server-side blocklist of revoked jti claims (SEC-003) |
| S-3 | OAuth state parameter forgery (CSRF on callback) | 32-byte random state stored in session, validated on callback |
| S-4 | Phishing of operator credentials | TOTP MFA available; SAML/OIDC SSO supported; no mitigation against social engineering itself |
| S-5 | Spoofed source IP in audit log | Audit log records the IP nginx reports via `X-Forwarded-For`; trust nginx only |

### 4.2 Tampering

| ID | Threat | Mitigation |
|----|--------|------------|
| T-1 | VM disk image modified outside libvirt | Disks owned by `libvirt-qemu`, mode 0600; operators advised to enable LUKS |
| T-2 | Audit chain broken by deletion of entries | Hash-chained audit log: each entry contains SHA-256 of previous (SEC-004); break is detectable, not preventable |
| T-3 | Configuration file modified by attacker with shell access | File mode 0600, owned by root; integrity check on startup compares hash to last-known-good |
| T-4 | Plugin tampering | Plugins must be signed; signature verified on load (2.6.1+) |
| T-5 | In-flight tampering of API requests | TLS termination at nginx; HSTS recommended |

### 4.3 Repudiation

| ID | Threat | Mitigation |
|----|--------|------------|
| R-1 | Operator denies performing a destructive action | All state-changing endpoints write to the audit log with user id, IP, timestamp, request body hash |
| R-2 | Audit log entry missing because the process crashed mid-write | Audit writes are line-buffered and `fsync`'d before the API returns success |
| R-3 | Log injection via attacker-controlled fields (e.g. VM name with newline) | Audit entries are JSON; control characters in values are escaped |
| R-4 | Clock skew makes audit timestamps unreliable | Operators required to run NTP; documented in install guide |

### 4.4 Information Disclosure

| ID | Threat | Mitigation |
|----|--------|------------|
| I-1 | API keys stored in plaintext in environment | Moved to file-based config with 0600 mode; environment fallback warned at startup (SEC-001) |
| I-2 | WebSocket auth token passed in URL query string | Tokens are now passed in the first frame after connect; URL only carries a one-time handshake nonce (SEC-002) |
| I-3 | Error messages leak file paths or stack traces | Production mode disables Flask debugger and returns generic 500 with a correlation id |
| I-4 | Directory listing on `/static/` | nginx config disables autoindex |
| I-5 | Timing oracle on login | Constant-time comparison for password verification; user lookup time padded (SEC-005) |
| I-6 | Console screenshots in recording directory readable by other users | Recording directory mode 0700, owned by `ankavm` user (SEC-006) |

References to SEC-001 through SEC-008 are tracked in `SECURITY.md`.

### 4.5 Denial of Service

| ID | Threat | Mitigation |
|----|--------|------------|
| D-1 | WebSocket connection flood exhausts file descriptors | Per-IP connection limit (default 10) and per-user limit (default 5); nginx `limit_conn` recommended |
| D-2 | A libvirt call hangs the Flask worker | All libvirt calls are wrapped with a 30-second timeout; on timeout the worker returns 504 |
| D-3 | Large multipart upload exhausts disk | nginx `client_max_body_size` capped at 8 GiB; Flask checks Content-Length before reading |
| D-4 | Brute force of login endpoint | Rate limit 5 attempts per minute per IP and per username; exponential backoff |
| D-5 | Zip bomb in ISO upload | ISOs are not extracted server-side; metadata read via `isoinfo` with size cap |
| D-6 | Memory exhaustion in metrics endpoint | Time-series queries paginated; default range capped at 24 h |

### 4.6 Elevation of Privilege

| ID | Threat | Mitigation |
|----|--------|------------|
| E-1 | Privilege escalation via setuid binaries | The ankavm install does not add any setuid binaries; `sudo` rules are restricted to a fixed allowlist in `/etc/sudoers.d/ankavm` |
| E-2 | Container escape from a Firecracker microVM | microVMs run with seccomp, drop capabilities, and use a dedicated user namespace; relies on Firecracker upstream for jailer correctness |
| E-3 | Command injection via VM name | Names validated against `^[A-Za-z0-9._-]{1,64}$` before being passed to any shell |
| E-4 | Path traversal in storage endpoints | All file paths resolved with `os.path.realpath` and checked against an allowed root prefix (SEC-007) |
| E-5 | CSRF allowing an authenticated admin to be tricked into destructive POST | Double-submit cookie + SameSite=Lax on session cookie (SEC-008) |
| E-6 | SSRF via remote ISO URL fetch | URL fetcher blocks RFC 1918, link-local, and metadata IPs; follows max 3 redirects |

---

## 5. Known Unmitigated Risks

These are risks we are aware of but have not yet mitigated. They are tracked in the
issue tracker and will be addressed in future releases.

1. **No hardware-backed key storage by default.** The JWT secret and OAuth client
   secrets sit on disk in plain text protected only by filesystem permissions. A
   PKCS#11 / TPM-backed option exists for the audit chain root but not for general
   secrets.

2. **No per-VM encryption-at-rest by default.** Operators must opt in to LUKS on
   the storage pool. A VM created on an unencrypted pool is readable by anyone
   with root on the host.

3. **No anomaly detection on the audit stream.** The audit log is integrity-checked
   but is not analyzed for unusual patterns. An attacker with valid credentials
   can perform destructive actions and the operator must notice manually.

4. **WebSocket origin check is advisory.** We validate the `Origin` header against
   a configured allowlist, but browsers running with `--disable-web-security` or
   non-browser clients can forge it. Combined with the auth token requirement
   this is defense in depth, not a primary control.

5. **No formal review of the plugin sandbox.** Plugins run in the same Python
   process as the API. Plugin signature verification proves authorship, not
   safety. Untrusted plugins should not be installed.

---

## 6. Change History

| Version | Date | Notes |
|---------|------|-------|
| 1.0 | 2026-06-06 | Initial threat model, covers ankavm 2.6.x |

This document will be revised when a new minor version introduces a new trust
boundary, a new asset class, or a change to the mitigations listed above.






