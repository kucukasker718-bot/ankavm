# -*- coding: utf-8 -*-
"""
ankavm API helper for Ansible modules.
Shared HTTP client with auth, JSON handling, retries.
"""
from __future__ import absolute_import, division, print_function
__metaclass__ = type

import json
import ssl
import time
try:
    from urllib.request import Request, urlopen, HTTPError, URLError
except ImportError:
    from urllib2 import Request, urlopen, HTTPError, URLError


class ankavmClient(object):
    """Minimal stdlib HTTP client — no external deps for ansible-galaxy installs."""

    def __init__(self, host, token=None, username=None, password=None,
                 verify_ssl=True, timeout=30):
        self.host       = host.rstrip("/")
        self.token      = token
        self.username   = username
        self.password   = password
        self.verify_ssl = verify_ssl
        self.timeout    = timeout
        if not self.token and self.username and self.password:
            self.login()

    def _ctx(self):
        if self.verify_ssl:
            return None
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        return ctx

    def request(self, method, path, payload=None, retries=2):
        url = self.host + path
        data = None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        last_err = None
        for attempt in range(retries + 1):
            try:
                req = Request(url, data=data, method=method, headers=headers)
                with urlopen(req, timeout=self.timeout, context=self._ctx()) as r:
                    body = r.read().decode("utf-8", errors="replace")
                    return json.loads(body) if body else {}
            except HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                try:
                    j = json.loads(body)
                except Exception:
                    j = {"error": body}
                raise RuntimeError("ankavm API %d: %s" % (e.code, j.get("error", body)))
            except URLError as e:
                last_err = e
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError("ankavm API connect failed: %s" % str(e))
        raise RuntimeError("ankavm API unreachable: %s" % str(last_err))

    def login(self):
        r = self.request("POST", "/api/auth/login",
                         {"username": self.username, "password": self.password})
        self.token = r.get("access_token") or r.get("token")
        if not self.token:
            raise RuntimeError("ankavm login failed: token missing in response")
        return self.token

    # Convenience
    def get(self, path):       return self.request("GET",    path)
    def post(self, path, p):   return self.request("POST",   path, p)
    def put(self, path, p):    return self.request("PUT",    path, p)
    def delete(self, path):    return self.request("DELETE", path)


COMMON_ARGS = dict(
    host       = dict(type="str", required=True),
    token      = dict(type="str", no_log=True),
    username   = dict(type="str"),
    password   = dict(type="str", no_log=True),
    verify_ssl = dict(type="bool", default=True),
    timeout    = dict(type="int", default=30),
)


def build_client(module):
    """Create ankavmClient from module params."""
    p = module.params
    if not p.get("token") and not (p.get("username") and p.get("password")):
        module.fail_json(msg="Either 'token' or 'username'+'password' required")
    try:
        return ankavmClient(
            host       = p["host"],
            token      = p.get("token"),
            username   = p.get("username"),
            password   = p.get("password"),
            verify_ssl = p["verify_ssl"],
            timeout    = p["timeout"],
        )
    except Exception as e:
        module.fail_json(msg="Auth failed: %s" % str(e))






