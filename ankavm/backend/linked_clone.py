"""
ankavm Linked Clones
â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
qemu-img backing file ile space-efficient VM kopyalarÄ±.
100 VM = 1 base (10 GB) + 100Ã—500MB diff = 60 GB (vs 1 TB full copy).

API:
    create_linked_clone(base_vm_id, new_vm_name, snapshot_name=None) -> dict
    convert_to_full(vm_id, disk_target) -> dict  (linked â†’ full)
    list_dependents(base_disk) -> list           (kimler bu base'i kullanÄ±yor)
"""

import os, subprocess, logging, uuid, json
from pathlib import Path

log = logging.getLogger("linked_clone")


def _qemu_img_info(path: str) -> dict:
    """qemu-img info JSON."""
    try:
        r = subprocess.run(["qemu-img", "info", "--output=json", path],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return json.loads(r.stdout)
    except Exception as e:
        log.warning("qemu-img info hatasÄ±: %s", e)
    return {}


def _virsh_dumpxml(vm: str) -> str:
    r = subprocess.run(["virsh", "dumpxml", vm], capture_output=True, text=True, timeout=10)
    return r.stdout if r.returncode == 0 else ""


def _get_disk_paths(vm: str) -> list:
    """VM'in disk yollarÄ±nÄ± al."""
    xml = _virsh_dumpxml(vm)
    import re
    return re.findall(r"<source file='([^']+)'/>", xml)


def create_linked_clone(base_vm: str, new_vm_name: str,
                         output_dir: str = "/var/lib/libvirt/images") -> dict:
    """
    base_vm: kaynak VM adÄ±/UUID
    new_vm_name: yeni klon adÄ±

    AkÄ±ÅŸ:
      1. base disk yolunu bul
      2. base diski "snapshot mode" â€” write protect / backing only
      3. Yeni qcow2 (overlay) oluÅŸtur: backing=base
      4. virsh define ile yeni VM
    """
    if not new_vm_name or "/" in new_vm_name:
        raise ValueError("GeÃ§ersiz klon adÄ±")

    base_disks = _get_disk_paths(base_vm)
    if not base_disks:
        raise ValueError(f"Base VM diski bulunamadÄ±: {base_vm}")
    base_disk = base_disks[0]

    if not os.path.exists(base_disk):
        raise FileNotFoundError(base_disk)

    # Base disk read-only zorunlu DEÄÄ°L â€” qemu overlay COW yapacak
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    clone_disk = out_dir / f"{new_vm_name}.qcow2"

    if clone_disk.exists():
        raise FileExistsError(f"Klon diski zaten var: {clone_disk}")

    # qemu-img create -f qcow2 -F qcow2 -b base.qcow2 clone.qcow2
    r = subprocess.run(
        ["qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
         "-b", base_disk, str(clone_disk)],
        capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        raise RuntimeError(f"qemu-img create baÅŸarÄ±sÄ±z: {r.stderr.strip()}")

    # Yeni VM XML Ã¼ret â€” base XML kopyala, name + UUID + disk path deÄŸiÅŸtir
    xml = _virsh_dumpxml(base_vm)
    if not xml:
        clone_disk.unlink()
        raise RuntimeError("Base VM XML alÄ±namadÄ±")

    new_uuid = str(uuid.uuid4())
    import re
    # name deÄŸiÅŸtir
    xml = re.sub(r"<name>[^<]+</name>", f"<name>{new_vm_name}</name>", xml, 1)
    # uuid deÄŸiÅŸtir
    xml = re.sub(r"<uuid>[^<]+</uuid>", f"<uuid>{new_uuid}</uuid>", xml, 1)
    # ilk disk path deÄŸiÅŸtir
    xml = re.sub(
        r"<source file='[^']+'/>",
        f"<source file='{clone_disk}'/>",
        xml, 1
    )
    # MAC adresleri random'la (network manager ayrÄ± handle)
    def _new_mac(_m):
        import random
        oct = [0x52, 0x54, 0x00] + [random.randint(0, 255) for _ in range(3)]
        return f"<mac address='{':'.join(f'{x:02x}' for x in oct)}'/>"
    xml = re.sub(r"<mac address='[^']+'/>", _new_mac, xml)

    # XML'i geÃ§ici dosyaya yaz + virsh define
    tmp_xml = Path(f"/tmp/ankavm-clone-{new_uuid}.xml")
    tmp_xml.write_text(xml)
    try:
        r = subprocess.run(["virsh", "define", str(tmp_xml)],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            clone_disk.unlink()
            raise RuntimeError(f"virsh define baÅŸarÄ±sÄ±z: {r.stderr.strip()}")
    finally:
        try:
            tmp_xml.unlink()
        except Exception:
            pass

    info = _qemu_img_info(str(clone_disk))
    return {
        "ok":          True,
        "vm_name":     new_vm_name,
        "vm_uuid":     new_uuid,
        "base_disk":   base_disk,
        "clone_disk":  str(clone_disk),
        "virtual_size": info.get("virtual-size", 0),
        "actual_size":  info.get("actual-size", 0),
        "savings":     info.get("virtual-size", 0) - info.get("actual-size", 0),
    }


def convert_to_full(vm_name: str, output_dir: str = None) -> dict:
    """Linked clone'u full (standalone) qcow2'ye Ã§evir."""
    disks = _get_disk_paths(vm_name)
    if not disks:
        raise ValueError("VM disk bulunamadÄ±")

    src = disks[0]
    info = _qemu_img_info(src)
    backing = info.get("backing-filename")
    if not backing:
        return {"ok": False, "message": "Zaten standalone disk â€” backing file yok"}

    out_dir = Path(output_dir or os.path.dirname(src))
    full_disk = out_dir / f"{vm_name}-full.qcow2"

    r = subprocess.run(
        ["qemu-img", "convert", "-O", "qcow2", src, str(full_disk)],
        capture_output=True, text=True, timeout=600
    )
    if r.returncode != 0:
        raise RuntimeError(f"qemu-img convert baÅŸarÄ±sÄ±z: {r.stderr.strip()}")

    # VM XML'inde disk path deÄŸiÅŸtir
    xml = _virsh_dumpxml(vm_name)
    import re
    xml = re.sub(
        r"<source file='" + re.escape(src) + r"'/>",
        f"<source file='{full_disk}'/>",
        xml
    )
    tmp = Path(f"/tmp/ankavm-full-{vm_name}.xml")
    tmp.write_text(xml)
    try:
        subprocess.run(["virsh", "define", str(tmp)], capture_output=True, timeout=10)
    finally:
        try: tmp.unlink()
        except Exception: pass

    return {
        "ok":           True,
        "old_disk":     src,
        "new_disk":     str(full_disk),
        "size_bytes":   full_disk.stat().st_size,
    }


def list_dependents(base_disk: str) -> list:
    """Bu base'i kullanan tÃ¼m VM'leri/diskleri bul."""
    deps = []
    try:
        # virsh list --all + her birinin diskini incele
        r = subprocess.run(["virsh", "list", "--all", "--name"],
                           capture_output=True, text=True, timeout=10)
        for vm in r.stdout.splitlines():
            vm = vm.strip()
            if not vm:
                continue
            for d in _get_disk_paths(vm):
                info = _qemu_img_info(d)
                if info.get("backing-filename") == base_disk or info.get("full-backing-filename") == base_disk:
                    deps.append({
                        "vm":      vm,
                        "disk":    d,
                        "size":    info.get("actual-size", 0),
                    })
    except Exception as e:
        log.warning("list_dependents hatasÄ±: %s", e)
    return deps


def stats() -> dict:
    """TÃ¼m linked clone'larÄ±n Ã¶zeti."""
    out = []
    try:
        r = subprocess.run(["virsh", "list", "--all", "--name"],
                           capture_output=True, text=True, timeout=10)
        for vm in r.stdout.splitlines():
            vm = vm.strip()
            if not vm:
                continue
            for d in _get_disk_paths(vm):
                info = _qemu_img_info(d)
                if info.get("backing-filename"):
                    out.append({
                        "vm":            vm,
                        "disk":          d,
                        "backing":       info.get("backing-filename"),
                        "virtual_size":  info.get("virtual-size", 0),
                        "actual_size":   info.get("actual-size", 0),
                    })
    except Exception as e:
        log.warning("linked_clone stats hatasÄ±: %s", e)
    return {
        "linked_clones": out,
        "total_count":   len(out),
        "total_actual":  sum(c["actual_size"] for c in out),
        "total_virtual": sum(c["virtual_size"] for c in out),
    }






