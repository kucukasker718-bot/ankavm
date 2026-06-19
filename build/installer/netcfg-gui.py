#!/usr/bin/env python3
"""
ankavm Hypervisor â€” Network Configuration GUI
Proxmox VE tarzÄ± pre-install aÄŸ yapÄ±landÄ±rmasÄ±.
Calamares baÅŸlamadan Ã¶nce Ã§alÄ±ÅŸÄ±r, config â†’ /tmp/ankavm-netcfg.json
"""
import tkinter as tk
import json, re, subprocess, os, sys

OUT = "/tmp/ankavm-netcfg.json"

# â”€â”€ Renk paleti (Proxmox tarzÄ± koyu lacivert) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BG      = "#0a1628"
SIDEBAR = "#060e1c"
CARD    = "#0d1f3a"
INPUT   = "#0b1930"
BTN     = "#1565c0"
BTNH    = "#1976d2"
FG      = "#ffffff"
FGL     = "#c5d8f0"
FGM     = "#5a89a8"
FGD     = "#2a4460"
ACT     = "#4a9eff"
ERR     = "#ef5350"
BDR     = "#18304f"
STEP_A  = "#1565c0"
STEP_I  = "#0f2038"


# â”€â”€ AÄŸ yardÄ±mcÄ±larÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _ifaces():
    EXCLUDE = re.compile(r"^(lo|vir|docker|br[0-9]|veth|dummy|vbox|vmnet)")
    try:
        out = subprocess.check_output(
            ["ip", "-o", "link", "show"], text=True, stderr=subprocess.DEVNULL)
        lst = []
        for ln in out.splitlines():
            m = re.match(r"\d+: ([^:@\s]+)", ln)
            if m:
                n = m.group(1).strip()
                if not EXCLUDE.match(n):
                    lst.append(n)
        return lst or ["eth0"]
    except Exception:
        return ["eth0"]


def _iface_info(iface):
    info = {"ip": "", "mask": "255.255.255.0", "gw": "", "dns": "8.8.8.8"}
    try:
        r = subprocess.check_output(
            ["ip", "-o", "-4", "addr", "show", iface],
            text=True, stderr=subprocess.DEVNULL)
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", r)
        if m:
            info["ip"] = m.group(1)
            pfx = int(m.group(2))
            n = (0xFFFFFFFF << (32 - pfx)) & 0xFFFFFFFF
            info["mask"] = ".".join(str((n >> s) & 0xFF) for s in [24, 16, 8, 0])
    except Exception:
        pass
    try:
        r = subprocess.check_output(
            ["ip", "-4", "route", "show", "default"],
            text=True, stderr=subprocess.DEVNULL)
        m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", r)
        if m:
            info["gw"] = m.group(1)
    except Exception:
        pass
    try:
        with open("/etc/resolv.conf") as f:
            for ln in f:
                if ln.startswith("nameserver"):
                    info["dns"] = ln.split()[1]
                    break
    except Exception:
        pass
    return info


def _hostname():
    try:
        h = open("/etc/hostname").read().strip()
        return h if h else "ankavm-node"
    except Exception:
        return "ankavm-node"


