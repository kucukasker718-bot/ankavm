#!/usr/bin/env python3
"""
ankavm Calamares Job Module
Reads globalStorage selections â†’ writes JSON config â†’ calls install.py --headless
"""

import os
import json
import subprocess
import tempfile

import libcalamares


CONFIG_PATH  = "/tmp/ankavm-install-config.json"
INSTALLER    = "/opt/ankavm-installer/install.py"
NETCFG_PATH  = "/tmp/oxnetwork.json"   # QML viewmodule tarafÄ±ndan yazÄ±lÄ±r
DISKCFG_PATH = "/tmp/ankavm-disk.json" # oxdisk QML viewmodule tarafÄ±ndan yazÄ±lÄ±r


def pretty_name():
    return "ankavm Hypervisor kurulumu"


def _gs_get(key, default=None):
    val = libcalamares.globalstorage.value(key)
    return val if val is not None else default


def _strip_partnum(dev):
    """'/dev/sda1' â†’ '/dev/sda', '/dev/nvme0n1p2' â†’ '/dev/nvme0n1', else unchanged."""
    import re
    if not dev:
        return dev
    # NVMe: /dev/nvme0n1p1 â†’ /dev/nvme0n1
    m = re.match(r"(/dev/nvme\d+n\d+)p\d+", dev)
    if m:
        return m.group(1)
    # SD/VD/HD: /dev/sda1 â†’ /dev/sda
    m = re.match(r"(/dev/[a-z]+)\d+", dev)
    if m:
        return m.group(1)
    return dev


def _detect_disk():
    """Multi-fallback disk detection from Calamares globalStorage + system."""
    import re

    # 1. partitions list â€” try multiple key names per partition object
    partitions = _gs_get("partitions", [])
    if partitions and isinstance(partitions, list):
        for p in partitions:
            if not isinstance(p, dict):
                continue
            for key in ("device", "devicePath", "path", "name"):
                dev = p.get(key, "")
                if dev and dev.startswith("/dev/"):
                    return _strip_partnum(dev)

    # 2. Direct globalStorage keys (Calamares version-dependent)
    for key in ("installDevice", "selectedDriveName", "targetDevice",
                "installDisk", "selectedDevice", "device"):
        val = _gs_get(key, "")
        if not val:
            continue
        val = str(val)
        # Normalize: some Calamares versions store "sda" instead of "/dev/sda"
        if not val.startswith("/"):
            val = f"/dev/{val}"
        if val.startswith("/dev/"):
            return _strip_partnum(val)

    # 3. rootMountPoint â†’ findmnt â†’ backing device
    root_mp = _gs_get("rootMountPoint", "/mnt")
    try:
        out = subprocess.check_output(
            ["findmnt", "-n", "-o", "SOURCE", str(root_mp)],
            text=True, stderr=subprocess.DEVNULL).strip()
        if out and out.startswith("/dev/"):
            return _strip_partnum(out)
    except Exception:
        pass

    # 4. First non-removable disk visible to lsblk
    try:
        out = subprocess.check_output(
            ["lsblk", "-d", "-n", "-o", "NAME,TYPE,RM"],
            text=True, stderr=subprocess.DEVNULL)
        for ln in out.splitlines():
            parts = ln.split()
            if len(parts) >= 3 and parts[1] == "disk" and parts[2] == "0":
                return f"/dev/{parts[0]}"
    except Exception:
        pass

    return ""


