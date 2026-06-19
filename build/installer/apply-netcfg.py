#!/usr/bin/env python3
"""
ankavm â€” apply-netcfg.py
Kurulumdan sonra aÄŸ yapÄ±landÄ±rmasÄ±nÄ± kurulu sisteme uygular.
KullanÄ±m: apply-netcfg.py <config.json> [mount_point]
"""
import sys, json, os, subprocess, re

CFG_PATH   = sys.argv[1] if len(sys.argv) > 1 else "/tmp/oxnetwork.json"
MOUNT_HINT = sys.argv[2] if len(sys.argv) > 2 else ""

INSTALL_CFG = "/tmp/ankavm-install-config.json"


def find_root_mount():
    """Kurulu sistemin root partisyonunun mount noktasÄ±nÄ± bul."""
    # 1. Verilen mount point
    if MOUNT_HINT and os.path.isdir(MOUNT_HINT):
        return MOUNT_HINT

    # 2. /mnt veya /mnt/target kontrol et
    for mp in ("/mnt/target", "/mnt"):
        if os.path.isdir(mp) and os.path.isfile(f"{mp}/etc/os-release"):
            return mp

    # 3. ankavm-install-config.json'dan disk bul, mount et
    if os.path.exists(INSTALL_CFG):
        try:
            with open(INSTALL_CFG) as f:
                cfg = json.load(f)
            disk = cfg.get("disk", "")
            if disk:
                return _mount_disk(disk)
        except Exception as e:
            print(f"[WARN] install config okunamadÄ±: {e}")

    # 4. lsblk ile ilk disk root partisyonunu bul
    try:
        out = subprocess.check_output(
            ["lsblk", "-o", "NAME,TYPE,MOUNTPOINT", "-J"],
            text=True, stderr=subprocess.DEVNULL)
        data = json.loads(out)
        for dev in data.get("blockdevices", []):
            if dev.get("type") == "disk":
                disk = f"/dev/{dev['name']}"
                return _mount_disk(disk)
    except Exception:
        pass

    return ""


def _mount_disk(disk):
    """Disk'in root partisyonunu /mnt/oxinstalled'a mount et."""
    mp = "/mnt/oxinstalled"
    os.makedirs(mp, exist_ok=True)

    # Partition adaylarÄ±: disk + 2 (EFI=1, root=2) veya disk + 1
    for suffix in ("2", "p2", "1", "p1"):
        part = disk + suffix
        if not os.path.exists(part):
            continue
        r = subprocess.run(["mount", part, mp],
                           capture_output=True, timeout=10)
        if r.returncode == 0:
            # GeÃ§erli bir Linux root mu?
            if os.path.isfile(f"{mp}/etc/os-release"):
                print(f"[OK] {part} â†’ {mp}")
                return mp
            subprocess.run(["umount", mp], capture_output=True)
    return ""


def write_interfaces(mp, cfg):
    """Debian /etc/network/interfaces yaz."""
    iface    = cfg.get("interface", "eth0")
    hostname = cfg.get("hostname",  "ankavm-node")
    mode     = cfg.get("mode",      "dhcp")

    # Hostname
    try:
        with open(f"{mp}/etc/hostname", "w") as f:
            f.write(hostname + "\n")
        print(f"[OK] hostname = {hostname}")
    except Exception as e:
        print(f"[WARN] hostname yazÄ±lamadÄ±: {e}")

    # /etc/hosts gÃ¼ncelle
    hosts_path = f"{mp}/etc/hosts"
    try:
        content = open(hosts_path).read() if os.path.exists(hosts_path) else ""
        # Eski hostname satÄ±rÄ±nÄ± gÃ¼ncelle
        new_line = f"127.0.1.1\t{hostname}\n"
        if "127.0.1.1" in content:
            content = re.sub(r"127\.0\.1\.1\s+\S+.*\n", new_line, content)
        else:
            content += new_line
        with open(hosts_path, "w") as f:
            f.write(content)
    except Exception as e:
        print(f"[WARN] /etc/hosts yazÄ±lamadÄ±: {e}")

    # /etc/network/interfaces
    ifaces_path = f"{mp}/etc/network/interfaces"
    if mode == "dhcp":
        content = (
            "# ankavm auto-generated\n"
            "source /etc/network/interfaces.d/*\n\n"
            "auto lo\n"
            "iface lo inet loopback\n\n"
            f"auto {iface}\n"
            f"iface {iface} inet dhcp\n"
        )
    else:
        ip   = cfg.get("ip",      "")
        mask = cfg.get("netmask", "255.255.255.0")
        gw   = cfg.get("gateway", "")
        dns1 = cfg.get("dns1",    "8.8.8.8")
        dns2 = cfg.get("dns2",    "8.8.4.4")
        # CIDR hesapla
        cidr = sum(bin(int(x)).count("1") for x in mask.split("."))
        content = (
            "# ankavm auto-generated\n"
            "source /etc/network/interfaces.d/*\n\n"
            "auto lo\n"
            "iface lo inet loopback\n\n"
            f"auto {iface}\n"
            f"iface {iface} inet static\n"
            f"    address {ip}/{cidr}\n"
        )
        if gw:
            content += f"    gateway {gw}\n"
        content += f"    dns-nameservers {dns1} {dns2}\n"

    try:
        with open(ifaces_path, "w") as f:
            f.write(content)
        print(f"[OK] /etc/network/interfaces yazÄ±ldÄ± ({mode})")
    except Exception as e:
        print(f"[WARN] interfaces yazÄ±lamadÄ±: {e}")

    # resolv.conf
    dns1 = cfg.get("dns1", "8.8.8.8")
    dns2 = cfg.get("dns2", "8.8.4.4")
    try:
        with open(f"{mp}/etc/resolv.conf", "w") as f:
            f.write(f"nameserver {dns1}\nnameserver {dns2}\n")
        print(f"[OK] resolv.conf = {dns1}, {dns2}")
    except Exception as e:
        print(f"[WARN] resolv.conf yazÄ±lamadÄ±: {e}")


def main():
    print(f"[*] apply-netcfg: {CFG_PATH}")

    if not os.path.exists(CFG_PATH):
        print(f"[ERR] Config bulunamadÄ±: {CFG_PATH}")
        sys.exit(1)

    with open(CFG_PATH) as f:
        cfg = json.load(f)
    print(f"[*] Config: {json.dumps(cfg, indent=2)}")

    mp = find_root_mount()
    if not mp:
        print("[ERR] Kurulu sistem mount edilemedi â€” aÄŸ ayarÄ± uygulanamadÄ±")
        sys.exit(1)

    print(f"[*] Mount point: {mp}")
    write_interfaces(mp, cfg)

    # GeÃ§ici mount ise unmount et
    if mp == "/mnt/oxinstalled":
        subprocess.run(["umount", mp], capture_output=True)
        print("[OK] Unmount edildi")

    print("[OK] AÄŸ yapÄ±landÄ±rmasÄ± tamamlandÄ±")


if __name__ == "__main__":
    main()






