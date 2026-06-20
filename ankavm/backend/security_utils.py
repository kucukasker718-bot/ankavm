"""
ankavm Shared Security Validators (v2.7.1 SEC-017..023)
─────────────────────────────────────────────────────────
Reusable helpers shared by federation, runbook executor, blueprints.

- validate_external_url(): scheme+host allowlist, SSRF guard
- validate_vm_id():       canonical libvirt domain name pattern
- validate_forward_path(): allowed forward paths for federation proxy
- safe_subprocess_arg(): deny shell metacharacters in argv

Used to plug:
  SEC-017  Runbook api_call SSRF (CRITICAL)
  SEC-018  Runbook vm_action argv injection (CRITICAL)
  SEC-019  Federation member URL SSRF (HIGH)
  SEC-020  Federation forward path allowlist (MEDIUM)
  SEC-021  Federation add_member URL validation (MEDIUM)
"""
from __future__ import annotations
import ipaddress
import re
from urllib.parse import urlparse

# Strict libvirt domain name pattern — letters, digits, dot, dash, underscore.
# Excludes whitespace, semicolons, pipes, ampersands, quotes, dollar signs,
# backticks, backslashes — anything a shell would interpret.
_VM_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")

# Allowed paths for federation forward(). Member RBAC + audit log enforce
# the action. Auth/setup/internal admin paths are denied.
_FORWARD_PATH_PREFIXES = (
    "/api/vms",
    "/api/hosts",
    "/api/alerts",
    "/api/networks",
    "/api/storage",
    "/api/monitoring",
    "/api/health",
)

# Private / loopback / link-local / reserved CIDR blocks blocked for external
# fetch unless explicit allow_loopback=True is passed.
_PRIVATE_NETS_V4 = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local + cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT
]
_PRIVATE_NETS_V6 = [
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),         # ULA
    ipaddress.ip_network("fe80::/10"),        # link-local
    ipaddress.ip_network("fd00:ec2::/32"),    # IPv6 cloud metadata
]


class SecurityValidationError(ValueError):
    """Raised when a request is rejected by security_utils."""


def validate_vm_id(vm_id: str) -> str:
    """Return the vm_id if it matches the strict pattern, else raise."""
    if not isinstance(vm_id, str) or not _VM_ID_RE.match(vm_id):
        raise SecurityValidationError(
            "invalid vm_id: must match ^[A-Za-z0-9._-]{1,128}$"
        )
    return vm_id


