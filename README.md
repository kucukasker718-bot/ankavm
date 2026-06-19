<div align="center">

<img src="https://ankavm.local/sadeceikon.png" alt="ANKAVM" width="120" />

# ANKAVM Hypervisor

### The open-source KVM/QEMU hypervisor with vCenter-class management.

<br>

[![License: MIT](https://img.shields.io/badge/License-MIT-22c55e.svg?style=for-the-badge)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.8.0--rc1-0091da.svg?style=for-the-badge)](https://github.com/ShinnAsukha/ankavm-hypervisor/releases)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2.svg?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/c6yHhKrQs5)
[![Get ANKAVM](https://img.shields.io/badge/â¬‡ï¸_Get_ANKAVM-Free-ff6b1a.svg?style=for-the-badge)](https://github.com/ShinnAsukha/ankavm-hypervisor/releases)

<br>

![GitHub stars](https://img.shields.io/github/stars/ShinnAsukha/ankavm-hypervisor?style=social)
![GitHub forks](https://img.shields.io/github/forks/ShinnAsukha/ankavm-hypervisor?style=social)
![GitHub watchers](https://img.shields.io/github/watchers/ShinnAsukha/ankavm-hypervisor?style=social)

[![CI](https://img.shields.io/github/actions/workflow/status/ShinnAsukha/ankavm-hypervisor/ci.yml?branch=main&label=CI&logo=github)](https://github.com/ShinnAsukha/ankavm-hypervisor/actions)
[![Last commit](https://img.shields.io/github/last-commit/ShinnAsukha/ankavm-hypervisor?logo=github)](https://github.com/ShinnAsukha/ankavm-hypervisor/commits/main)
[![Downloads](https://img.shields.io/github/downloads/ShinnAsukha/ankavm-hypervisor/total?logo=github)](https://github.com/ShinnAsukha/ankavm-hypervisor/releases)
[![Contributors](https://img.shields.io/github/contributors/ShinnAsukha/ankavm-hypervisor?logo=github)](https://github.com/ShinnAsukha/ankavm-hypervisor/graphs/contributors)
[![Open issues](https://img.shields.io/github/issues/ShinnAsukha/ankavm-hypervisor?logo=github)](https://github.com/ShinnAsukha/ankavm-hypervisor/issues)
[![Closed PRs](https://img.shields.io/github/issues-pr-closed/ShinnAsukha/ankavm-hypervisor?logo=github)](https://github.com/ShinnAsukha/ankavm-hypervisor/pulls?q=is%3Apr+is%3Aclosed)

[![Platform](https://img.shields.io/badge/platform-Ubuntu_22.04+_|_Debian_12+-orange.svg)]()
[![Hypervisor](https://img.shields.io/badge/hypervisor-KVM%2FQEMU-red.svg)]()
[![Languages](https://img.shields.io/badge/i18n-TR_â€¢_EN_â€¢_ES_â€¢_DE_â€¢_ZH_â€¢_FR-0091da.svg)]()
[![Confidential VMs](https://img.shields.io/badge/Confidential_VMs-SEV_â€¢_TDX_â€¢_vTPM-7c3aed.svg)]()
[![Audit-Ready](https://img.shields.io/badge/Compliance-SOC2_â€¢_ISO27001_â€¢_PCI_â€¢_HIPAA-22c55e.svg)]()

<br>

[**ğŸŒ Website**](https://ankavm.local) Â·
[**ğŸ“š Documentation**](https://ankavm.local/docs/) Â·
[**ğŸ’° Pricing**](https://ankavm.local/pricing/) Â·
[**ğŸ›’ Marketplace**](https://ankavm.local/marketplace/) Â·
[**ğŸ¤ Partners**](https://ankavm.local/partners/) Â·
[**ğŸ“ Certification**](https://ankavm.local/certification/) Â·
[**ğŸ› Bug Bounty**](https://ankavm.local/security/bug-bounty/) Â·
[**ğŸ“¡ Status**](https://ankavm.local/status/)

</div>

---

> **ANKAVM replaces VMware vSphere â€” without the licence.**
> Confidential VMs (SEV/TDX) Â· DRS Â· HA Â· live migration Â· cluster federation Â· 6-language web UI Â· SOC 2 in progress Â· MIT licensed Â· **save 90%+ vs vSphere.**

---

## â­ Why ankavm?

| | ankavm | VMware vSphere | Proxmox VE |
|---|:---:|:---:|:---:|
| Open source (MIT) | âœ… | âŒ | âœ… (GPL) |
| Per-CPU socket tax | âŒ none | ğŸ’¸ yes | âŒ none |
| Confidential VMs (SEV/TDX) | âœ… | âœ… | partial |
| vTPM 2.0 per VM | âœ… | âœ… | partial |
| Cluster federation API | âœ… v2 | âœ… vCenter | âŒ |
| Live migration | âœ… | âœ… | âœ… |
| Runbook auto-remediation | âœ… | partial | âŒ |
| GitOps (ArgoCD/Flux) | âœ… | âŒ | âŒ |
| Kubernetes CSI driver | âœ… | âœ… | community |
| KubeVirt bridge | âœ… | âŒ | âŒ |
| Built-in compliance scanner | âœ… | partial | âŒ |
| **3-year cost (32 cores, 50 VMs)** | **~$2,250** | ~$200,000 | ~$5,000 |

---

## ğŸš€ Quick Install

```bash
curl -sSL https://ankavm.local/install.sh | sudo bash
```

> Ubuntu 22.04+ / Debian 12+ â€¢ x86_64 with VT-x or AMD-V â€¢ 4 GB RAM minimum
> Installation takes ~3 minutes. Panel listens on `https://<host-ip>:8006`.

**Prefer not to pipe curl into bash?**

```bash
git clone https://github.com/ShinnAsukha/ankavm-hypervisor.git /opt/ankavm-src
cd /opt/ankavm-src
sudo bash install.sh
```

---

## ğŸ“¦ What's in the box

<table>
<tr>
<td width="50%" valign="top">

### ğŸ–¥ï¸ VMs & lifecycle
- Create / start / stop / pause / clone / snapshot / migrate
- Disk hot-extend, SMART, qcow2 + raw
- noVNC + SPICE + xterm.js console
- Import: OVA / OVF / VMDK / VHD / VHDX / raw
- Cloud-init first-boot
- Live migration between ankavm nodes
- Bulk operations w/ HMAC-bound confirm tokens

### ğŸŒ Networking
- libvirt bridges, NAT, isolated, routed
- IPAM with CIDR pools + DHCP static leases
- Per-VM nftables firewall, port-forward DNAT
- HAProxy + WireGuard helpers
- BGP peering (FRR), DNS manager
- Subnet calculator
- v2.7.2 SSRF guards on every outbound call

### ğŸ’¾ Storage
- qcow2, LVM, NFS, Ceph (community), MinIO/S3
- Snapshots: live + scheduled + app-consistent
- 3-2-1 backup automation, mount + boot verify
- SFTP, MinIO, S3 backup targets
- Cross-site disk replication
- **Kubernetes CSI driver** (v2.7.2)

</td>
<td width="50%" valign="top">

### ğŸ” Security
- RBAC: administrator / operator / viewer / vm-user
- TOTP 2FA + single-use recovery codes
- SAML 2.0 + OIDC SSO (Okta, Entra, Google, Keycloak)
- OAuth2 one-click presets (v2.7.2)
- LDAP / AD with group-to-role mapping
- API keys with scopes
- Hash-chained audit log (SHA-256)
- SSH known-hosts + first-contact approval (v2.7.2)
- **Bug bounty**: $50â€“$5000 per finding

### ğŸ›¡ï¸ Confidential computing
- AMD SEV / SEV-ES / SEV-SNP
- Intel TDX
- vTPM 2.0 per VM
- UEFI Secure Boot
- Launch attestation report capture

### ğŸ¤– AI + automation
- **OXY** â€” natural-language ops copilot
- Anomaly detector (z-score per metric)
- Auto-remediation runbooks (notify / shell / api_call / vm_action)
- Capacity forecasting
- Right-sizing recommendations
- **GitOps manager** (ArgoCD/Flux dirs)

### ğŸŒ Cloud-native (v2.7.2)
- Kubernetes **CSI driver**
- **KubeVirt** bridge
- **Firecracker** microVM runtime (<125 ms boot)
- **PWA offline mode** (read-only fallback)
- **CycloneDX SBOM** per release

</td>
</tr>
</table>

---

## ğŸŒ Six interface languages

Full parity, 2400+ entries per language. CI gate blocks any merge that introduces an untranslated Turkish string.

ğŸ‡¹ğŸ‡· TÃ¼rkÃ§e Â· ğŸ‡¬ğŸ‡§ English Â· ğŸ‡ªğŸ‡¸ EspaÃ±ol Â· ğŸ‡©ğŸ‡ª Deutsch Â· ğŸ‡¨ğŸ‡³ ä¸­æ–‡ Â· ğŸ‡«ğŸ‡· FranÃ§ais

---

## ğŸ› ï¸ Tech stack

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  Web UI (HTML/JS, no build step)        REST API + WebSocket â”‚
â”‚         â†•                                       â†•            â”‚
â”‚                    Flask 3.x backend                          â”‚
â”‚         â†•                                       â†•            â”‚
â”‚   libvirt / QEMU              nftables / iptables             â”‚
â”‚         â†•                                                     â”‚
â”‚   KVM (Linux kernel)                                          â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

- **Backend** â€” Python 3.11+, Flask, Flask-SocketIO, libvirt-python
- **Frontend** â€” Single-page HTML + vanilla JS (no React/Vue/Webpack)
- **Reverse proxy** â€” nginx + Let's Encrypt
- **Process supervision** â€” systemd
- **Storage** â€” qcow2 default, plus LVM / ZFS / Ceph / NFS / MinIO / S3
- **Networking** â€” libvirt bridges, nftables firewall, optional Open vSwitch

---

## ğŸ“š Resources

| Where | What |
|---|---|
| [**ankavm.local**](https://ankavm.local) | Marketing site + live demo + cost calculator |
| [**ankavm.local/docs/**](https://ankavm.local/docs/) | Full installation + admin guide |
| [**ankavm.local/pricing/**](https://ankavm.local/pricing/) | Pricing â€” Standard $35/mo Â· Pro $250/yr Â· Lifetime $2000 |
| [**ankavm.local/marketplace/**](https://ankavm.local/marketplace/) | Curated plugin + template registry |
| [**ankavm.local/partners/**](https://ankavm.local/partners/) | Reseller program â€” 30% recurring commission |
| [**ankavm.local/certification/**](https://ankavm.local/certification/) | ankavm Certified Administrator ($99 exam) |
| [**ankavm.local/compliance/**](https://ankavm.local/compliance/) | SOC 2 / ISO 27001 / CIS / NIST / PCI / HIPAA |
| [**ankavm.local/status/**](https://ankavm.local/status/) | Live SaaS uptime + incident history |
| [**ankavm.local/security/bug-bounty/**](https://ankavm.local/security/bug-bounty/) | Bug bounty program (up to $5,000 / bug) |
| [**Discord**](https://discord.gg/c6yHhKrQs5) | Community chat â€” questions, plugin showcase, alpha-test announcements |
| [**SECURITY.md**](SECURITY.md) | Vulnerability disclosure policy + SEC-001..033 history |
| [**CHANGELOG.md**](CHANGELOG.md) | Per-release feature + security changelog |
| [**MODULARIZATION_PLAN.md**](MODULARIZATION_PLAN.md) | v2.8 app.py â†’ blueprints migration plan |
| [**CONTRIBUTING.md**](CONTRIBUTING.md) | Dev setup + PR guidelines + commit format |

---

## âš¡ What's new in v2.8.0-rc1

**Modularization seed:** app.py split into 5 domain blueprints. New `/api/v2/` endpoints under `auth`, `vms`, `networks`, `storage`, `monitoring`. Legacy `/api/*` untouched. See [`MODULARIZATION_PLAN.md`](MODULARIZATION_PLAN.md).

## âš¡ What shipped in v2.7.2

**Security (SEC-029..033)** â€” Safe archive extraction, DNS rebinding mitigation, FTP backup deprecated, SSH known-hosts + first-contact approval, Bandit + pip-audit in CI.

**8 new feature modules** â€” Kubernetes CSI driver, KubeVirt bridge, GitOps manager, Firecracker microVM runtime, OAuth2 provider presets, audit-log retention policy, CycloneDX SBOM generator, PWA offline mode.

**i18n parity** â€” French (FR) added; 6 languages with CI gate.

See [`CHANGELOG.md`](CHANGELOG.md) for the full list.

---

## ğŸ›¡ï¸ Security

ankavm ships with `security_utils.py` carrying validated helpers for SSRF blocking (`validate_external_url`), shell argv injection guards (`validate_vm_id`, `safe_subprocess_arg`), safe archive extraction (`safe_tar_extract`, `safe_zip_extract`), and DNS rebinding mitigation (`resolve_safe_host`).

**33 SEC-tracked patches** to date (SEC-001 through SEC-033) across auth, federation, runbook executor, plugin SDK, and bulk operations. Full history in [`SECURITY.md`](SECURITY.md).

**Found a vulnerability?** Report via [GitHub Security Advisories](https://github.com/ShinnAsukha/ankavm-hypervisor/security/advisories/new) or email `root@ankavm.local`. Bounties up to **$5,000 / bug** â€” see the [Bug Bounty program](https://ankavm.local/security/bug-bounty/).

---

## âš™ï¸ API

```bash
# Get a JWT token
curl -k -X POST https://host:8006/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"yourpass"}'

# Use it
curl -k https://host:8006/api/vms -H "Authorization: Bearer $TOKEN"
```

Swagger UI lives at `https://<host>:8006/api/docs`. Full OpenAPI 3 spec at `/api/openapi`. **~290 endpoints** across VM management, networking, storage, RBAC, monitoring, CSI, KubeVirt, GitOps, Firecracker, runbooks, federation, OAuth2, SBOM, PWA, and the new v2.8 `/api/v2/*` blueprint routes.

A [Terraform provider](terraform-provider-ankavm/) ships with `ankavm_vm`, `ankavm_network`, `ankavm_storage_pool` resources.

---

## ğŸ¤ Contributing

PRs welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) first:

- Run `make i18n-check` before pushing if you touched `index.html`
- Run `make security` to fire Bandit + pip-audit
- Run `make test` â€” the SEC-017..033 regression suite must stay green
- New features need an entry in `CHANGELOG.md`
- Don't add new routes to `app.py` â€” use a blueprint under `ankavm/backend/blueprints/`. See [`MODULARIZATION_PLAN.md`](MODULARIZATION_PLAN.md).

By the way â€” a quick **â­ star** is the cheapest way to say thanks and helps ankavm appear in GitHub trending. It takes a second.

---

## ğŸ“ˆ Star history

[![Star History Chart](https://api.star-history.com/svg?repos=ShinnAsukha/ankavm-hypervisor&type=Date)](https://star-history.com/#ShinnAsukha/ankavm-hypervisor&Date)

---

## ğŸ’¬ Community

- **Discord** â€” [discord.gg/c6yHhKrQs5](https://discord.gg/c6yHhKrQs5)
- **GitHub Discussions** â€” [github.com/ShinnAsukha/ankavm-hypervisor/discussions](https://github.com/ShinnAsukha/ankavm-hypervisor/discussions)
- **Issues** â€” [github.com/ShinnAsukha/ankavm-hypervisor/issues](https://github.com/ShinnAsukha/ankavm-hypervisor/issues)
- **Security** â€” [GitHub Security Advisories](https://github.com/ShinnAsukha/ankavm-hypervisor/security/advisories/new) or `root@ankavm.local`

---

## ğŸ“„ Licence

ankavm is released under the [MIT License](LICENSE). Use it commercially, fork it, embed it, sell support around it â€” go ahead. Just keep the copyright notice.

A **Pro / Lifetime** plan unlocks priority issue triage, all v2.x updates, and partner perks. Source remains MIT regardless. See [pricing](https://ankavm.local/pricing/) for details. Pricing is symbolic; the code is and will remain free.

---

<div align="center">

**Built with â¤ï¸ for operators who think VMware should not charge per CPU socket.**

[â­ Star this repo](https://github.com/ShinnAsukha/ankavm-hypervisor) Â·
[ğŸ’¬ Join Discord](https://discord.gg/c6yHhKrQs5) Â·
[â¬‡ï¸ Get ankavm](https://github.com/ShinnAsukha/ankavm-hypervisor/releases) Â·
[ğŸŒ ankavm.local](https://ankavm.local)

</div>






