#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Manage ANKAVM VMs (create/delete/start/stop/snapshot)."""
from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: vm
short_description: Manage ANKAVM VMs
description:
  - Create, delete, start, stop, reboot, snapshot ANKAVM VMs via REST API.
options:
  name:
    description: VM name (unique).
    type: str
    required: true
  state:
    description: Desired state.
    choices: [present, absent, started, stopped, rebooted, snapshot]
    default: present
  vcpus:
    description: vCPU count (present only).
    type: int
  memory_mb:
    description: RAM in MB (present only).
    type: int
  disk_gb:
    description: Disk size GB (present only).
    type: int
  iso:
    description: ISO path or library name for install.
    type: str
  os_variant:
    description: libosinfo variant (ubuntu24.04, debian12, win11, ...).
    type: str
  network:
    description: libvirt network name (default = 'default').
    type: str
    default: default
  snapshot_name:
    description: Snapshot name (when state=snapshot).
    type: str
extends_documentation_fragment:
  - ankavm.kvm.common
author:
  - ANKAVM (@ankavm)
"""

EXAMPLES = r"""
- name: Create Ubuntu VM
  ankavm.kvm.vm:
    host: https://ankavm.example.com
    token: "{{ ankavm_token }}"
    name: web-01
    state: present
    vcpus: 2
    memory_mb: 2048
    disk_gb: 20
    iso: ubuntu-24.04.iso
    os_variant: ubuntu24.04

- name: Stop VM
  ankavm.kvm.vm:
    host: https://ankavm.example.com
    token: "{{ ankavm_token }}"
    name: web-01
    state: stopped

- name: Take snapshot
  ankavm.kvm.vm:
    host: https://ankavm.example.com
    token: "{{ ankavm_token }}"
    name: web-01
    state: snapshot
    snapshot_name: pre-upgrade
"""

RETURN = r"""
vm:
  description: VM details from ankavm API.
  returned: always
  type: dict
changed:
  description: Whether a change was made.
  returned: always
  type: bool
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ankavm.kvm.plugins.module_utils.ankavm_api import (
    COMMON_ARGS, build_client
)


def find_vm(client, name):
    r = client.get("/api/vms")
    for v in r.get("vms", []):
        if v.get("name") == name:
            return v
    return None


def run():
    args = dict(COMMON_ARGS)
    args.update(
        name          = dict(type="str", required=True),
        state         = dict(type="str", default="present",
                             choices=["present","absent","started","stopped","rebooted","snapshot"]),
        vcpus         = dict(type="int"),
        memory_mb     = dict(type="int"),
        disk_gb       = dict(type="int"),
        iso           = dict(type="str"),
        os_variant    = dict(type="str"),
        network       = dict(type="str", default="default"),
        snapshot_name = dict(type="str"),
    )
    module = AnsibleModule(argument_spec=args, supports_check_mode=True)
    client = build_client(module)
    name   = module.params["name"]
    state  = module.params["state"]

    vm     = find_vm(client, name)
    result = {"changed": False, "vm": vm}

    if module.check_mode:
        module.exit_json(**result)

    try:
        if state == "absent":
            if vm:
                client.delete("/api/vms/" + vm["id"])
                result["changed"] = True
                result["vm"]      = None
        elif state == "present":
            if not vm:
                payload = {
                    "name":       name,
                    "vcpus":      module.params.get("vcpus")     or 1,
                    "memory_mb":  module.params.get("memory_mb") or 1024,
                    "disk_gb":    module.params.get("disk_gb")   or 10,
                    "iso":        module.params.get("iso"),
                    "os_variant": module.params.get("os_variant"),
                    "network":    module.params.get("network"),
                }
                r = client.post("/api/vms", payload)
                result["changed"] = True
                result["vm"]      = r.get("vm") or r
        elif state in ("started", "stopped", "rebooted"):
            if not vm:
                module.fail_json(msg="VM not found: " + name)
            action_map = {"started":"start", "stopped":"shutdown", "rebooted":"reboot"}
            target     = action_map[state]
            cur        = vm.get("state", "").lower()
            if (state == "started" and cur != "running") or \
               (state == "stopped" and cur == "running") or \
               (state == "rebooted"):
                client.post("/api/vms/" + vm["id"] + "/action", {"action": target})
                result["changed"] = True
        elif state == "snapshot":
            if not vm:
                module.fail_json(msg="VM not found: " + name)
            snap = module.params.get("snapshot_name") or ("ansible-" + name)
            client.post("/api/vms/" + vm["id"] + "/snapshot", {"name": snap})
            result["changed"] = True
            result["snapshot"] = snap

        module.exit_json(**result)
    except Exception as e:
        module.fail_json(msg=str(e), **result)


if __name__ == "__main__":
    run()