def _ip_is_private(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        for net in _PRIVATE_NETS_V4:
            if ip in net:
                return True
    else:
        for net in _PRIVATE_NETS_V6:
            if ip in net:
                return True
    return False


def validate_external_url(url: str, *, allow_loopback: bool = False,
                          allow_http: bool = False) -> str:
    """Validate URL for outbound federation/runbook api_call.

    - scheme must be https (or http if allow_http=True)
    - host must be present
    - host (if literal IP) must not be a private / loopback / link-local /
      metadata address unless allow_loopback=True

    Returns the normalized URL or raises SecurityValidationError.
    """
    if not isinstance(url, str) or not url.strip():
        raise SecurityValidationError("url must be a non-empty string")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("https", "http"):
        raise SecurityValidationError(
            f"url scheme must be https (got '{parsed.scheme}')"
        )
    if parsed.scheme == "http" and not allow_http:
        raise SecurityValidationError(
            "http:// not permitted for external calls — use https://"
        )
    if not parsed.hostname:
        raise SecurityValidationError("url has no hostname")
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        is_ip = False
    if is_ip and not allow_loopback and _ip_is_private(host):
        raise SecurityValidationError(
            f"refusing to call private/loopback/link-local address: {host}"
        )
    if not allow_loopback and host.lower() in ("localhost", "localhost.localdomain"):
        raise SecurityValidationError(
            f"refusing to call loopback hostname: {host}"
        )
    return parsed.geturl()


def validate_forward_path(path: str) -> str:
    """Return path if it's on the federation forward allowlist, else raise."""
    if not isinstance(path, str) or not path.startswith("/"):
        raise SecurityValidationError("forward path must start with '/'")
    blocked = ("/api/auth", "/api/setup", "/api/internal", "/api/admin",
               "/api/users", "/api/sessions", "/api/.well-known")
    for b in blocked:
        if path.startswith(b):
            raise SecurityValidationError(f"forward path '{b}*' is blocked")
    for prefix in _FORWARD_PATH_PREFIXES:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return path
    raise SecurityValidationError(
        f"forward path '{path}' not in allowlist {_FORWARD_PATH_PREFIXES}"
    )


# Shell metacharacters that should never appear in subprocess argv elements
# derived from user input — even when the caller uses argv form, presence of
# these characters in a single element is a strong injection signal.
_SHELL_META = set(";|&`$<>\n\r\t\\\"'\x00")


def safe_subprocess_arg(value: str) -> str:
    """Return value if it contains no shell metacharacters, else raise."""
    if not isinstance(value, str):
        raise SecurityValidationError("subprocess argument must be a string")
    for ch in value:
        if ch in _SHELL_META:
            raise SecurityValidationError(
                f"subprocess argument contains shell metacharacter: {ch!r}"
            )
    return value


# ─────────────────────────────────────────────────────────────────────────
# SEC-029: safe archive extraction (replaces unguarded extractall() calls)
# ─────────────────────────────────────────────────────────────────────────
import os as _os
import tarfile as _tarfile
import zipfile as _zipfile


def _is_within(target: str, root: str) -> bool:
    """Return True if `target` resolves inside `root` (no traversal)."""
    target_abs = _os.path.realpath(target)
    root_abs = _os.path.realpath(root)
    rel = _os.path.relpath(target_abs, root_abs)
    return not rel.startswith("..") and not _os.path.isabs(rel)


def safe_tar_extract(archive_path: str, dest_dir: str) -> int:
    """Extract a tar archive into dest_dir, rejecting any member that:
      * is an absolute path
      * contains a `..` parent reference
      * is a symlink or hardlink pointing outside dest_dir
      * is a special file (block / char device / FIFO)
    Returns the number of members extracted. Raises SecurityValidationError
    on the first violation; partial extraction is left in place for the
    caller to clean up.
    """
    _os.makedirs(dest_dir, exist_ok=True)
    count = 0
    with _tarfile.open(archive_path) as tf:
        for member in tf.getmembers():
            name = member.name
            if _os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
                raise SecurityValidationError(
                    f"tar member rejected (path traversal): {name!r}"
                )
            if member.isdev():
                raise SecurityValidationError(
                    f"tar member rejected (device file): {name!r}"
                )
            target = _os.path.join(dest_dir, name)
            if not _is_within(target, dest_dir):
                raise SecurityValidationError(
                    f"tar member rejected (escapes dest): {name!r}"
                )
            if member.issym() or member.islnk():
                link_target = _os.path.join(_os.path.dirname(target),
                                            member.linkname)
                if not _is_within(link_target, dest_dir):
                    raise SecurityValidationError(
                        f"tar member link target escapes dest: {name!r}"
                        f" -> {member.linkname!r}"
                    )
        # On Python >= 3.12, also apply tarfile's data_filter as a belt+braces
        # defense. The membership scan above already rejected everything
        # data_filter would, but the filter additionally strips setuid bits.
        try:
            tf.extractall(dest_dir, filter="data")  # type: ignore[arg-type]
        except TypeError:
            tf.extractall(dest_dir)  # Python < 3.12 fallback
        count = sum(1 for _ in tf.getmembers())
    return count


def safe_zip_extract(archive_path: str, dest_dir: str) -> int:
    """Extract a zip archive with the same path-traversal guarantees as
    safe_tar_extract."""
    _os.makedirs(dest_dir, exist_ok=True)
    count = 0
    with _zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if _os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
                raise SecurityValidationError(
                    f"zip member rejected (path traversal): {name!r}"
                )
            target = _os.path.join(dest_dir, name)
            if not _is_within(target, dest_dir):
                raise SecurityValidationError(
                    f"zip member rejected (escapes dest): {name!r}"
                )
            count += 1
        zf.extractall(dest_dir)
    return count


# ─────────────────────────────────────────────────────────────────────────
# SEC-030: DNS rebinding mitigation
# ─────────────────────────────────────────────────────────────────────────
import socket as _socket


def resolve_safe_host(host: str, *, allow_loopback: bool = False) -> str:
    """Resolve `host` to a single IP and verify it is not in any blocked
    range. The caller should then connect to that IP directly (bypassing the
    OS resolver) so a DNS rebinding attack cannot point the connection at a
    different IP between the resolve and the connect. Returns the IP string.
    """
    try:
        infos = _socket.getaddrinfo(host, None,
                                    type=_socket.SOCK_STREAM)
    except _socket.gaierror as e:
        raise SecurityValidationError(f"DNS resolution failed: {e}")
    if not infos:
        raise SecurityValidationError(f"no DNS records for {host!r}")
    ip = infos[0][4][0]
    if not allow_loopback and _ip_is_private(ip):
        raise SecurityValidationError(
            f"refusing to connect to private/loopback address {ip} "
            f"resolved from {host!r}"
        )
    return ip






