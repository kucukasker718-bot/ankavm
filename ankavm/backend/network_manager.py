import libvirt
import xml.etree.ElementTree as ET
import subprocess
import config

LIBVIRT_URI = config.LIBVIRT_URI


def _connect():
    return libvirt.open(LIBVIRT_URI)


def _safe_bridge_name(net):
    """Passthrough/macvtap ağlarda bridgeName() exception fırlatır — yakala."""
    try:
        return net.bridgeName() if net.isActive() else ""
    except Exception:
        return ""


def list_networks():
    conn = _connect()
    nets = []
    try:
        for net in conn.listAllNetworks():
            xml_str = net.XMLDesc()
            root = ET.fromstring(xml_str)

            forward = root.find("forward")
            ip_el = root.find("ip")
            dhcp_el = root.find(".//dhcp/range") if ip_el is not None else None

            nets.append({
                "uuid": net.UUIDString(),
                "name": net.name(),
                "active": bool(net.isActive()),
                "autostart": bool(net.autostart()),
                "bridge": _safe_bridge_name(net),
                "forward_mode": forward.get("mode", "nat") if forward is not None else "isolated",
                "ip": ip_el.get("address", "") if ip_el is not None else "",
                "netmask": ip_el.get("netmask", "") if ip_el is not None else "",
                "dhcp": {
                    "start": dhcp_el.get("start", "") if dhcp_el is not None else "",
                    "end": dhcp_el.get("end", "") if dhcp_el is not None else "",
                } if dhcp_el is not None else None,
            })
    finally:
        conn.close()
    return nets


def create_network(name, forward_mode="nat", bridge_name=None,
                   ip_address="192.168.100.1", netmask="255.255.255.0",
                   dhcp_start="192.168.100.100", dhcp_end="192.168.100.200",
                   bridge_iface=None):

    # Bridge / passthrough modu: fiziksel arayüzü doğrudan kullan
    # libvirt bridge modunda mevcut bir bridge aygıtı (br0 gibi) gerekir.
    # Fiziksel interface (ens160, enp1s0) için passthrough kullan — ayrı bridge kurmaya gerek yok.
    if forward_mode == "bridge":
        iface = bridge_iface or "enp1s0"
        xml = f"""<network>
  <name>{name}</name>
  <forward mode='passthrough'>
    <interface dev='{iface}'/>
  </forward>
</network>"""
        conn = _connect()
        try:
            net = conn.networkDefineXML(xml)
            net.setAutostart(1)
            net.create()
            return {"uuid": net.UUIDString(), "name": name, "status": "created", "mode": "passthrough"}
        finally:
            conn.close()

    if not bridge_name:
        bridge_name = f"virbr-{name[:8]}"

    forward_xml = ""
    if forward_mode in ("nat", "route"):
        forward_xml = f"<forward mode='{forward_mode}'/>"

    xml = f"""<network>
  <name>{name}</name>
  {forward_xml}
  <bridge name='{bridge_name}' stp='on' delay='0'/>
  <ip address='{ip_address}' netmask='{netmask}'>
    <dhcp>
      <range start='{dhcp_start}' end='{dhcp_end}'/>
    </dhcp>
  </ip>
</network>"""

    conn = _connect()
    try:
        net = conn.networkDefineXML(xml)
        net.setAutostart(1)
        net.create()
        return {"uuid": net.UUIDString(), "name": name, "status": "created"}
    finally:
        conn.close()


def delete_network(net_uuid):
    conn = _connect()
    try:
        try:
            net = conn.networkLookupByUUIDString(net_uuid)
        except libvirt.libvirtError:
            net = conn.networkLookupByName(net_uuid)

        if net.isActive():
            net.destroy()
        net.undefine()
        return {"status": "deleted"}
    finally:
        conn.close()


def start_network(net_uuid):
    conn = _connect()
    try:
        net = conn.networkLookupByUUIDString(net_uuid)
        net.create()
        return {"status": "started"}
    finally:
        conn.close()


def stop_network(net_uuid):
    conn = _connect()
    try:
        net = conn.networkLookupByUUIDString(net_uuid)
        net.destroy()
        return {"status": "stopped"}
    finally:
        conn.close()


def set_network_autostart(net_uuid, enabled: bool):
    conn = _connect()
    try:
        net = conn.networkLookupByUUIDString(net_uuid)
        net.setAutostart(1 if enabled else 0)
        return {"ok": True, "autostart": enabled}
    finally:
        conn.close()


