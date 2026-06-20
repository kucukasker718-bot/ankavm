<div align="center">

<br/>

<!-- Logo Placeholder -->
<img src="https://ankavm.local/sadeceikon.png" alt="ANKAVM Logo" width="110"/>

<br/>
<br/>

# ANKAVM Hypervisor

### Enterprise-Grade Open-Source KVM/QEMU Virtualization Platform

<br/>

[![License: MIT](https://img.shields.io/badge/License-MIT-22c55e.svg?style=for-the-badge)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.8.0--rc1-0091da.svg?style=for-the-badge)](https://github.com/ShinnAsukha/ankavm-hypervisor/releases)
[![Discord](https://img.shields.io/badge/Discord-Community-5865F2.svg?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/c6yHhKrQs5)
[![Download](https://img.shields.io/badge/⬇_Get_ANKAVM-Free-ff6b1a.svg?style=for-the-badge)](https://github.com/ShinnAsukha/ankavm-hypervisor/releases)

<br/>

![Stars](https://img.shields.io/github/stars/ShinnAsukha/ankavm-hypervisor?style=social)
![Forks](https://img.shields.io/github/forks/ShinnAsukha/ankavm-hypervisor?style=social)
![Watchers](https://img.shields.io/github/watchers/ShinnAsukha/ankavm-hypervisor?style=social)

[![CI](https://img.shields.io/github/actions/workflow/status/ShinnAsukha/ankavm-hypervisor/ci.yml?branch=main&label=CI&logo=github)](https://github.com/ShinnAsukha/ankavm-hypervisor/actions)
[![Last Commit](https://img.shields.io/github/last-commit/ShinnAsukha/ankavm-hypervisor?logo=github)](https://github.com/ShinnAsukha/ankavm-hypervisor/commits/main)
[![Downloads](https://img.shields.io/github/downloads/ShinnAsukha/ankavm-hypervisor/total?logo=github)](https://github.com/ShinnAsukha/ankavm-hypervisor/releases)
[![Contributors](https://img.shields.io/github/contributors/ShinnAsukha/ankavm-hypervisor?logo=github)](https://github.com/ShinnAsukha/ankavm-hypervisor/graphs/contributors)
[![Issues](https://img.shields.io/github/issues/ShinnAsukha/ankavm-hypervisor?logo=github)](https://github.com/ShinnAsukha/ankavm-hypervisor/issues)
[![Closed PRs](https://img.shields.io/github/issues-pr-closed/ShinnAsukha/ankavm-hypervisor?logo=github)](https://github.com/ShinnAsukha/ankavm-hypervisor/pulls?q=is%3Apr+is%3Aclosed)

[![Platform](https://img.shields.io/badge/platform-Ubuntu_22.04+_|_Debian_12+-orange.svg)]()
[![Hypervisor](https://img.shields.io/badge/hypervisor-KVM%2FQEMU-red.svg)]()
[![Languages](https://img.shields.io/badge/i18n-TR_•_EN_•_ES_•_DE_•_ZH_•_FR-0091da.svg)]()
[![Confidential VMs](https://img.shields.io/badge/Confidential_VMs-SEV_•_TDX_•_vTPM-7c3aed.svg)]()
[![Compliance](https://img.shields.io/badge/Compliance-SOC2_•_ISO27001_•_PCI_•_HIPAA-22c55e.svg)]()
[![Endpoints](https://img.shields.io/badge/REST_API-290+_Endpoints-blue.svg)]()
[![Security](https://img.shields.io/badge/Security_Patches-SEC--001..033-critical.svg)]()

<br/>

[🌐 Website](https://ankavm.local) ·
[📚 Documentation](https://ankavm.local/docs/) ·
[💰 Pricing](https://ankavm.local/pricing/) ·
[🛒 Marketplace](https://ankavm.local/marketplace/) ·
[🤝 Partners](https://ankavm.local/partners/) ·
[📝 Certification](https://ankavm.local/certification/) ·
[🐛 Bug Bounty](https://ankavm.local/security/bug-bounty/) ·
[📡 Status](https://ankavm.local/status/)

<br/>

</div>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Why ANKAVM?](#-why-ankavm)
- [Feature Matrix](#-feature-matrix)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [System Requirements](#-system-requirements)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [REST API](#-rest-api)
- [Security](#-security)
- [Compliance & Audit](#-compliance--audit)
- [Infrastructure as Code](#-infrastructure-as-code)
- [Internationalization](#-internationalization)
- [Release Notes](#-release-notes)
- [Contributing](#-contributing)
- [Community](#-community)
- [Resources](#-resources)
- [License](#-license)

---

## 🔍 Overview

**ANKAVM** is a production-ready, open-source hypervisor management platform built on **KVM/QEMU**, delivering enterprise virtualization capabilities without the licensing costs of proprietary solutions. Designed for infrastructure teams that need reliability, security, and extensibility at scale.

> ANKAVM replaces VMware vSphere — without the licence.
> Confidential VMs (AMD SEV / Intel TDX) · DRS · HA · live migration · cluster federation · 6-language web UI · SOC 2 in progress · MIT licensed · **save 90%+ vs vSphere.**

ANKAVM provides a unified control plane spanning:

- **Virtual Machine Lifecycle** — full create/clone/snapshot/migrate/import workflows
- **Confidential Computing** — hardware-rooted memory encryption via AMD SEV and Intel TDX
- **Cloud-Native Integration** — Kubernetes CSI driver, KubeVirt bridge, GitOps, Firecracker microVMs
- **Enterprise Security** — RBAC, SSO (SAML/OIDC/OAuth2), 2FA, hash-chained audit logs, 33 patched CVEs
- **AI-Driven Operations** — OXY copilot, anomaly detection, capacity forecasting, auto-remediation runbooks
- **Multi-Site Federation** — cluster federation with live migration across ANKAVM nodes
- **Compliance** — built-in scanner for CIS, STIG, SOC 2, ISO 27001, PCI-DSS, HIPAA profiles

---

## ⭐ Why ANKAVM?

| Capability | ANKAVM | VMware vSphere | Proxmox VE |
|:---|:---:|:---:|:---:|
| Open source (MIT) | ✅ | ❌ | ✅ (GPL) |
| Per-CPU socket licensing | ❌ none | 💸 yes | ❌ none |
| Confidential VMs (SEV / TDX) | ✅ | ✅ | partial |
| vTPM 2.0 per VM | ✅ | ✅ | partial |
| Cluster federation API | ✅ v2 | ✅ vCenter | ❌ |
| Live migration | ✅ | ✅ | ✅ |
| Runbook auto-remediation | ✅ | partial | ❌ |
| GitOps (ArgoCD / Flux) | ✅ | ❌ | ❌ |
| Kubernetes CSI driver | ✅ | ✅ | community |
| KubeVirt bridge | ✅ | ❌ | ❌ |
| Firecracker microVM runtime | ✅ | ❌ | ❌ |
| Built-in compliance scanner | ✅ | partial | ❌ |
| AI ops copilot (OXY) | ✅ | ❌ | ❌ |
| Plugin SDK + Marketplace | ✅ | ❌ | ❌ |
| Multi-language UI (6 langs) | ✅ | limited | ❌ |
| **3-year total cost (32 cores, 50 VMs)** | **~$2,250** | **~$200,000** | **~$5,000** |

---

## 📦 Feature Matrix

<table>
<tr>
<td width="50%" valign="top">

### 🖥️ Virtual Machine Lifecycle
- Create / start / stop / pause / reboot / destroy
- Clone, linked clone, template promotion
- Live snapshot + scheduled snapshots + app-consistent (QEMU guest agent)
- Disk hot-extend for running VMs; SMART monitoring
- Image formats: qcow2, raw, VMDK, VHD, VHDX
- Import: OVA / OVF / VMDK / VHD / VHDX / raw
- Cloud-init first-boot provisioning
- Live migration between ANKAVM nodes
- Boot order management; HugePages per VM
- Bulk operations with HMAC-bound confirm tokens
- OS-aware icon display (Ubuntu, Debian, RHEL, Windows, FreeBSD…)

### 🌐 Networking
- libvirt bridges, NAT, isolated, routed network modes
- IPAM with CIDR pools + DHCP static leases
- Per-VM nftables firewall + port-forward DNAT
- VLAN management, Open vSwitch (OVS) support
- HAProxy load-balancer integration
- WireGuard VPN helpers
- BGP peering via FRR, DNS manager
- Microsegmentation per workload tag
- BFD uplink detection, service chaining (L4–L7)
- Service mesh (Istio sidecar injection for VMs)
- Network I/O Control (NIOC) shares and limits
- Subnet calculator; SSRF guards on every outbound call

### 💾 Storage
- qcow2 (default), LVM, ZFS, NFS, Ceph (community), MinIO/S3
- Live + scheduled + application-consistent snapshots
- 3-2-1 backup automation with restore-and-boot verification
- Backup targets: SFTP, MinIO, S3
- Continuous Data Protection (CDP) — 15-second RPO
- Cross-site disk replication
- Storage DRS for datastore balancing
- **Kubernetes CSI driver** — ANKAVM storage as PersistentVolumes

### ⚡ Performance & Availability
- Distributed Resource Scheduler (DRS) with affinity/anti-affinity rules
- Enhanced vMotion Compatibility (EVC) baselines per cluster
- NUMA-aware VM placement
- SR-IOV passthrough configuration
- vGPU support (NVIDIA vGPU, Intel GVT-g)
- Fault tolerance: lockstep VM mirroring across two hosts
- Maintenance mode with automatic VM evacuation
- Cluster-wide resource pools; per-tenant hard quotas

</td>
<td width="50%" valign="top">

### 🔐 Security & Identity
- RBAC: administrator / operator / viewer / vm-user roles
- TOTP 2FA + single-use recovery codes; MFA enforcement per role
- SAML 2.0 + OIDC SSO (Okta, Entra ID, Google, Keycloak, GitLab)
- OAuth2 one-click provider presets
- LDAP / Active Directory with group-to-role mapping
- API keys with granular scopes
- Hash-chained audit log (SHA-256, tamper-evident)
- SSH known-hosts management + first-contact approval queue
- Strict Content-Security-Policy headers
- Per-IP + per-username rate limiting on auth endpoints
- Data Loss Prevention (DLP) engine on file uploads
- Forensic export of VM memory and disk
- **Bug bounty**: $50–$5,000 per confirmed vulnerability

### 🛡️ Confidential Computing
- AMD SEV / SEV-ES / SEV-SNP memory encryption
- Intel TDX trusted domain execution
- vTPM 2.0 provisioned per VM
- UEFI Secure Boot enforcement
- Launch attestation report capture
- Live disk encryption (LUKS) for running VMs
- HashiCorp Vault integration for secret retrieval

### 🤖 AI & Automation
- **OXY** — natural-language infrastructure operations copilot
- Anomaly detector: z-score per metric with high-confidence thresholds
- Auto-remediation runbooks: notify / shell / api_call / vm_action steps
- ML-based capacity forecasting (90-day history)
- Right-sizing recommendations
- Predictive failure detection on SMART and performance data
- AI planner for multi-step provisioning workflows
- Configuration drift detection against a golden baseline

### ☁️ Cloud-Native
- **Kubernetes CSI driver** — volumes from ANKAVM storage pools
- **KubeVirt bridge** — lower VirtualMachineInstance specs to ANKAVM VMs
- **Kubernetes Operator** (`ankavm-operator`) + custom resources
- **Firecracker microVM** runtime — ~125 ms boot, ~5 MB overhead
- **Kata Containers** and WebAssembly (wasmtime) runtime drivers
- GitOps manager with ArgoCD / Flux directory conventions
- Cloud bursting to AWS and Azure for transient capacity
- Cloud export: AWS AMI, Azure VHD formats
- **CycloneDX SBOM** auto-generated per release
- **PWA offline mode** — read-only fallback when network is unavailable
- OpenTelemetry tracing on API + scheduler
- CloudEvents emitter for external automation
- Open Policy Agent (OPA) admission control

### 🖥️ Console & Client
- noVNC + SPICE + xterm.js in-browser console
- Console session recording with retention policy
- Electron desktop client (Linux, macOS, Windows)
- Bundled Grafana dashboards + topology view
- Self-service portal for tenant users
- Chargeback & showback reports; service catalog with approval workflow

</td>
</tr>
</table>

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ANKAVM Control Plane                                │
│                                                                             │
│   ┌───────────────────────┐         ┌─────────────────────────────────┐    │
│   │   Web UI (HTML/JS)    │         │   REST API + WebSocket (Flask)  │    │
│   │  (no build step/SPA)  │◄───────►│   ~290 endpoints · OpenAPI 3   │    │
│   └───────────────────────┘         └────────────┬────────────────────┘    │
│                                                   │                         │
│   ┌────────────────────────────────────────────────────────────────────┐   │
│   │                     Flask 3.x Backend                              │   │
│   │  app.py (monolith) + Blueprints (v2.8 modularization in progress)  │   │
│   │  ┌──────────┐ ┌────────┐ ┌──────────┐ ┌─────────┐ ┌───────────┐  │   │
│   │  │ v28_auth │ │v28_vms │ │v28_nets  │ │v28_stor │ │v28_monitor│  │   │
│   │  └──────────┘ └────────┘ └──────────┘ └─────────┘ └───────────┘  │   │
│   └──────────────────────────┬─────────────────────────────────────────┘   │
│                              │                                              │
│          ┌───────────────────┼────────────────────┐                        │
│          ▼                   ▼                    ▼                         │
│   ┌─────────────┐   ┌──────────────┐   ┌──────────────────┐               │
│   │libvirt/QEMU │   │ nftables/OVS │   │ Storage Backends │               │
│   └──────┬──────┘   └──────────────┘   │ qcow2/LVM/NFS/   │               │
│          │                             │ Ceph/MinIO/S3     │               │
│          ▼                             └──────────────────┘               │
│   ┌─────────────┐                                                          │
│   │ KVM (Linux) │  ← AMD SEV / Intel TDX / vTPM / Secure Boot             │
│   └─────────────┘                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
         │                         │                        │
         ▼                         ▼                        ▼
  ┌─────────────┐        ┌──────────────────┐     ┌────────────────┐
  │  Kubernetes │        │  Cluster         │     │  External      │
  │  CSI Driver │        │  Federation      │     │  Integrations  │
  │  KubeVirt   │        │  Multi-Site DR   │     │  Terraform     │
  │  GitOps     │        │  Live Migration  │     │  Pulumi / OPA  │
  └─────────────┘        └──────────────────┘     │  Vault / SIEM  │
                                                   └────────────────┘
```

### Technology Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11+, Flask 3.x, Flask-SocketIO, libvirt-python |
| **Frontend** | Vanilla HTML + JS — single-page, no React/Vue/Webpack build step |
| **Reverse Proxy** | nginx + Let's Encrypt (auto-provisioned) |
| **Process Supervision** | systemd |
| **Storage Engines** | qcow2 (default) · LVM · ZFS · Ceph · NFS · MinIO · S3 |
| **Networking** | libvirt bridges · nftables · Open vSwitch · WireGuard · FRR BGP |
| **Confidential Compute** | AMD SEV/SEV-ES/SEV-SNP · Intel TDX · vTPM 2.0 · UEFI Secure Boot |
| **Cloud-Native** | Kubernetes CSI · KubeVirt · Firecracker · Kata · GitOps (ArgoCD/Flux) |
| **Identity** | SAML 2.0 · OIDC · OAuth2 · LDAP/AD · TOTP 2FA |
| **Observability** | OpenTelemetry · Prometheus · Grafana (bundled dashboards) |
| **IaC** | Terraform provider · Pulumi provider · Ansible collection |
| **Security** | Bandit · pip-audit · CycloneDX SBOM · OPA |

---

## 🚀 Quick Start

### One-Line Install

```bash
curl -sSL https://ankavm.local/install.sh | sudo bash
```

> Installation completes in approximately 3 minutes.
> The management panel starts at `https://<host-ip>:8006`.

### Verify-Before-Run Install

```bash
git clone https://github.com/ShinnAsukha/ankavm-hypervisor.git /opt/ankavm-src
cd /opt/ankavm-src
sudo bash install.sh
```

---

## 💻 System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| **OS** | Ubuntu 22.04 LTS / Debian 12 | Ubuntu 24.04 LTS |
| **Architecture** | x86_64 with VT-x or AMD-V | x86_64 with AMD-V (for SEV) |
| **RAM** | 4 GB | 16 GB+ |
| **Disk** | 20 GB | 100 GB+ (SSD recommended) |
| **CPU** | 2 cores | 8+ cores |
| **Network** | 1 Gbps | 10 Gbps |
| **Kernel** | Linux 5.15+ | Linux 6.1+ (for SEV-SNP / TDX) |

**For Confidential Computing (AMD SEV / Intel TDX):**

```bash
# Check AMD SEV support
cat /proc/cpuinfo | grep -i sev

# Check Intel TDX support
cat /proc/cpuinfo | grep -i tdx

# Verify KVM availability
ls -la /dev/kvm
```

---

## ⚙️ Installation

### Automated Installer (`install.sh`)

The `install.sh` script handles the full stack:

1. Dependency installation (QEMU, libvirt, nginx, Python 3.11+)
2. Python virtual environment setup
3. nginx reverse proxy configuration with self-signed or Let's Encrypt TLS
4. systemd service registration and enablement
5. Kernel module validation (KVM, nftables)
6. AppArmor / seccomp profile installation (`kernel/` directory)
7. First-run admin credential generation

```bash
# Full install with default options
sudo bash install.sh

# Non-interactive install with custom port
sudo bash install.sh --port 8443 --no-tls

# Repair an existing installation
sudo bash repair.sh --diagnose

# Uninstall (preserves VM data by default)
sudo bash uninstall.sh
```

### Ansible Collection

```bash
ansible-galaxy collection install ./ansible-collection-ankavm
```

```yaml
# site.yml
- hosts: hypervisors
  collections:
    - ankavm.ankavm
  roles:
    - role: ankavm.ankavm.install
      vars:
        ankavm_port: 8006
        ankavm_tls: true
```

### Terraform Provider

```hcl
terraform {
  required_providers {
    ankavm = {
      source = "ankavm/ankavm"
    }
  }
}

provider "ankavm" {
  host     = "https://192.168.1.10:8006"
  username = "admin"
  password = var.ankavm_password
}

resource "ankavm_vm" "web_server" {
  name   = "web-01"
  vcpus  = 4
  memory = 8192
  disk   = 50

  network {
    bridge = "virbr0"
  }
}
```

### Post-Install Access

| Service | Default URL | Protocol |
|---|---|---|
| Web Panel | `https://<host-ip>:8006` | HTTPS |
| REST API | `https://<host-ip>:8006/api/` | HTTPS + JWT |
| WebSocket | `wss://<host-ip>:8006/socket.io/` | WSS |
| noVNC Console | `https://<host-ip>:8006/vnc/<vm-id>` | HTTPS |
| Swagger UI | `https://<host-ip>:8006/api/docs` | HTTPS |
| OpenAPI Spec | `https://<host-ip>:8006/api/openapi` | HTTPS |

---

## 🔧 Configuration

Key configuration paths after installation:

| Path | Purpose |
|---|---|
| `/etc/ankavm/config.json` | Main configuration file |
| `/var/lib/ankavm/` | VM disks, snapshots, audit logs |
| `/var/lib/ankavm/audit.jsonl` | Hash-chained audit log |
| `/var/lib/ankavm/bulk_audit.jsonl` | Bulk-operation audit trail |
| `/etc/nginx/sites-enabled/ankavm` | nginx reverse proxy config |
| `/etc/systemd/system/ankavm.service` | systemd unit file |
| `kernel/apparmor/` | AppArmor profiles |
| `kernel/seccomp/` | seccomp filter definitions |
| `kernel/ebpf/` | eBPF programs for network enforcement |

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ANKAVM_SECRET_KEY` | (auto-generated) | Flask session signing key |
| `ANKAVM_DATA_DIR` | `/var/lib/ankavm` | VM data root |
| `ANKAVM_PORT` | `8006` | Listening port |
| `ANKAVM_FEDERATION_ALLOW_INSECURE` | `0` | Allow non-TLS federation (dev only) |
| `ANKAVM_ENABLE_INSECURE_FTP` | `0` | Enable FTP backup target (discouraged) |

---

## 🔌 REST API

### Authentication

```bash
# Obtain a JWT token
curl -k -X POST https://host:8006/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "yourpass"}'

# Use the token
export TOKEN="<jwt-from-response>"
curl -k https://host:8006/api/vms \
  -H "Authorization: Bearer $TOKEN"
```

### Common Endpoints

```bash
# List all VMs
GET  /api/vms

# Create a VM
POST /api/vms

# VM state control
POST /api/vms/<id>/start
POST /api/vms/<id>/stop
POST /api/vms/<id>/pause

# Take a snapshot
POST /api/vms/<id>/snapshot

# List storage pools
GET  /api/storage/pools

# Network management
GET  /api/networks
POST /api/networks

# Cluster federation
GET  /api/federation/members
POST /api/federation/members/add

# Monitoring
GET  /api/monitoring/host
GET  /api/monitoring/alerts
```

### v2 Blueprint API (v2.8+)

```bash
# New versioned endpoints under /api/v2/
GET  /api/v2/auth/me
GET  /api/v2/vms
GET  /api/v2/vms/<id>
GET  /api/v2/networks
GET  /api/v2/storage/pools
GET  /api/v2/monitoring/system-health

# Kubernetes CSI
GET  /api/v2/csi/volumes

# KubeVirt
POST /api/v2/kubevirt/clusters

# GitOps
POST /api/v2/gitops/repos

# Firecracker microVMs
POST /api/v3/firecracker/vms
```

> **Interactive docs:** Swagger UI at `https://<host>:8006/api/docs`
> **Machine-readable spec:** OpenAPI 3 JSON at `https://<host>:8006/api/openapi`
> **~290 endpoints** across VM management, networking, storage, RBAC, monitoring, CSI, KubeVirt, GitOps, Firecracker, runbooks, federation, OAuth2, SBOM, and PWA.

---

## 🔐 Security

ANKAVM is built with security as a first-class concern. Key security properties:

### Defence-in-Depth

| Control | Implementation |
|---|---|
| **Input validation** | `security_utils.py` — shared validators for SSRF, shell injection, path traversal |
| **SSRF protection** | `validate_external_url` blocks RFC 1918, loopback, link-local, CGNAT, cloud metadata |
| **Archive extraction** | `safe_tar_extract` / `safe_zip_extract` — rejects path traversal and symlink escapes |
| **DNS rebinding** | `resolve_safe_host` — resolves once, validates, returns IP |
| **Runbook sandboxing** | Shell step restricted to allowlist; argv elements checked for metacharacters |
| **Bulk operations** | HMAC-SHA256 nonce bound to exact VM-id set, single-use, 5-minute expiry |
| **Plugin isolation** | AST validator blocks sandbox escapes; routes confined to `/plugins/<id>/*` |
| **Audit log integrity** | SHA-256 hash chain — each entry links to the previous |
| **Federation TLS** | `verify_tls=False` coerced to `True` unless `ANKAVM_FEDERATION_ALLOW_INSECURE=1` |
| **Auth rate limiting** | 20 requests / 60 seconds / source IP on login + 2FA endpoints |
| **CSP** | `default-src 'self'; form-action 'self'; frame-ancestors 'self'; object-src 'none'` |

### Security Patch History

**33 SEC-tracked patches** (SEC-001 through SEC-033) across:
- Authentication and session management (SEC-001–008)
- SSRF and injection (SEC-017–019, SEC-030)
- Federation and bulk operations (SEC-020–021, SEC-025–026)
- Runbook executor (SEC-022–023)
- Plugin SDK (SEC-024, SEC-027)
- Archive and FTP safety (SEC-028–029, SEC-031)
- SSH and supply-chain (SEC-032–033)

Full history: [`SECURITY.md`](SECURITY.md)

### Vulnerability Disclosure

Found a security issue?

1. **Report** via [GitHub Security Advisories](https://github.com/ShinnAsukha/ankavm-hypervisor/security/advisories/new) — preferred
2. **Email** `root@ankavm.local` for sensitive disclosures
3. **Bug bounty**: $50–$5,000 per confirmed finding — see [Bug Bounty program](https://ankavm.local/security/bug-bounty/)

We follow responsible disclosure and aim to ship a patch within **72 hours** for critical findings.

### Running Security Checks

```bash
# Run Bandit static analysis + pip-audit
make security

# Run full test suite including SEC regression tests (SEC-017..033)
make test

# Verify i18n completeness (CI gate)
make i18n-check

# Generate CycloneDX SBOM
make sbom
```

---

## 📋 Compliance & Audit

ANKAVM supports compliance workflows for multiple regulatory frameworks:

| Framework | Status | Notes |
|---|---|---|
| **SOC 2 Type II** | In progress | Hash-chained audit log, RBAC, 2FA, encryption at rest |
| **ISO 27001** | In progress | Risk management, access control, audit trail |
| **CIS Benchmarks** | ✅ Scanner built-in | VM-level and host-level CIS profiles |
| **STIG** | ✅ Scanner built-in | DoD STIG profiles for Linux VMs |
| **PCI-DSS** | Partial | Network segmentation, audit log, encryption |
| **HIPAA** | Partial | Encryption, access controls, audit trail |
| **NIST CSF** | Reference | Mapped in `SECURITY.md` |
| **GDPR** | Reference | Privacy policy at `ankavm.local/privacy` |

Full compliance documentation: [ankavm.local/compliance/](https://ankavm.local/compliance/)

---

## 🛠️ Infrastructure as Code

ANKAVM ships three first-party IaC integrations:

### Terraform Provider

```
terraform-provider-ankavm/
├── resources/
│   ├── ankavm_vm.go
│   ├── ankavm_network.go
│   └── ankavm_storage_pool.go
```

### Ansible Collection

```
ansible-collection-ankavm/
├── roles/
│   ├── install/
│   ├── configure/
│   └── harden/
```

### Pulumi Provider

```bash
pip install pulumi-ankavm
```

```python
import pulumi_ankavm as ankavm

vm = ankavm.Vm("web-01",
    vcpus=4,
    memory=8192,
    disk=50)
```

---

## 🌍 Internationalization

ANKAVM ships with **full UI parity** across 6 languages — 2,400+ translation entries each. A CI gate (`make i18n-check`) blocks merges that introduce untranslated Turkish strings.

| Language | Code | Status |
|---|:---:|---|
| 🇹🇷 Türkçe | `tr` | Source language |
| 🇬🇧 English | `en` | ✅ Full parity |
| 🇪🇸 Español | `es` | ✅ Full parity |
| 🇩🇪 Deutsch | `de` | ✅ Full parity |
| 🇨🇳 中文 | `zh` | ✅ Full parity |
| 🇫🇷 Français | `fr` | ✅ Added in v2.7.2 |

### i18n Toolchain

```bash
# Extract → scan → augment → inject
make i18n

# Verify no untranslated strings
make i18n-check

# Pre-commit hook (auto-runs on index.html changes)
# Installed at: .git-hooks/pre-commit
```

---

## 📰 Release Notes

### v2.8.0-rc1 — 2026-06-13 ⚡ Modularization Seed

**Highlights:** `app.py` split into 5 domain blueprints under `/api/v2/`.

- New `ankavm/backend/blueprints/` package with `v28_auth`, `v28_vms`, `v28_networks`, `v28_storage`, `v28_monitoring`
- 25 new endpoints total; legacy `/api/*` routes untouched for backward compatibility
- Each blueprint uses a late-bind dependency-injection contract — zero imports from `app.py`
- `MODULARIZATION_PLAN.md` published with per-domain target counts and migration rules
- `tests/test_blueprints_v28.py` smoke suite added

See [`MODULARIZATION_PLAN.md`](MODULARIZATION_PLAN.md) for the full v2.8 GA roadmap.

---

### v2.7.2 — 2026-06-12 🔒 Security + Cloud-Native

**Security (SEC-029..033):** Safe archive extraction, DNS rebinding mitigation, FTP backup deprecation, SSH known-hosts + first-contact approval, Bandit + pip-audit in CI.

**8 new feature modules:** Kubernetes CSI driver, KubeVirt bridge, GitOps manager, Firecracker microVM runtime, OAuth2 provider presets, audit-log retention policy, CycloneDX SBOM generator, PWA offline mode.

**i18n:** French (FR) added — 6 languages with CI gate.

---

### v2.7.1 — 2026-06-11 🛡️ Security Hardening Sprint

**17 security patches** (SEC-017..033): SSRF blocking on runbook `api_call`, argv injection guards on `vm_action`, federation member URL validation, path allowlisting, plugin SDK AST sandbox, bulk-delete HMAC nonce, `security_utils.py` module.

---

### v2.7.0 — 2026-06-10

Confidential VMs (SEV / SEV-ES / SEV-SNP / TDX / vTPM 2.0), anomaly auto-remediation runbooks, cluster federation v2, OXY AI copilot, Electron desktop client, plugin authoring wizard.

---

Full history: [`CHANGELOG.md`](CHANGELOG.md)

---

## 🤝 Contributing

Contributions are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a PR.

### Development Setup

```bash
git clone https://github.com/ShinnAsukha/ankavm-hypervisor.git
cd ankavm-hypervisor
python3 -m venv .venv
source .venv/bin/activate
pip install -r ankavm/backend/requirements.txt

# Install pre-commit hook
cp .git-hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

### Contribution Checklist

- [ ] Run `make i18n-check` before pushing any changes to `index.html`
- [ ] Run `make security` (Bandit + pip-audit must be clean)
- [ ] Run `make test` — SEC-017..033 regression suite must stay green
- [ ] Add a `CHANGELOG.md` entry for new features or security fixes
- [ ] **Do not add new routes to `app.py`** — use a blueprint under `ankavm/backend/blueprints/`
- [ ] Follow commit format documented in [`CONTRIBUTING.md`](CONTRIBUTING.md)

### Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating you agree to abide by its terms.

---

## 💬 Community

| Channel | Purpose |
|---|---|
| [**Discord**](https://discord.gg/c6yHhKrQs5) | Real-time chat — questions, plugin showcase, alpha announcements |
| [**GitHub Discussions**](https://github.com/ShinnAsukha/ankavm-hypervisor/discussions) | Long-form Q&A, plugin sharing, RFCs |
| [**GitHub Issues**](https://github.com/ShinnAsukha/ankavm-hypervisor/issues) | Bug reports and feature requests |
| [**Security Advisories**](https://github.com/ShinnAsukha/ankavm-hypervisor/security/advisories/new) | Responsible vulnerability disclosure |
| [**Email**](mailto:root@ankavm.local) | Private security disclosures |

---

## 📚 Resources

| Resource | Description |
|---|---|
| [ankavm.local](https://ankavm.local) | Marketing site · live demo · 3-year cost calculator |
| [ankavm.local/docs/](https://ankavm.local/docs/) | Full installation and administrator guide |
| [ankavm.local/pricing/](https://ankavm.local/pricing/) | Standard $35/mo · Pro $250/yr · Lifetime $2,000 |
| [ankavm.local/marketplace/](https://ankavm.local/marketplace/) | Curated plugin and VM template registry |
| [ankavm.local/partners/](https://ankavm.local/partners/) | Reseller program — 30% recurring commission |
| [ankavm.local/certification/](https://ankavm.local/certification/) | ANKAVM Certified Administrator ($99 exam) |
| [ankavm.local/compliance/](https://ankavm.local/compliance/) | SOC 2 · ISO 27001 · CIS · NIST · PCI · HIPAA |
| [ankavm.local/status/](https://ankavm.local/status/) | Live SaaS uptime · incident history |
| [ankavm.local/security/bug-bounty/](https://ankavm.local/security/bug-bounty/) | Bug bounty program (up to $5,000 / bug) |
| [SECURITY.md](SECURITY.md) | Vulnerability disclosure policy · SEC-001..033 patch history |
| [CHANGELOG.md](CHANGELOG.md) | Per-release feature and security changelog |
| [MODULARIZATION_PLAN.md](MODULARIZATION_PLAN.md) | v2.8 blueprint migration plan and route inventory |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Developer setup · PR guidelines · commit format |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Threat model · attack surface analysis |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Community standards |

---

## 📈 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=ShinnAsukha/ankavm-hypervisor&type=Date)](https://star-history.com/#ShinnAsukha/ankavm-hypervisor&Date)

---

## 📄 License

ANKAVM is released under the **[MIT License](LICENSE)**.

You are free to use it commercially, fork it, embed it, and sell support around it. The only requirement is to keep the copyright notice intact.

```
MIT License — Copyright (c) 2025–2026 ANKAVM Contributors
```

**Pro / Lifetime plans** unlock priority issue triage, all v2.x updates, and partner perks. The source code remains MIT regardless. See [pricing](https://ankavm.local/pricing/) for details.

---

<div align="center">

**Built with ❤️ for operators who believe enterprise infrastructure should be free.**

[⭐ Star this repo](https://github.com/ShinnAsukha/ankavm-hypervisor) ·
[💬 Join Discord](https://discord.gg/c6yHhKrQs5) ·
[⬇️ Get ANKAVM](https://github.com/ShinnAsukha/ankavm-hypervisor/releases) ·
[🌐 ankavm.local](https://ankavm.local)

</div>
