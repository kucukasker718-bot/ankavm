#!/usr/bin/env python3
"""
ankavm XDP Network Filter Loader
Attaches xdp_filter.o to each VM tap interface (vnetX).
Usage:
  python3 xdp_loader.py attach vnet0   # attach filter
  python3 xdp_loader.py detach vnet0   # detach filter
  python3 xdp_loader.py list            # show attached interfaces
  python3 xdp_loader.py attach-all     # attach to all vnet* interfaces
  python3 xdp_loader.py detach-all     # remove from all vnet* interfaces
Requires: iproute2 (ip link), xdp_filter.o compiled from xdp_filter.c
"""
import subprocess
import sys
import os
import json
import glob

XDP_OBJ = os.path.join(os.path.dirname(__file__), "xdp_filter.o")
STATE_FILE = "/var/lib/ankavm/xdp_state.json"


def _run(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{r.stderr}")
    return r.stdout.strip()


def attach(iface: str) -> bool:
    if not os.path.exists(XDP_OBJ):
        print(f"[ERROR] {XDP_OBJ} not found — compile with: clang -O2 -g -target bpf -c xdp_filter.c -o xdp_filter.o")
        return False
    try:
        _run(["ip", "link", "set", "dev", iface, "xdpgeneric", "obj", XDP_OBJ, "sec", "xdp"])
        _save_state(iface, True)
        print(f"[OK] XDP filter attached to {iface}")
        return True
    except RuntimeError as e:
        print(f"[WARN] {e}")
        return False


def detach(iface: str) -> bool:
    try:
        _run(["ip", "link", "set", "dev", iface, "xdpgeneric", "off"])
        _save_state(iface, False)
        print(f"[OK] XDP filter detached from {iface}")
        return True
    except RuntimeError as e:
        print(f"[WARN] {e}")
        return False


def list_interfaces():
    try:
        out = _run(["ip", "-j", "link", "show"], check=False)
        ifaces = json.loads(out) if out else []
        for iface in ifaces:
            name = iface.get("ifname", "")
            xdp  = iface.get("xdp", {})
            if name.startswith("vnet") or xdp:
                status = "XDP attached" if xdp else "no XDP"
                print(f"  {name:20s} {status}")
    except Exception as e:
        print(f"[WARN] {e}")


def _vnet_interfaces():
    try:
        out = _run(["ip", "-j", "link", "show"], check=False)
        ifaces = json.loads(out) if out else []
        return [i["ifname"] for i in ifaces if i.get("ifname","").startswith("vnet")]
    except Exception:
        return []


def _save_state(iface: str, attached: bool):
    state = {}
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                state = json.load(f)
    except Exception:
        pass
    state[iface] = attached
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "attach" and len(sys.argv) >= 3:
        attach(sys.argv[2])
    elif cmd == "detach" and len(sys.argv) >= 3:
        detach(sys.argv[2])
    elif cmd == "list":
        list_interfaces()
    elif cmd == "attach-all":
        ifaces = _vnet_interfaces()
        if not ifaces:
            print("[INFO] No vnet* interfaces found")
        for iface in ifaces:
            attach(iface)
    elif cmd == "detach-all":
        ifaces = _vnet_interfaces()
        for iface in ifaces:
            detach(iface)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()