def update_network(net_uuid: str, dhcp_start: str = None, dhcp_end: str = None,
                   ip_address: str = None, netmask: str = None) -> dict:
    """
    Edit a libvirt network's IP/DHCP config.
    Must stop → redefine → start because libvirt doesn't support live DHCP edits.
    Bridge/passthrough networks don't support IP/DHCP via libvirt XML — autostart only.
    """
    conn = _connect()
    try:
        net = conn.networkLookupByUUIDString(net_uuid)
        was_active = bool(net.isActive())
        was_autostart = bool(net.autostart())

        xml_str = net.XMLDesc(0)
        root = ET.fromstring(xml_str)

        # Detect bridge/passthrough — these networks have no <ip> element in libvirt XML
        fwd_el = root.find("forward")
        fwd_mode = fwd_el.get("mode", "nat") if fwd_el is not None else "nat"
        is_bridge = fwd_mode in ("bridge", "passthrough", "private", "vepa")

        if is_bridge:
            # Bridge networks: libvirt XML has no <ip> — can't configure gateway/DHCP here.
            # IP addressing is handled by physical network or ankavm IPAM pools.
            # Only save autostart (handled by caller via separate endpoint).
            return {
                "ok": True,
                "active": bool(net.isActive()),
                "autostart": bool(net.autostart()),
                "bridge_note": (
                    "Bu ağ bir köprü ağıdır. Gateway ve DHCP libvirt üzerinden "
                    "yapılandırılamaz. IPAM → IP Havuzu oluşturun ve bu ağı seçin."
                ),
            }

        ip_el = root.find("ip")
        if ip_el is not None:
            if ip_address:
                ip_el.set("address", ip_address)
            if netmask:
                ip_el.set("netmask", netmask)
            dhcp_el = ip_el.find("dhcp")
            if dhcp_el is not None:
                range_el = dhcp_el.find("range")
                if range_el is None:
                    range_el = ET.SubElement(dhcp_el, "range")
                if dhcp_start:
                    range_el.set("start", dhcp_start)
                if dhcp_end:
                    range_el.set("end", dhcp_end)
            elif dhcp_start and dhcp_end:
                dhcp_el = ET.SubElement(ip_el, "dhcp")
                range_el = ET.SubElement(dhcp_el, "range")
                range_el.set("start", dhcp_start)
                range_el.set("end", dhcp_end)
        elif ip_address and netmask:
            # No <ip> element yet — create one (for NAT/route networks)
            ip_el = ET.SubElement(root, "ip")
            ip_el.set("address", ip_address)
            ip_el.set("netmask", netmask)
            if dhcp_start and dhcp_end:
                dhcp_el = ET.SubElement(ip_el, "dhcp")
                range_el = ET.SubElement(dhcp_el, "range")
                range_el.set("start", dhcp_start)
                range_el.set("end", dhcp_end)

        new_xml = ET.tostring(root, encoding="unicode")

        # Stop → redefine → start
        if was_active:
            net.destroy()
        net.undefine()
        new_net = conn.networkDefineXML(new_xml)
        new_net.setAutostart(1 if was_autostart else 0)
        if was_active:
            new_net.create()

        return {
            "ok": True,
            "active": bool(new_net.isActive()),
            "autostart": bool(new_net.autostart()),
        }
    finally:
        conn.close()

def get_network_info(net_uuid):
    """Get detailed info for a single network."""
    conn = _connect()
    try:
        net = conn.networkLookupByUUIDString(net_uuid)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(net.XMLDesc(0))
        ip_el = root.find("ip")
        dhcp_el = ip_el.find("dhcp") if ip_el is not None else None
        range_el = dhcp_el.find("range") if dhcp_el is not None else None
        # forward mode — use .get() on element, NOT findtext("forward/@mode")
        # (stdlib ET doesn't support @attr in findtext path → SyntaxError)
        fwd_el = root.find("forward")
        fwd_mode = fwd_el.get("mode", "nat") if fwd_el is not None else "nat"
        # bridge name
        try:
            bridge_name = net.bridgeName() if net.isActive() else ""
        except Exception:
            br_el = root.find("bridge")
            bridge_name = br_el.get("name", "") if br_el is not None else ""
        return {
            "name": net.name(),
            "uuid": net_uuid,
            "active": bool(net.isActive()),
            "autostart": bool(net.autostart()),
            "bridge": bridge_name,
            "mode": fwd_mode,
            "gateway": ip_el.get("address") if ip_el is not None else None,
            "netmask": ip_el.get("netmask") if ip_el is not None else None,
            "dhcp_start": range_el.get("start") if range_el is not None else None,
            "dhcp_end": range_el.get("end") if range_el is not None else None,
        }
    finally:
        conn.close()


