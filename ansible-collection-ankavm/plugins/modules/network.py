#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Manage ANKAVM networks."""
from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: network
short_description: Manage ANKAVM libvirt networks
options:
  name:
    description: Network name.
    type: str
    required: true
  state:
    description: present or absent
    choices: [present, absent]
    default: present
  forward_mode:
    description: nat | bridge | isolated | route
    type: str
    default: nat
  subnet:
    description: e.g. 192.168.122.0/24
    type: str
  bridge:
    description: bridge interface (bridge mode)
    type: str
extends_documentation_fragment:
  - ankavm.kvm.common
"""

EXAMPLES = r"""
- name: Create NAT network
  ankavm.kvm.network:
    host: https://ankavm.example.com
    token: "{{ ankavm_token }}"
    name: vmnet-prod
    forward_mode: nat
    subnet: 10.10.0.0/24
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ankavm.kvm.plugins.module_utils.ankavm_api import (
    COMMON_ARGS, build_client
)


def find_net(client, name):
    r = client.get("/api/networks")
    for n in r.get("networks", []):
        if n.get("name") == name:
            return n
    return None


def run():
    args = dict(COMMON_ARGS)
    args.update(
        name         = dict(type="str", required=True),
        state        = dict(type="str", default="present", choices=["present","absent"]),
        forward_mode = dict(type="str", default="nat",
                            choices=["nat","bridge","isolated","route"]),
        subnet       = dict(type="str"),
        bridge       = dict(type="str"),
    )
    module = AnsibleModule(argument_spec=args, supports_check_mode=True)
    client = build_client(module)
    name   = module.params["name"]
    state  = module.params["state"]

    net    = find_net(client, name)
    result = {"changed": False, "network": net}
    if module.check_mode:
        module.exit_json(**result)

    try:
        if state == "absent" and net:
            client.delete("/api/networks/" + net.get("uuid", name))
            result["changed"] = True
            result["network"] = None
        elif state == "present" and not net:
            payload = {
                "name":         name,
                "forward_mode": module.params["forward_mode"],
                "subnet":       module.params.get("subnet"),
                "bridge":       module.params.get("bridge"),
            }
            r = client.post("/api/networks", payload)
            result["changed"] = True
            result["network"] = r.get("network") or r
        module.exit_json(**result)
    except Exception as e:
        module.fail_json(msg=str(e), **result)


if __name__ == "__main__":
    run()