def _build_config():
    """Extract Calamares globalStorage values into install.py headless config."""

    # â”€â”€ Debug dump â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        # Log all globalStorage keys so we can diagnose issues
        gs_keys = libcalamares.globalstorage.keys() \
            if hasattr(libcalamares.globalstorage, "keys") else []
        libcalamares.utils.debug(
            f"ankavm_install: globalStorage keys = {list(gs_keys)}")
        for k in gs_keys:
            v = libcalamares.globalstorage.value(k)
            libcalamares.utils.debug(f"  gs[{k}] = {v!r}")
    except Exception as _e:
        libcalamares.utils.debug(f"ankavm_install: gs dump failed: {_e}")

    # â”€â”€ Disk: Ã¶nce oxdisk QML'nin yazdÄ±ÄŸÄ± dosyayÄ± dene â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    disk = ""
    if os.path.exists(DISKCFG_PATH):
        try:
            with open(DISKCFG_PATH) as _f:
                _dcfg = json.load(_f)
            disk = _dcfg.get("disk", "")
            if disk:
                libcalamares.utils.debug(f"ankavm_install: disk from oxdisk QML: {disk}")
        except Exception as _e:
            libcalamares.utils.debug(f"ankavm_install: diskcfg read error: {_e}")

    if not disk:
        disk = _detect_disk()  # fallback: kpmcore globalStorage + lsblk

    # â”€â”€ Locale / timezone â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    locale_conf = _gs_get("localeConf", {})
    locale   = locale_conf.get("LANG", "tr_TR.UTF-8") if isinstance(locale_conf, dict) else "tr_TR.UTF-8"
    timezone = _gs_get("locationRegion", "Europe") + "/" + _gs_get("locationZone", "Istanbul")

    # â”€â”€ Keyboard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    kb_layout  = _gs_get("keyboardLayout",  "tr")
    kb_variant = _gs_get("keyboardVariant", "")
    if isinstance(kb_layout, dict):
        kb_layout = kb_layout.get("key", "tr")

    # â”€â”€ Users â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    username = _gs_get("username", "oxadmin")
    password = _gs_get("password", "")
    if not password:
        password = _gs_get("userPassword", "")
    hostname = _gs_get("hostname", "ankavm-node")
    if not hostname:
        hostname = "ankavm-node"

    # â”€â”€ Network â€” QML viewmodule /tmp/oxnetwork.json veya globalStorage â”€â”€â”€â”€â”€
    net_mode = "dhcp"
    net_ip   = ""
    net_gw   = ""
    net_dns1 = "8.8.8.8"
    net_dns2 = "8.8.4.4"

    # 1. QML oxnetwork modÃ¼lÃ¼nÃ¼n yazdÄ±ÄŸÄ± dosyayÄ± oku
    if os.path.exists(NETCFG_PATH):
        try:
            with open(NETCFG_PATH) as _f:
                _net = json.load(_f)
            if _net.get("hostname"):
                hostname = _net["hostname"]
            net_mode = _net.get("mode", "dhcp")
            net_ip   = _net.get("ip",      "")
            net_gw   = _net.get("gateway",  "")
            net_dns1 = _net.get("dns1",     "8.8.8.8")
            net_dns2 = _net.get("dns2",     "8.8.4.4")
            libcalamares.utils.debug(f"ankavm_install: netcfg from QML file: {_net}")
        except Exception as _e:
            libcalamares.utils.debug(f"ankavm_install: netcfg file error: {_e}")

    # 2. globalStorage fallback (Python viewmodule olsaydÄ± buraya yazÄ±lÄ±rdÄ±)
    ox_host = _gs_get("oxnetwork_hostname", "")
    if ox_host:
        hostname = ox_host
    if _gs_get("oxnetwork_dhcp", None) is not None:
        net_mode = "dhcp" if _gs_get("oxnetwork_dhcp", True) else "static"
        net_ip   = _gs_get("oxnetwork_ip",   net_ip)
        net_gw   = _gs_get("oxnetwork_gw",   net_gw)
        net_dns1 = _gs_get("oxnetwork_dns1", net_dns1)
        net_dns2 = _gs_get("oxnetwork_dns2", net_dns2)

    cfg = {
        "disk":             disk,
        "hostname":         hostname,
        "username":         username,
        "password":         password,
        "net_mode":         net_mode,
        "keyboard_layout":  kb_layout,
        "keyboard_variant": kb_variant,
        "locale":           locale,
        "timezone":         timezone,
        "ssh_enabled":      True,
        "ssh_port":         22,
        "ssh_root":         False,
        "ssh_passwd_auth":  True,
    }
    if net_mode == "static" and net_ip:
        cfg["net_ip"]   = net_ip
        cfg["net_gw"]   = net_gw
        cfg["net_dns"]  = net_dns1
        cfg["net_dns2"] = net_dns2
    return cfg


def run():
    libcalamares.utils.debug("ankavm_install: baÅŸlÄ±yor")

    if not os.path.exists(INSTALLER):
        return (
            "Installer bulunamadÄ±",
            f"{INSTALLER} mevcut deÄŸil. ISO doÄŸru oluÅŸturuldu mu?",
        )

    cfg = _build_config()

    if not cfg["disk"]:
        return (
            "Disk seÃ§ilmedi",
            "Hedef disk tespit edilemedi. Partition sayfasÄ±na dÃ¶nÃ¼p diski seÃ§in.",
        )

    libcalamares.utils.debug(f"ankavm_install: config = {json.dumps(cfg, indent=2)}")

    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f)

    libcalamares.job.setprogress(0.01)

    try:
        proc = subprocess.Popen(
            ["python3", INSTALLER, "--headless", CONFIG_PATH],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            libcalamares.utils.debug(f"installer: {line}")
            try:
                data = json.loads(line)
                pct  = data.get("pct", 0)
                msg  = data.get("msg", "")
                if pct:
                    libcalamares.job.setprogress(max(0.01, min(0.99, pct / 100.0)))
                if msg:
                    libcalamares.utils.debug(f"progress {pct}%: {msg}")
                if data.get("error"):
                    return ("Kurulum hatasÄ±", data["error"])
                if data.get("done") and pct >= 100:
                    break
            except json.JSONDecodeError:
                libcalamares.utils.debug(f"installer stdout: {line}")

        proc.wait()
        if proc.returncode != 0:
            return (
                "Kurulum baÅŸarÄ±sÄ±z",
                f"install.py exit code {proc.returncode}. /tmp/calamares-install.log dosyasÄ±nÄ± kontrol edin.",
            )

    except Exception as exc:
        return ("Kurulum istisnasÄ±", str(exc))
    finally:
        try:
            os.unlink(CONFIG_PATH)
        except OSError:
            pass

    libcalamares.job.setprogress(1.0)
    return None