def _read_sys(path: str, default="") -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return default


def _parse_proc_net_dev() -> dict:
    """Parse /proc/net/dev → {iface: {rx_bytes, tx_bytes, rx_packets, tx_packets}}"""
    stats = {}
    try:
        with open("/proc/net/dev") as f:
            for line in f:
                parts = line.split()
                if ":" not in parts[0]:
                    continue
                iface = parts[0].rstrip(":")
                # columns: iface rx_bytes rx_packets rx_errs rx_drop ... tx_bytes ...
                stats[iface] = {
                    "rx_bytes":   int(parts[1]),
                    "rx_packets": int(parts[2]),
                    "tx_bytes":   int(parts[9]),
                    "tx_packets": int(parts[10]),
                }
    except Exception:
        pass
    return stats


def _iface_type(name: str) -> str:
    """Classify interface type from name and sysfs."""
    if name == "lo":
        return "loopback"
    if name.startswith("br") or name.startswith("virbr"):
        return "bridge"
    if name.startswith("vnet") or name.startswith("vif") or name.startswith("tap"):
        return "virtual"
    if name.startswith("bond"):
        return "bond"
    if "." in name:
        return "vlan"
    if name.startswith("wl"):
        return "wifi"
    if name.startswith("tun") or name.startswith("wg"):
        return "tunnel"
    return "ethernet"


def setup_host_bridge(bridge_name: str = "oxbr0", physical_iface: str = "enp1s0",
                      libvirt_net_name: str = "oxbridge") -> dict:
    """
    Host üzerinde Linux bridge oluştur ve libvirt'e kaydet.
    VMs bu bridge'e bağlanarak host NIC üzerinden doğrudan IP alır (gerçek IP izolasyonu).

    Adımlar:
    1. ip link add oxbr0 type bridge
    2. ip link set enp1s0 master oxbr0
    3. ip link set oxbr0 up
    4. libvirt'e bridge network tanımla (forward mode=bridge)
    """
    errors = []
    steps  = []

    # 1. Bridge oluştur (varsa atla)
    r = subprocess.run(["ip", "link", "show", bridge_name], capture_output=True)
    if r.returncode != 0:
        r2 = subprocess.run(
            ["ip", "link", "add", bridge_name, "type", "bridge"],
            capture_output=True, text=True
        )
        if r2.returncode == 0:
            steps.append(f"Bridge oluşturuldu: {bridge_name}")
        else:
            errors.append(f"Bridge oluşturulamadı: {r2.stderr.strip()}")
    else:
        steps.append(f"Bridge zaten var: {bridge_name}")

    # 2. Fiziksel NIC'i bridge'e ekle
    r3 = subprocess.run(
        ["ip", "link", "set", physical_iface, "master", bridge_name],
        capture_output=True, text=True
    )
    if r3.returncode == 0:
        steps.append(f"{physical_iface} → {bridge_name}")
    else:
        errors.append(f"NIC bridge'e eklenemedi: {r3.stderr.strip()}")

    # 3. Bridge'i aktif et
    subprocess.run(["ip", "link", "set", bridge_name, "up"], capture_output=True)
    steps.append(f"{bridge_name} UP")

    # 4. Libvirt bridge network tanımla
    xml = f"""<network>
  <name>{libvirt_net_name}</name>
  <forward mode='bridge'/>
  <bridge name='{bridge_name}'/>
</network>"""

    try:
        conn = _connect()
        try:
            # Varsa önce sil
            try:
                existing = conn.networkLookupByName(libvirt_net_name)
                if existing.isActive():
                    existing.destroy()
                existing.undefine()
            except Exception:
                pass

            net = conn.networkDefineXML(xml)
            net.setAutostart(1)
            net.create()
            steps.append(f"Libvirt network tanımlandı: {libvirt_net_name}")
        finally:
            conn.close()
    except Exception as e:
        errors.append(f"Libvirt network hatası: {e}")

    return {
        "ok": len(errors) == 0,
        "bridge": bridge_name,
        "physical_iface": physical_iface,
        "libvirt_network": libvirt_net_name,
        "steps": steps,
        "errors": errors,
        "info": (
            "VMs bu ağda oluşturulduğunda fiziksel NIC üzerinden doğrudan IP alır. "
            "Upstream DHCP veya cloud-init static IP kullanın."
        ),
    }