# â”€â”€ Ana uygulama â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class App:
    FONT_UI    = "Ubuntu"
    FONT_MONO  = "Ubuntu Mono"
    FONT_FALL  = "sans-serif"

    def __init__(self):
        self.r = tk.Tk()
        self.r.title("ankavm Hypervisor â€” AÄŸ YapÄ±landÄ±rmasÄ±")
        self.r.configure(bg=BG, cursor="left_ptr")
        self.r.attributes("-fullscreen", True)
        # ESC devre dÄ±ÅŸÄ± â€” kullanÄ±cÄ± geri dÃ¶nemez
        self.r.bind("<Escape>", lambda e: None)
        self.r.bind("<Return>", lambda e: self._go())

        self.ifaces  = _ifaces()
        self.v_iface = tk.StringVar(value=self.ifaces[0])
        self.v_dhcp  = tk.BooleanVar(value=True)
        self.v_host  = tk.StringVar(value=_hostname())
        self.v_ip    = tk.StringVar()
        self.v_mask  = tk.StringVar(value="255.255.255.0")
        self.v_gw    = tk.StringVar()
        self.v_dns1  = tk.StringVar(value="8.8.8.8")
        self.v_dns2  = tk.StringVar(value="8.8.4.4")
        self.v_err   = tk.StringVar()
        self.v_stat  = tk.StringVar(value="")

        self._build_welcome()

    # â”€â”€ Widget yardÄ±mcÄ±larÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _font(self, sz=11, bold=False, mono=False):
        fam = self.FONT_MONO if mono else self.FONT_UI
        w   = "bold" if bold else "normal"
        return (fam, sz, w)

    def _lbl(self, p, text, fg=FGL, sz=11, bold=False, **kw):
        return tk.Label(p, text=text, bg=p.cget("bg"), fg=fg,
                        font=self._font(sz, bold), **kw)

    def _entry(self, p, var, mono=False, width=30):
        e = tk.Entry(
            p, textvariable=var,
            bg=INPUT, fg=FG, insertbackground=FG,
            relief="flat",
            font=self._font(12, mono=mono),
            highlightbackground=BDR, highlightcolor=ACT,
            highlightthickness=1, width=width,
            disabledbackground=CARD, disabledforeground=FGD,
        )
        return e

    def _divider(self, p):
        tk.Frame(p, bg=BDR, height=1).pack(fill="x", pady=(0, 16))

    def _section_lbl(self, p, text):
        tk.Label(p, text=text, bg=p.cget("bg"), fg=FGD,
                 font=self._font(9, bold=True),
                 anchor="w").pack(anchor="w", pady=(0, 8))

    # â”€â”€ KarÅŸÄ±lama ekranÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _build_welcome(self):
        self._wf = tk.Frame(self.r, bg=BG)
        self._wf.place(relx=0, rely=0, relwidth=1, relheight=1)

        c = tk.Frame(self._wf, bg=BG)
        c.place(relx=0.5, rely=0.5, anchor="center")

        # Logo â€” sadece ikon (metin yok)
        try:
            raw = tk.PhotoImage(
                file="/usr/share/calamares/branding/ankavm/ankavm_icon.png")
            img = raw.subsample(2, 2)
            lbl = tk.Label(c, image=img, bg=BG)
            lbl.image = img
            lbl.pack(pady=(0, 18))
        except Exception:
            tk.Label(c, text="OX", bg=BG, fg=FG,
                     font=self._font(42, bold=True)).pack(pady=(0, 18))

        tk.Label(c, text="ankavm Hypervisor",
                 bg=BG, fg=FG,
                 font=self._font(34, bold=True)).pack()
        tk.Label(c, text="v2.0  â€”  Kurulum SihirbazÄ±",
                 bg=BG, fg=FGM,
                 font=self._font(15)).pack(pady=(6, 0))

        tk.Frame(c, bg=BTN, height=2, width=80).pack(pady=22)

        tk.Label(c, text="Sunucunuzu yapÄ±landÄ±rmak iÃ§in aÅŸaÄŸÄ±daki adÄ±mlarÄ± tamamlayÄ±n.",
                 bg=BG, fg=FGL,
                 font=self._font(12)).pack(pady=(0, 32))

        btn = tk.Button(
            c, text="   Kuruluma BaÅŸla  â†’   ",
            bg=BTN, fg=FG, relief="flat",
            font=self._font(14, bold=True),
            activebackground=BTNH, activeforeground=FG,
            padx=28, pady=13, cursor="hand2",
            command=self._start_install,
        )
        btn.pack()
        btn.bind("<Enter>", lambda e: btn.config(bg=BTNH))
        btn.bind("<Leave>", lambda e: btn.config(bg=BTN))

        self.r.bind("<Return>", lambda e: self._start_install())

    def _start_install(self):
        self.r.unbind("<Return>")
        self._wf.destroy()
        self._build()
        self._refresh_iface()
        self.r.bind("<Return>", lambda e: self._go())

    # â”€â”€ UI kurulum â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _build(self):
        root = self.r

        # â”€â”€ Sol sidebar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sb = tk.Frame(root, bg=SIDEBAR, width=270)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        tk.Frame(sb, bg=SIDEBAR, height=52).pack()

        # Logo
        logo_f = tk.Frame(sb, bg=SIDEBAR)
        logo_f.pack(padx=32)
        try:
            raw = tk.PhotoImage(
                file="/usr/share/calamares/branding/ankavm/ankavm_icon.png")
            img = raw.subsample(2, 2)
            lbl = tk.Label(logo_f, image=img, bg=SIDEBAR, cursor="")
            lbl.image = img
            lbl.pack(anchor="center")
        except Exception:
            tk.Label(logo_f, text="OX", bg=SIDEBAR, fg=FG,
                     font=self._font(28, bold=True)).pack()

        self._lbl(sb, "Hypervisor",        fg=FGM, sz=13).pack(pady=(6, 0))
        self._lbl(sb, "2.0",               fg=FGD, sz=10).pack(pady=(1, 0))
        self._lbl(sb, "ankavm.local",        fg=FGD, sz=9 ).pack(pady=(0, 32))

        tk.Frame(sb, bg=BDR, height=1).pack(fill="x", padx=28, pady=(0, 20))

        # AdÄ±m gÃ¶stergesi
        STEPS = [
            ("1", "AÄŸ YapÄ±landÄ±rmasÄ±",  True ),
            ("2", "Dil & Klavye",       False),
            ("3", "Disk SeÃ§imi",        False),
            ("4", "KullanÄ±cÄ± AyarlarÄ±", False),
            ("5", "Kurulum",            False),
        ]
        for num, label, active in STEPS:
            row = tk.Frame(sb, bg=SIDEBAR)
            row.pack(fill="x", padx=28, pady=4)

            nbg = STEP_A if active else STEP_I
            nfg = FG     if active else FGD
            tk.Label(row, text=num, bg=nbg, fg=nfg,
                     font=self._font(10, bold=True),
                     width=2, padx=5, pady=3).pack(side="left", padx=(0, 14))
            tk.Label(row, text=label,
                     bg=SIDEBAR,
                     fg=FG if active else FGM,
                     font=self._font(11, bold=active),
                     anchor="w").pack(side="left")

        tk.Frame(sb, bg=SIDEBAR).pack(expand=True)
        self._lbl(sb, "Â© 2026 ankavm", fg=FGD, sz=9).pack(pady=18)

        # â”€â”€ SaÄŸ iÃ§erik â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        main = tk.Frame(root, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        # OrtalanmÄ±ÅŸ kapsayÄ±cÄ±
        wrap = tk.Frame(main, bg=BG)
        wrap.place(relx=0.5, rely=0.5, anchor="center")

        # Sayfa baÅŸlÄ±ÄŸÄ±
        self._lbl(wrap, "AÄŸ YapÄ±landÄ±rmasÄ±",
                  fg=FG, sz=22, bold=True).pack(anchor="w")
        self._lbl(wrap, "Kurulum iÃ§in aÄŸ baÄŸlantÄ±sÄ±nÄ± yapÄ±landÄ±rÄ±n.",
                  fg=FGM, sz=12).pack(anchor="w", pady=(4, 22))

        # â”€â”€ Kart â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        card = tk.Frame(wrap, bg=CARD, padx=34, pady=26,
                        highlightbackground=BDR, highlightthickness=1)
        card.pack(fill="x")

        # â€” AÄŸ arayÃ¼zÃ¼ seÃ§imi â€”
        self._section_lbl(card, "AÄ ARAYÃœZÃœ")
        iface_row = tk.Frame(card, bg=CARD)
        iface_row.pack(fill="x", pady=(0, 16))
        for iface in self.ifaces:
            tk.Radiobutton(
                iface_row, text=iface,
                variable=self.v_iface, value=iface,
                bg=CARD, fg=FGL, selectcolor=INPUT,
                activebackground=CARD, activeforeground=FG,
                font=self._font(12, mono=True),
                command=self._refresh_iface,
            ).pack(side="left", padx=(0, 24))

        self._divider(card)

        # â€” YapÄ±landÄ±rma tÃ¼rÃ¼ â€”
        self._section_lbl(card, "YAPILANDIRMA TÃœRÃœ")
        mode_row = tk.Frame(card, bg=CARD)
        mode_row.pack(fill="x", pady=(0, 16))
        for val, lbl_text in [(True, "DHCP  (Otomatik)"), (False, "Statik IP")]:
            tk.Radiobutton(
                mode_row, text=lbl_text,
                variable=self.v_dhcp, value=val,
                bg=CARD, fg=FGL, selectcolor=INPUT,
                activebackground=CARD, activeforeground=FG,
                font=self._font(12),
                command=self._refresh_mode,
            ).pack(side="left", padx=(0, 36))

        self._divider(card)

        # â€” Form alanlarÄ± â€”
        self._section_lbl(card, "AYARLAR")
        ff = tk.Frame(card, bg=CARD)
        ff.pack(fill="x")

        def frow(label, var, mono=False):
            r = tk.Frame(ff, bg=CARD)
            r.pack(fill="x", pady=(0, 10))
            tk.Label(r, text=label, bg=CARD, fg=FGL,
                     font=self._font(12),
                     width=17, anchor="w").pack(side="left")
            e = self._entry(r, var, mono=mono)
            e.pack(side="left", fill="x", expand=True, ipady=8, padx=(2, 0))
            return e

        self.e_host = frow("Hostname",   self.v_host)
        self.e_ip   = frow("IP Adresi",  self.v_ip,   mono=True)
        self.e_mask = frow("AÄŸ Maskesi", self.v_mask, mono=True)
        self.e_gw   = frow("AÄŸ GeÃ§idi", self.v_gw,   mono=True)
        self.e_dns1 = frow("DNS 1",      self.v_dns1, mono=True)
        self.e_dns2 = frow("DNS 2",      self.v_dns2, mono=True)

        # Durum satÄ±rÄ±
        tk.Label(card, textvariable=self.v_stat,
                 bg=CARD, fg=ACT, font=self._font(11),
                 anchor="w").pack(anchor="w", pady=(10, 0))

        # â”€â”€ Buton satÄ±rÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(18, 0))

        tk.Label(btn_row, textvariable=self.v_err,
                 bg=BG, fg=ERR, font=self._font(11)).pack(side="left")

        btn = tk.Button(
            btn_row, text="   Devam  â†’   ",
            bg=BTN, fg=FG, relief="flat",
            font=self._font(13, bold=True),
            activebackground=BTNH, activeforeground=FG,
            padx=22, pady=11, cursor="hand2",
            command=self._go,
        )
        btn.pack(side="right")
        btn.bind("<Enter>", lambda e: btn.config(bg=BTNH))
        btn.bind("<Leave>", lambda e: btn.config(bg=BTN))

        self._refresh_mode()

    # â”€â”€ Olay iÅŸleyiciler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _refresh_iface(self, *_):
        iface = self.v_iface.get()
        info  = _iface_info(iface)
        if info["ip"]:
            self.v_stat.set(f"  {iface}:  {info['ip']}  (aktif)")
        else:
            self.v_stat.set(f"  {iface}:  IP atanmamÄ±ÅŸ")
        # Static modda mevcut deÄŸerleri prefill
        if not self.v_dhcp.get() and info["ip"]:
            self.v_ip.set(info["ip"])
            self.v_mask.set(info["mask"])
            self.v_gw.set(info["gw"])
            self.v_dns1.set(info["dns"])

    def _refresh_mode(self, *_):
        static = not self.v_dhcp.get()
        for e in (self.e_ip, self.e_mask, self.e_gw, self.e_dns1, self.e_dns2):
            e.config(state="normal" if static else "disabled")
        if static:
            self._refresh_iface()

    # â”€â”€ DoÄŸrulama â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _valid(self):
        IP_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
        def ok_ip(s):
            m = IP_RE.match(s.strip())
            return bool(m) and all(0 <= int(g) <= 255 for g in m.groups())

        h = self.v_host.get().strip()
        if not h or not re.match(
                r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$",
                h):
            self.v_err.set("âŒ  GeÃ§ersiz hostname â€” harf, rakam ve tire kullanÄ±n")
            return False

        if not self.v_dhcp.get():
            for var, name in [
                (self.v_ip,   "IP adresi"),
                (self.v_mask, "aÄŸ maskesi"),
            ]:
                if not ok_ip(var.get()):
                    self.v_err.set(f"âŒ  GeÃ§ersiz {name}")
                    return False
            gw = self.v_gw.get().strip()
            if gw and not ok_ip(gw):
                self.v_err.set("âŒ  GeÃ§ersiz aÄŸ geÃ§idi")
                return False

        self.v_err.set("")
        return True

    # â”€â”€ Devam â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _go(self):
        if not self._valid():
            return
        cfg = {
            "interface": self.v_iface.get(),
            "mode":     "dhcp" if self.v_dhcp.get() else "static",
            "hostname":  self.v_host.get().strip(),
            "ip":        self.v_ip.get().strip()   if not self.v_dhcp.get() else "",
            "netmask":   self.v_mask.get().strip()  if not self.v_dhcp.get() else "",
            "gateway":   self.v_gw.get().strip()    if not self.v_dhcp.get() else "",
            "dns1":      self.v_dns1.get().strip()  if not self.v_dhcp.get() else "8.8.8.8",
            "dns2":      self.v_dns2.get().strip()  if not self.v_dhcp.get() else "8.8.4.4",
        }
        try:
            with open(OUT, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            self.v_err.set(f"âŒ  KayÄ±t hatasÄ±: {e}")
            return
        self.r.destroy()

    def run(self):
        self.r.mainloop()


if __name__ == "__main__":
    App().run()






