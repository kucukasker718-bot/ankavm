# Contributing to ankavm

Thanks for considering a contribution. This document describes how to report
bugs, suggest features, and submit patches.

ankavm is maintained by a small team. We try to respond to issues within a few
days, but there is no service level agreement on open source contributions.

---

## Reporting a Bug

Open an issue at https://github.com/ShinnAsukha/ankavm-hypervisor/issues.

Before opening, please:

1. Search existing issues to avoid duplicates.
2. Run `sudo /opt/ankavm/repair.sh --diagnose` and attach the output. The
   diagnostic bundle contains version, kernel, libvirt status, recent log
   lines, and configuration hashes. It does not include secrets.
3. Include exact steps to reproduce, the expected result, and the actual
   result.
4. Include OS, kernel version, and ANKAVM version (`ankavm --version`).

If the bug is a security vulnerability, do not open a public issue. Follow the
process in `SECURITY.md`.

---

## Suggesting a Feature

Open an issue with the `enhancement` label and describe:

- The problem you are trying to solve.
- Why existing features are insufficient.
- A rough sketch of the proposed solution.

Please open the issue and discuss before writing code. We may have constraints
or related work that affect the design. Pull requests for features that have
not been discussed may be closed without review.

---

## Development Setup

Tested on Ubuntu 22.04 LTS. Debian 12 also works. Other distributions are not
supported for development.

### System packages

```
sudo apt update
sudo apt install -y \
    python3 python3-venv python3-dev \
    libvirt-dev libvirt-daemon-system \
    qemu-kvm qemu-utils \
    build-essential pkg-config
```

### Python environment

```
git clone https://github.com/ShinnAsukha/ankavm-hypervisor.git
cd ankavm-hypervisor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Running the development server

```
export ANKAVM_CONFIG=./dev-config.yaml
python3 backend/main.py
```

The server listens on `127.0.0.1:5000`. The dev config disables some
production checks (HSTS, secure cookies) so it works over plain HTTP on
localhost. Do not use the dev config in production.

---

## Running Tests

```
pytest tests/
```

Tests do not require a real libvirt daemon. The `mock_libvirt` fixture
patches the libvirt module so tests run on any developer machine.

For coverage:

```
pytest --cov=backend tests/
```

A coverage report under 70% on touched files will block a pull request.

---

## Code Style

- PEP 8 with a maximum line length of 130 characters.
- Use `ruff` for linting and `black` for formatting (configured in
  `pyproject.toml`).
- Prefer explicit over clever. A new contributor should be able to read the
  diff and understand it.
- No new third-party dependencies without prior discussion in an issue.

Run before pushing:

```
ruff check backend/ tests/
black --check backend/ tests/
```

---

## Commit Message Format

We use Conventional Commits.

```
<type>(<optional scope>): <short summary>

<optional body>

<optional footer>
```

Allowed types:

- `feat` - a new feature visible to users
- `fix` - a bug fix
- `docs` - documentation only
- `chore` - tooling, build, dependency bumps
- `refactor` - no behavior change
- `test` - test additions or fixes
- `security` - security-relevant changes; reference the SEC-xxx id in the body
- `perf` - performance improvement

Example:

```
fix(scheduler): avoid double placement when two requests race

The scheduler now holds a row-level lock on the candidate host before
committing the placement decision.

Closes #1234
```

---

## Pull Request Checklist

Before opening a PR, confirm:

- [ ] `pytest tests/` passes locally.
- [ ] `ruff check` and `black --check` produce no findings.
- [ ] No new runtime dependency was added without prior discussion.
- [ ] Documentation under `docs/` is updated if behavior changed.
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]`.
- [ ] The PR description references the related issue.
- [ ] You have signed your commits if you want them attributed to you.

PRs are reviewed by at least one maintainer. We may request changes; this is
not a rejection.

---

## Code of Conduct

This project follows the Contributor Covenant 2.1.

In short:

- Be respectful. Disagreement is fine; personal attacks are not.
- Assume good faith from other contributors.
- Harassment of any kind is not tolerated.
- Maintainers may remove comments, commits, or contributors that violate
  these rules.

Full text: https://www.contributor-covenant.org/version/2/1/code_of_conduct/

Report code of conduct issues to `root@ankavm.local`.

---

## License and Contributor License Agreement

ANKAVM is released under the MIT License. By submitting a pull request you
agree that your contribution is licensed under the same terms.

We do not require a separate Contributor License Agreement (CLA). The MIT
license covers both inbound and outbound contributions.

---

## Getting Help

- GitHub Discussions:
  https://github.com/ShinnAsukha/ankavm-hypervisor/discussions
- Email (non-security): `root@ankavm.local`
- Security: `root@ankavm.local` (see `SECURITY.md`)

Please use Discussions for usage questions. Issues are for bugs and concrete
feature requests.