def list_host_bridges() -> list:
    """Host üzerindeki Linux bridge listesi."""
    result = subprocess.run(
        ["ip", "-j", "link", "show", "type", "bridge"],
        capture_output=True, text=True
    )
    bridges = []
    try:
        import json as _json
        data = _json.loads(result.stdout)
        for item in data:
            name = item.get("ifname", "")
            state = item.get("operstate", "UNKNOWN").lower()
            # Üyeleri bul
            r2 = subprocess.run(
                ["ip", "link", "show", "master", name],
                capture_output=True, text=True
            )
            members = []
            for line in r2.stdout.splitlines():
                parts = line.split(":")
                if len(parts) >= 2:
                    iface = parts[1].strip().split("@")[0].strip()
                    if iface and iface != name:
                        members.append(iface)
            bridges.append({"name": name, "state": state, "members": members})
    except Exception:
        pass
    return bridges


def _detect_primary_iface() -> str:
    """Detect primary physical interface from default route (e.g. ens160)."""
    result = subprocess.run(["ip", "route", "show", "default"],
                            capture_output=True, text=True)
    for line in result.stdout.splitlines():
        parts = line.split()
        if "dev" in parts:
            idx = parts.index("dev")
            if idx + 1 < len(parts):
                candidate = parts[idx + 1]
                # Skip virtual/bridge ifaces
                if not any(candidate.startswith(p) for p in
                           ("virbr", "vnet", "vif", "tap", "br", "lo", "tun", "wg")):
                    return candidate
    return "ens160"


def ensure_physnet() -> dict:
    """
    Ensure oxbridge (Linux bridge) or fallback network exists for VMs to reach
    the physical network.

    Priority:
    1. oxbridge already active in libvirt → return it
    2. oxbr0 Linux bridge exists on host → register with libvirt as oxbridge
    3. Any other passthrough/bridge libvirt network → return it
    4. Fallback: macvtap passthrough on detected interface (single-VM only)

    Never raises — caller logs result.
    """
    try:
        conn = _connect()
        try:
            # Priority 1: oxbridge already registered and active
            for net in conn.listAllNetworks():
                if net.name() == "oxbridge" and net.isActive():
                    return {"ok": True, "existing": True, "name": "oxbridge", "mode": "bridge"}

            # Priority 3: any other passthrough/bridge network
            _fallback = None
            for net in conn.listAllNetworks():
                if not net.isActive():
                    continue
                root = ET.fromstring(net.XMLDesc())
                forward = root.find("forward")
                if forward is not None and forward.get("mode") in (
                        "passthrough", "bridge", "private", "vepa"):
                    _fallback = {"ok": True, "existing": True,
                                 "name": net.name(), "mode": forward.get("mode")}
        finally:
            conn.close()
    except Exception as _e:
        return {"ok": False, "error": f"libvirt scan failed: {_e}"}

    # Priority 2: oxbr0 exists on host but not registered in libvirt
    _br_check = subprocess.run(["ip", "link", "show", "oxbr0"], capture_output=True)
    if _br_check.returncode == 0:
        _xml = """<network>
  <name>oxbridge</name>
  <forward mode='bridge'/>
  <bridge name='oxbr0'/>
</network>"""
        try:
            conn = _connect()
            try:
                # Remove stale unstarted definition if exists
                try:
                    _old = conn.networkLookupByName("oxbridge")
                    if not _old.isActive():
                        _old.undefine()
                except Exception:
                    pass
                net = conn.networkDefineXML(_xml)
                net.setAutostart(1)
                net.create()
                return {"ok": True, "created": True, "name": "oxbridge", "mode": "bridge"}
            finally:
                conn.close()
        except Exception as e:
            # oxbr0 exists but libvirt registration failed — still usable
            if _fallback:
                return _fallback
            return {"ok": False, "error": f"oxbridge register failed: {e}"}

    if _fallback:
        return _fallback

    # Priority 4: macvtap passthrough fallback (single-VM only, host can't reach VM)
    iface = _detect_primary_iface()
    try:
        result = create_network("physnet", forward_mode="bridge", bridge_iface=iface)
        result["created"] = True
        result["iface"] = iface
        result["warning"] = (
            "macvtap passthrough kullanılıyor — host VM'lere ulaşamaz. "
            "Kalıcı çözüm için install.sh çalıştırın (oxbr0 bridge kurar)."
        )
        return result
    except Exception as e:
        return {"ok": False, "error": str(e), "iface": iface}


