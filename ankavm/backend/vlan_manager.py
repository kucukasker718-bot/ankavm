"""
vlan_manager.py â€” VLAN network yÃ¶netimi (Linux bridge + libvirt) (ankavm Hypervisor)
Root yetkisi gerekir.
"""

import subprocess
import json
import logging
import os
import threading
import uuid
import re

log = logging.getLogger("ankavm.vlan")

VLANS_FILE = "/var/lib/ankavm/vlans.json"

_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Ä°Ã§ yardÄ±mcÄ±lar
# ---------------------------------------------------------------------------

def _run(*cmd):
    """subprocess.run Ã§alÄ±ÅŸtÄ±rÄ±r; hata fÄ±rlatmaz."""
    try:
        result = subprocess.run(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            log.warning("Komut baÅŸarÄ±sÄ±z [%d]: %s | stderr: %s",
                        result.returncode, " ".join(cmd), result.stderr.strip())
        return result
    except FileNotFoundError:
        log.error("Komut bulunamadÄ±: %s", cmd[0])
        return None
    except Exception as exc:
        log.exception("_run hatasÄ±: %s", exc)
        return None


def _load():
    """VLANS_FILE'dan vlan listesini yÃ¼kler."""
    try:
        os.makedirs(os.path.dirname(VLANS_FILE), exist_ok=True)
        if not os.path.exists(VLANS_FILE):
            return {}
        with open(VLANS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        log.error("VLANS_FILE okunamadÄ±: %s", exc)
        return {}


def _save(data):
    """Vlan listesini VLANS_FILE'a kaydeder."""
    try:
        os.makedirs(os.path.dirname(VLANS_FILE), exist_ok=True)
        with open(VLANS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        log.error("VLANS_FILE yazÄ±lamadÄ±: %s", exc)
        raise


def _libvirt_network_xml(vlan_id, name, bridge_name):
    """libvirt network tanÄ±m XML'ini dÃ¶ner."""
    return f"""<network>
  <name>vlan{vlan_id}-{name}</name>
  <uuid>{uuid.uuid4()}</uuid>
  <forward mode='bridge'/>
  <bridge name='{bridge_name}'/>
  <vlan tag='{vlan_id}'>
    <trunk>no</trunk>
  </vlan>
</network>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_vlans():
    """
    VLANS_FILE + ip link show ile enriched vlan listesini dÃ¶ner.
    """
    try:
        vlans = _load()

        # ip link show type vlan ile aktif olanlarÄ± bul
        active_ifaces = set()
        result = _run("ip", "-j", "link", "show", "type", "vlan")
        if result and result.returncode == 0:
            try:
                iface_data = json.loads(result.stdout)
                for iface in iface_data:
                    active_ifaces.add(iface.get("ifname", ""))
            except (json.JSONDecodeError, TypeError):
                pass

        enriched = []
        for vid, vlan in vlans.items():
            entry = dict(vlan)
            iface_name = vlan.get("iface_name", "")
            entry["active"] = iface_name in active_ifaces
            enriched.append(entry)

        return enriched
    except Exception as exc:
        log.exception("list_vlans hatasÄ±: %s", exc)
        return []


def create_vlan(parent_iface, vlan_id, name, ip_address=None, gateway=None):
    """
    VLAN arayÃ¼zÃ¼ oluÅŸturur, libvirt network tanÄ±mlar ve VLANS_FILE'a kaydeder.
    """
    with _lock:
        try:
            vlan_id = int(vlan_id)
            iface_name = f"{parent_iface}.{vlan_id}"
            bridge_name = f"br-vlan{vlan_id}"

            # ip link add
            r = _run("ip", "link", "add", "link", parent_iface,
                     "name", iface_name, "type", "vlan", "id", str(vlan_id))
            if r is None or r.returncode != 0:
                return {"success": False, "error": f"VLAN arayÃ¼zÃ¼ oluÅŸturulamadÄ±: {r.stderr.strip() if r else 'komut yok'}"}

            # ip link set up
            _run("ip", "link", "set", iface_name, "up")

            # ip addr add (opsiyonel)
            if ip_address:
                _run("ip", "addr", "add", ip_address, "dev", iface_name)

            # libvirt bridge ve network
            _run("ip", "link", "add", "name", bridge_name, "type", "bridge")
            _run("ip", "link", "set", iface_name, "master", bridge_name)
            _run("ip", "link", "set", bridge_name, "up")

            # libvirt network XML oluÅŸtur ve tanÄ±mla
            xml = _libvirt_network_xml(vlan_id, name, bridge_name)
            xml_path = f"/tmp/ankavm_vlan_{vlan_id}.xml"
            try:
                with open(xml_path, "w", encoding="utf-8") as f:
                    f.write(xml)
                _run("virsh", "net-define", xml_path)
                _run("virsh", "net-start", f"vlan{vlan_id}-{name}")
                _run("virsh", "net-autostart", f"vlan{vlan_id}-{name}")
            except OSError as exc:
                log.warning("libvirt network tanÄ±mlanamadÄ±: %s", exc)

            # VLANS_FILE'a kaydet
            vlans = _load()
            vlans[str(vlan_id)] = {
                "vlan_id": vlan_id,
                "name": name,
                "parent_iface": parent_iface,
                "iface_name": iface_name,
                "bridge_name": bridge_name,
                "ip_address": ip_address,
                "gateway": gateway,
                "libvirt_network": f"vlan{vlan_id}-{name}",
            }
            _save(vlans)

            log.info("VLAN oluÅŸturuldu: %s (id=%d)", iface_name, vlan_id)
            return {
                "success": True,
                "vlan_id": vlan_id,
                "iface_name": iface_name,
                "bridge_name": bridge_name,
            }
        except Exception as exc:
            log.exception("create_vlan hatasÄ±: %s", exc)
            return {"success": False, "error": str(exc)}


def delete_vlan(vlan_id):
    """VLAN arayÃ¼zÃ¼nÃ¼ ve libvirt network'Ã¼ siler."""
    with _lock:
        try:
            vlan_id = int(vlan_id)
            vlans = _load()
            vlan = vlans.get(str(vlan_id))

            if not vlan:
                return {"success": False, "error": "VLAN bulunamadÄ±"}

            iface_name = vlan.get("iface_name", f"*.{vlan_id}")
            bridge_name = vlan.get("bridge_name", f"br-vlan{vlan_id}")
            libvirt_net = vlan.get("libvirt_network", "")

            # libvirt network kaldÄ±r
            if libvirt_net:
                _run("virsh", "net-destroy", libvirt_net)
                _run("virsh", "net-undefine", libvirt_net)

            # Bridge ve vlan arayÃ¼zÃ¼nÃ¼ kaldÄ±r
            _run("ip", "link", "set", bridge_name, "down")
            _run("ip", "link", "del", bridge_name)
            _run("ip", "link", "del", iface_name)

            vlans.pop(str(vlan_id), None)
            _save(vlans)

            log.info("VLAN silindi: %d", vlan_id)
            return {"success": True, "vlan_id": vlan_id}
        except Exception as exc:
            log.exception("delete_vlan hatasÄ±: %s", exc)
            return {"success": False, "error": str(exc)}


def get_vlan(vlan_id):
    """Belirtilen VLAN bilgisini dÃ¶ner."""
    try:
        vlans = _load()
        vlan = vlans.get(str(vlan_id))
        if not vlan:
            return {"success": False, "error": "VLAN bulunamadÄ±"}
        return {"success": True, "vlan": vlan}
    except Exception as exc:
        log.exception("get_vlan hatasÄ±: %s", exc)
        return {"success": False, "error": str(exc)}


def list_interfaces():
    """
    ip link show parse eder; mevcut arayÃ¼zleri listeler.
    """
    try:
        result = _run("ip", "-j", "link", "show")
        if result is None or result.returncode != 0:
            return []

        try:
            ifaces = json.loads(result.stdout)
            return [
                {
                    "name": iface.get("ifname"),
                    "type": iface.get("link_type"),
                    "state": iface.get("operstate"),
                    "mac": iface.get("address"),
                    "flags": iface.get("flags", []),
                }
                for iface in ifaces
            ]
        except (json.JSONDecodeError, TypeError):
            # Fallback: text parse
            interfaces = []
            for line in result.stdout.splitlines():
                m = re.match(r"\d+: (\S+):", line)
                if m:
                    interfaces.append({"name": m.group(1).rstrip("@")})
            return interfaces
    except Exception as exc:
        log.exception("list_interfaces hatasÄ±: %s", exc)
        return []


def attach_vm_to_vlan(vm_id, vlan_id):
    """VM'i VLAN'a baÄŸlar (virsh attach-interface)."""
    try:
        vlans = _load()
        vlan = vlans.get(str(vlan_id))
        if not vlan:
            return {"success": False, "error": "VLAN bulunamadÄ±"}

        network_name = vlan.get("libvirt_network", f"vlan{vlan_id}")
        result = _run("virsh", "attach-interface", str(vm_id),
                      "--type", "network",
                      "--source", network_name,
                      "--model", "virtio",
                      "--config", "--live")

        if result is None:
            return {"success": False, "error": "virsh bulunamadÄ±"}

        success = result.returncode == 0
        log.info("VM %s VLAN %d'e baÄŸlandÄ±: %s", vm_id, vlan_id, success)
        return {
            "success": success,
            "vm_id": vm_id,
            "vlan_id": vlan_id,
            "stderr": result.stderr.strip(),
        }
    except Exception as exc:
        log.exception("attach_vm_to_vlan hatasÄ±: %s", exc)
        return {"success": False, "error": str(exc)}


def detach_vm_from_vlan(vm_id, vlan_id):
    """VM'i VLAN'dan ayÄ±rÄ±r (virsh detach-interface)."""
    try:
        vlans = _load()
        vlan = vlans.get(str(vlan_id))
        network_name = vlan.get("libvirt_network", f"vlan{vlan_id}") if vlan else f"vlan{vlan_id}"

        result = _run("virsh", "detach-interface", str(vm_id),
                      "--type", "network",
                      "--config", "--live")

        if result is None:
            return {"success": False, "error": "virsh bulunamadÄ±"}

        success = result.returncode == 0
        log.info("VM %s VLAN %d'den ayrÄ±ldÄ±: %s", vm_id, vlan_id, success)
        return {
            "success": success,
            "vm_id": vm_id,
            "vlan_id": vlan_id,
            "stderr": result.stderr.strip(),
        }
    except Exception as exc:
        log.exception("detach_vm_from_vlan hatasÄ±: %s", exc)
        return {"success": False, "error": str(exc)}


def get_vlan_stats(vlan_id):
    """ip -s link show ile VLAN arayÃ¼z istatistiklerini dÃ¶ner."""
    try:
        vlans = _load()
        vlan = vlans.get(str(vlan_id))
        if not vlan:
            return {"success": False, "error": "VLAN bulunamadÄ±"}

        iface_name = vlan.get("iface_name", f"*.{vlan_id}")

        result = _run("ip", "-j", "-s", "link", "show", iface_name)
        if result is None or result.returncode != 0:
            return {"success": False, "error": "ArayÃ¼z bulunamadÄ±"}

        try:
            data = json.loads(result.stdout)
            if data:
                stats = data[0].get("stats64", data[0].get("stats", {}))
                return {
                    "success": True,
                    "iface": iface_name,
                    "rx_bytes": stats.get("rx", {}).get("bytes", 0),
                    "tx_bytes": stats.get("tx", {}).get("bytes", 0),
                    "rx_packets": stats.get("rx", {}).get("packets", 0),
                    "tx_packets": stats.get("tx", {}).get("packets", 0),
                    "rx_errors": stats.get("rx", {}).get("errors", 0),
                    "tx_errors": stats.get("tx", {}).get("errors", 0),
                }
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            log.warning("Stats JSON parse hatasÄ±: %s", exc)

        return {"success": True, "iface": iface_name, "raw": result.stdout}
    except Exception as exc:
        log.exception("get_vlan_stats hatasÄ±: %s", exc)
        return {"success": False, "error": str(exc)}






