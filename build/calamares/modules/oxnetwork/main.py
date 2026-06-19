#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ankavm AÄŸ YapÄ±landÄ±rmasÄ± â€” Calamares Python viewmodule
Proxmox VE tarzÄ±: live sistem aÄŸÄ±nÄ± Calamares iÃ§inde yapÄ±landÄ±rÄ±r.
"""
import subprocess, re
import libcalamares
from libcalamaresui import ViewStep
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QLineEdit, QRadioButton, QFrame, QComboBox)
from PyQt5.QtCore import Qt

# â”€â”€ AÄŸ yardÄ±mcÄ±larÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _ifaces():
    EXCL = re.compile(r'^(lo|vir|docker|br\d|veth|dummy|vbox|vmnet)')
    try:
        out = subprocess.check_output(['ip', '-o', 'link', 'show'], text=True,
                                      stderr=subprocess.DEVNULL)
        lst = []
        for ln in out.splitlines():
            m = re.match(r'\d+: ([^:@\s]+)', ln)
            if m:
                n = m.group(1).strip()
                if not EXCL.match(n):
                    lst.append(n)
        return lst or ['eth0']
    except Exception:
        return ['eth0']

def _iface_info(iface):
    info = {'ip': '', 'mask': '255.255.255.0', 'gw': '', 'dns': '8.8.8.8'}
    try:
        r = subprocess.check_output(['ip', '-o', '-4', 'addr', 'show', iface],
                                    text=True, stderr=subprocess.DEVNULL)
        m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)/(\d+)', r)
        if m:
            info['ip'] = m.group(1)
            pfx = int(m.group(2))
            n = (0xFFFFFFFF << (32 - pfx)) & 0xFFFFFFFF
            info['mask'] = '.'.join(str((n >> s) & 0xFF) for s in [24, 16, 8, 0])
    except Exception:
        pass
    try:
        r = subprocess.check_output(['ip', '-4', 'route', 'show', 'default'],
                                    text=True, stderr=subprocess.DEVNULL)
        m = re.search(r'default via (\d+\.\d+\.\d+\.\d+)', r)
        if m:
            info['gw'] = m.group(1)
    except Exception:
        pass
    try:
        with open('/etc/resolv.conf') as f:
            for ln in f:
                if ln.startswith('nameserver'):
                    info['dns'] = ln.split()[1]
                    break
    except Exception:
        pass
    return info

def _hostname():
    try:
        h = open('/etc/hostname').read().strip()
        return h if h else 'ankavm-node'
    except Exception:
        return 'ankavm-node'


# â”€â”€ Qt Widget â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class NetworkWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ifaces = _ifaces()
        self._setup_ui()
        self._refresh_iface()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        # ArayÃ¼z seÃ§imi
        row1 = QHBoxLayout()
        lbl1 = QLabel('AÄŸ ArayÃ¼zÃ¼:')
        lbl1.setMinimumWidth(130)
        self._iface_combo = QComboBox()
        for iface in self.ifaces:
            self._iface_combo.addItem(iface)
        self._iface_combo.currentTextChanged.connect(lambda _: self._refresh_iface())
        row1.addWidget(lbl1)
        row1.addWidget(self._iface_combo)
        row1.addStretch()
        layout.addLayout(row1)

        # YapÄ±landÄ±rma modu
        row2 = QHBoxLayout()
        lbl2 = QLabel('YapÄ±landÄ±rma:')
        lbl2.setMinimumWidth(130)
        self._dhcp_rb   = QRadioButton('DHCP (Otomatik)')
        self._static_rb = QRadioButton('Statik IP')
        self._dhcp_rb.setChecked(True)
        self._dhcp_rb.toggled.connect(self._refresh_mode)
        row2.addWidget(lbl2)
        row2.addWidget(self._dhcp_rb)
        row2.addWidget(self._static_rb)
        row2.addStretch()
        layout.addLayout(row2)

        # AyÄ±rÄ±cÄ±
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # Form alanlarÄ±
        form = QVBoxLayout()
        form.setSpacing(10)

        def make_row(label, placeholder=''):
            r = QHBoxLayout()
            l = QLabel(label)
            l.setMinimumWidth(130)
            e = QLineEdit()
            e.setPlaceholderText(placeholder)
            e.setMinimumWidth(280)
            e.setMaximumWidth(420)
            r.addWidget(l)
            r.addWidget(e)
            r.addStretch()
            form.addLayout(r)
            return e

        self._e_host = make_row('Hostname:',    'ankavm-node')
        self._e_host.setText(_hostname())
        self._e_ip   = make_row('IP Adresi:',   '192.168.1.100')
        self._e_mask = make_row('AÄŸ Maskesi:',  '255.255.255.0')
        self._e_mask.setText('255.255.255.0')
        self._e_gw   = make_row('AÄŸ GeÃ§idi:',   '192.168.1.1')
        self._e_dns1 = make_row('DNS 1:',        '8.8.8.8')
        self._e_dns1.setText('8.8.8.8')
        self._e_dns2 = make_row('DNS 2:',        '8.8.4.4')
        self._e_dns2.setText('8.8.4.4')

        layout.addLayout(form)

        # Durum
        self._status_lbl = QLabel('')
        self._status_lbl.setStyleSheet('color: #4a9a6a; font-style: italic;')
        layout.addWidget(self._status_lbl)

        layout.addStretch()
        self._refresh_mode()

    def _refresh_mode(self):
        is_static = self._static_rb.isChecked()
        for e in (self._e_ip, self._e_mask, self._e_gw):
            e.setEnabled(is_static)
        if is_static:
            self._refresh_iface()

    def _refresh_iface(self):
        iface = self._iface_combo.currentText()
        info  = _iface_info(iface)
        if info['ip']:
            self._status_lbl.setText(f'{iface}: {info["ip"]} (aktif)')
            if self._static_rb.isChecked():
                self._e_ip.setText(info['ip'])
                self._e_mask.setText(info['mask'])
                self._e_gw.setText(info['gw'])
                if info['dns']:
                    self._e_dns1.setText(info['dns'])
        else:
            self._status_lbl.setText(f'{iface}: baÄŸlantÄ± yok')

    def apply(self):
        """Live sisteme aÄŸ ayarlarÄ±nÄ± uygula â€” ViewStep.onLeave() tarafÄ±ndan Ã§aÄŸrÄ±lÄ±r."""
        iface    = self._iface_combo.currentText()
        hostname = self._e_host.text().strip() or 'ankavm-node'
        use_dhcp = self._dhcp_rb.isChecked()

        try:
            # Hostname
            subprocess.run(['hostnamectl', 'set-hostname', hostname],
                           capture_output=True, timeout=5)
            try:
                with open('/etc/hostname', 'w') as f:
                    f.write(hostname + '\n')
            except Exception:
                pass

            subprocess.run(['ip', 'link', 'set', iface, 'up'],
                           capture_output=True, timeout=5)

            if use_dhcp:
                # dhclient Ã¶nce, dhcpcd fallback
                r = subprocess.run(['dhclient', '-v', iface],
                                   capture_output=True, timeout=30)
                if r.returncode != 0:
                    subprocess.run(['dhcpcd', '-n', iface],
                                   capture_output=True, timeout=30)
            else:
                ip   = self._e_ip.text().strip()
                mask = self._e_mask.text().strip() or '255.255.255.0'
                gw   = self._e_gw.text().strip()
                dns1 = self._e_dns1.text().strip() or '8.8.8.8'
                dns2 = self._e_dns2.text().strip() or '8.8.4.4'
                if ip:
                    cidr = sum(bin(int(x)).count('1') for x in mask.split('.'))
                    subprocess.run(['ip', 'addr', 'flush', 'dev', iface],
                                   capture_output=True)
                    subprocess.run(['ip', 'addr', 'add', f'{ip}/{cidr}', 'dev', iface],
                                   capture_output=True)
                    if gw:
                        subprocess.run(['ip', 'route', 'add', 'default', 'via', gw],
                                       capture_output=True)
                    with open('/etc/resolv.conf', 'w') as f:
                        f.write(f'nameserver {dns1}\nnameserver {dns2}\n')

            # DeÄŸerleri ankavm_install iÃ§in sakla
            libcalamares.globalstorage.insert('oxnetwork_iface',    iface)
            libcalamares.globalstorage.insert('oxnetwork_hostname', hostname)
            libcalamares.globalstorage.insert('oxnetwork_dhcp',     use_dhcp)
            if not use_dhcp:
                libcalamares.globalstorage.insert('oxnetwork_ip',   self._e_ip.text().strip())
                libcalamares.globalstorage.insert('oxnetwork_gw',   self._e_gw.text().strip())
                libcalamares.globalstorage.insert('oxnetwork_dns1', self._e_dns1.text().strip())
                libcalamares.globalstorage.insert('oxnetwork_dns2', self._e_dns2.text().strip())

        except Exception as exc:
            libcalamares.utils.warning(f'oxnetwork.apply: {exc}')


# â”€â”€ ViewStep â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class OxNetworkStep(ViewStep):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._widget = NetworkWidget()

    def prettyName(self):
        return 'AÄŸ YapÄ±landÄ±rmasÄ±'

    def widget(self):
        return self._widget

    def isNextEnabled(self):
        return True

    def isBackEnabled(self):
        return True

    def isAtBeginning(self):
        return True

    def isAtEnd(self):
        return True

    def onLeave(self):
        self._widget.apply()

    def jobs(self):
        return []


def create_module():
    return OxNetworkStep()