def get_host_interfaces():
    result = subprocess.run(
        ["ip", "-j", "addr"],
        capture_output=True, text=True
    )
    interfaces = []
    _stats = _parse_proc_net_dev()
    try:
        import json
        ifaces = json.loads(result.stdout)
        for iface in ifaces:
            ifname = iface.get("ifname", "")
            addrs  = [
                a["local"]
                for a in iface.get("addr_info", [])
                if a.get("family") == "inet"
            ]
            addrs6 = [
                a["local"]
                for a in iface.get("addr_info", [])
                if a.get("family") == "inet6" and not a["local"].startswith("fe80")
            ]
            flags     = iface.get("flags", [])
            operstate = iface.get("operstate", "UNKNOWN").lower()
            # UNKNOWN operstate: VMware/virtual NICs report UNKNOWN even when active.
            if operstate in ("unknown", "") and "UP" in flags:
                operstate = "up"
            # Fallback: if has IP addresses, must be up
            if operstate not in ("up", "down") and addrs:
                operstate = "up"

            # Speed from sysfs (Mbps; -1 = unknown/virtual)
            speed_raw = _read_sys(f"/sys/class/net/{ifname}/speed")
            try:
                speed_mbps = int(speed_raw)
            except (ValueError, TypeError):
                speed_mbps = -1

            # Duplex
            duplex = _read_sys(f"/sys/class/net/{ifname}/duplex")

            # Driver via ethtool module path
            driver = _read_sys(f"/sys/class/net/{ifname}/device/driver/module/srcversion",
                               _read_sys(f"/sys/class/net/{ifname}/device/uevent", ""))
            # Simpler driver: just use modalias or skip
            driver = ""

            net_stats = _stats.get(ifname, {})

            interfaces.append({
                "name":       ifname,
                "state":      operstate,
                "mac":        iface.get("address", ""),
                "addresses":  addrs,
                "addresses6": addrs6,
                "flags":      flags,
                "mtu":        iface.get("mtu", 1500),
                "type":       _iface_type(ifname),
                "speed_mbps": speed_mbps if speed_mbps > 0 else None,
                "duplex":     duplex or None,
                "rx_bytes":   net_stats.get("rx_bytes", 0),
                "tx_bytes":   net_stats.get("tx_bytes", 0),
                "rx_packets": net_stats.get("rx_packets", 0),
                "tx_packets": net_stats.get("tx_packets", 0),
            })
    except Exception:
        pass
    return interfaces


# ── MAC OUI lookup (çevrimdışı, sadece yaygın satıcılar) ─────────────────────
_OUI_TABLE = {
    "00:00:0c": "Cisco", "00:01:42": "Cisco", "00:0d:60": "Cisco",
    "00:1a:a2": "Cisco", "00:25:45": "Cisco", "00:50:56": "VMware",
    "00:0c:29": "VMware", "00:e0:4c": "Realtek", "08:00:27": "VirtualBox",
    "00:1b:21": "Intel", "08:00:20": "Sun", "00:0a:f7": "HPE",
    "3c:d9:2b": "HPE", "00:17:a4": "HPE", "00:1c:c4": "MikroTik",
    "d4:ca:6d": "MikroTik", "b8:69:f4": "MikroTik", "e4:8d:8c": "MikroTik",
    "00:e0:52": "Juniper", "2c:21:72": "Juniper", "00:1f:12": "Juniper",
    "0c:75:bd": "Dell", "14:18:77": "Dell", "00:21:9b": "Dell",
    "7c:d1:c3": "Ubiquiti", "00:27:22": "Ubiquiti", "f4:92:bf": "Ubiquiti",
    "18:e8:29": "Huawei", "ac:85:3d": "Huawei", "00:e0:fc": "Huawei",
    "00:1e:67": "Arista", "00:1c:73": "Arista",
    "00:24:e8": "Extreme Networks", "00:04:96": "Extreme Networks",
}

def _mac_vendor(mac: str) -> str:
    if not mac or len(mac) < 8:
        return ""
    oui = mac[:8].lower()
    return _OUI_TABLE.get(oui, "")


def get_lldp_neighbors() -> list:
    """
    LLDP komşu cihazları döndür.
    lldpd kuruluysa lldpctl -f json ile gerçek veri,
    kurulu değilse ARP tablosu + MAC vendor lookup ile tahmin.
    """
    neighbors = []

    # ── Yöntem 1: lldpctl (lldpd paketi) ──────────────────────────────────
    try:
        import subprocess, json as _json
        result = subprocess.run(
            ["lldpctl", "-f", "json"],
            capture_output=True, text=True, timeout=8
        )
        if result.returncode == 0 and result.stdout.strip():
            data = _json.loads(result.stdout)
            lldp = data.get("lldp", {})
            ifaces = lldp.get("interface", {})
            if isinstance(ifaces, list):
                ifaces = {item.get("name","?"): item for item in ifaces}
            for iface_name, iface_data in ifaces.items():
                chassis = iface_data.get("chassis", {})
                if isinstance(chassis, list):
                    chassis = chassis[0] if chassis else {}
                port = iface_data.get("port", {})
                if isinstance(port, list):
                    port = port[0] if port else {}
                ch_name = chassis.get("name", {})
                if isinstance(ch_name, dict):
                    ch_name = ch_name.get("value", "")
                ch_desc = chassis.get("descr", {})
                if isinstance(ch_desc, dict):
                    ch_desc = ch_desc.get("value", "")
                port_id = port.get("id", {})
                if isinstance(port_id, dict):
                    port_id = port_id.get("value", "")
                ch_mac = ""
                ch_id = chassis.get("id", {})
                if isinstance(ch_id, dict) and ch_id.get("type") == "mac":
                    ch_mac = ch_id.get("value", "")
                neighbors.append({
                    "source":      "lldp",
                    "local_iface": iface_name,
                    "chassis_name": str(ch_name),
                    "chassis_desc": str(ch_desc)[:120],
                    "port_id":     str(port_id),
                    "mac":         ch_mac,
                    "vendor":      _mac_vendor(ch_mac),
                    "type":        "switch" if "switch" in str(ch_desc).lower() else "device",
                })
            if neighbors:
                return neighbors
    except FileNotFoundError:
        pass  # lldpd kurulu değil
    except Exception:
        pass

    # ── Yöntem 2: ARP tablosu + MAC vendor ────────────────────────────────
    try:
        import subprocess
        result = subprocess.run(
            ["ip", "-j", "neigh"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            import json as _json
            entries = _json.loads(result.stdout)
            for e in entries:
                mac  = e.get("lladdr", "")
                ip   = e.get("dst", "")
                dev  = e.get("dev", "")
                state = e.get("state", [])
                if not mac or not ip:
                    continue
                # Sadece erişilebilir/kalıcı kayıtlar
                if isinstance(state, list) and any(s in state for s in ("REACHABLE", "PERMANENT", "STALE", "DELAY")):
                    vendor = _mac_vendor(mac)
                    neighbors.append({
                        "source":       "arp",
                        "local_iface":  dev,
                        "ip":           ip,
                        "mac":          mac,
                        "vendor":       vendor,
                        "type":         "switch" if any(k in vendor.lower() for k in ("cisco","juniper","arista","ubiquiti","mikrotik","hpe","huawei","extreme")) else "host",
                        "chassis_name": vendor or mac,
                        "chassis_desc": "",
                        "port_id":      "",
                    })
    except Exception:
        pass

    return neighbors


def get_arp_table() -> list:
    """Tam ARP tablosunu döndür (tüm kayıtlar)."""
    try:
        import subprocess, json as _json
        result = subprocess.run(["ip", "-j", "neigh"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            entries = _json.loads(result.stdout)
            out = []
            for e in entries:
                mac = e.get("lladdr", "")
                out.append({
                    "ip":     e.get("dst", ""),
                    "mac":    mac,
                    "iface":  e.get("dev", ""),
                    "state":  e.get("state", []),
                    "vendor": _mac_vendor(mac),
                })
            return out
    except Exception:
        pass
    return []






