/* OXware Hypervisor — Ağ Yapılandırması
   Calamares QML viewmodule — Qt Quick 2.10 */

import QtQuick 2.10
import QtQuick.Controls 2.10
import QtQuick.Layouts 1.3

Item {
    id: root
    anchors.fill: parent

    // ── Calamares QML viewmodule interface ────────────────────────────────────
    property bool isNextEnabled:  true
    property bool isBackEnabled:  true
    property bool isAtEnd:        true
    property bool isAtBeginning:  true

    // Called by Calamares when step becomes active
    function onActivate() {
        readNetInfo()
    }

    // Called by Calamares when user clicks "Sonraki"
    function onLeave() {
        saveConfig()
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    function readNetInfo() {
        // Pre-fill interface name
        try {
            var r = new XMLHttpRequest()
            r.open("GET", "file:///tmp/oxware-iface.txt", false)
            r.send()
            if (r.responseText.trim()) {
                ifaceField.text = r.responseText.trim()
            }
        } catch(e) {}

        // Pre-fill current IP info
        try {
            var r2 = new XMLHttpRequest()
            r2.open("GET", "file:///tmp/oxware-netinfo.json", false)
            r2.send()
            if (r2.responseText.trim()) {
                var info = JSON.parse(r2.responseText)
                if (info.ip) {
                    statusLabel.text = (info.iface || ifaceField.text) +
                                       ": " + info.ip + " (aktif)"
                    statusLabel.color = "#2e7d32"
                } else {
                    statusLabel.text = (info.iface || ifaceField.text) + ": bağlantı yok"
                    statusLabel.color = "#c62828"
                }
            }
        } catch(e) {}
    }

    function saveConfig() {
        var cfg = {
            "interface": ifaceField.text.trim()  || "eth0",
            "hostname":  hostnameField.text.trim() || "oxware-node",
            "mode":      dhcpRadio.checked ? "dhcp" : "static",
            "ip":        ipField.text.trim(),
            "netmask":   maskField.text.trim() || "255.255.255.0",
            "gateway":   gwField.text.trim(),
            "dns1":      dns1Field.text.trim() || "8.8.8.8",
            "dns2":      dns2Field.text.trim() || "8.8.4.4"
        }
        try {
            var xhr = new XMLHttpRequest()
            xhr.open("PUT", "file:///tmp/oxnetwork.json", false)
            xhr.send(JSON.stringify(cfg, null, 2))
        } catch(e) {
            console.log("oxnetwork: config save error:", e)
        }
    }

    // ── UI ────────────────────────────────────────────────────────────────────

    ScrollView {
        anchors.fill: parent
        clip: true

        ColumnLayout {
            x: 40
            y: 30
            width: Math.min(root.width - 80, 580)
            spacing: 14

            // Başlık
            Label {
                text: "Ağ Yapılandırması"
                font.pixelSize: 20
                font.bold: true
                Layout.fillWidth: true
            }
            Label {
                text: "Kurulumdan sonra sisteme uygulanacak ağ ayarları."
                font.pixelSize: 12
                color: "#777777"
                Layout.fillWidth: true
            }

            Rectangle { height: 1; color: "#cccccc"; Layout.fillWidth: true; Layout.topMargin: 4 }

            // Hostname
            RowLayout {
                Layout.fillWidth: true
                Label { text: "Hostname:"; Layout.minimumWidth: 130; font.pixelSize: 13 }
                TextField {
                    id: hostnameField
                    text: "oxware-node"
                    placeholderText: "oxware-node"
                    Layout.fillWidth: true
                    font.pixelSize: 13
                }
            }

            // Ağ arayüzü
            RowLayout {
                Layout.fillWidth: true
                Label { text: "Ağ Arayüzü:"; Layout.minimumWidth: 130; font.pixelSize: 13 }
                TextField {
                    id: ifaceField
                    text: "eth0"
                    placeholderText: "eth0"
                    Layout.fillWidth: true
                    font.pixelSize: 13
                }
            }

            Rectangle { height: 1; color: "#cccccc"; Layout.fillWidth: true }

            // Yapılandırma türü
            RowLayout {
                Layout.fillWidth: true
                Label { text: "Yapılandırma:"; Layout.minimumWidth: 130; font.pixelSize: 13 }
                RadioButton {
                    id: dhcpRadio
                    text: "DHCP (Otomatik)"
                    checked: true
                    font.pixelSize: 13
                }
                RadioButton {
                    id: staticRadio
                    text: "Statik IP"
                    font.pixelSize: 13
                }
            }

            // IP adresi (sadece statik modda)
            RowLayout {
                Layout.fillWidth: true
                visible: staticRadio.checked
                Label { text: "IP Adresi:"; Layout.minimumWidth: 130; font.pixelSize: 13 }
                TextField {
                    id: ipField
                    placeholderText: "192.168.1.100"
                    Layout.fillWidth: true
                    font.pixelSize: 13
                    enabled: staticRadio.checked
                }
            }

            // Ağ Maskesi
            RowLayout {
                Layout.fillWidth: true
                visible: staticRadio.checked
                Label { text: "Ağ Maskesi:"; Layout.minimumWidth: 130; font.pixelSize: 13 }
                TextField {
                    id: maskField
                    text: "255.255.255.0"
                    placeholderText: "255.255.255.0"
                    Layout.fillWidth: true
                    font.pixelSize: 13
                    enabled: staticRadio.checked
                }
            }

            // Ağ Geçidi
            RowLayout {
                Layout.fillWidth: true
                visible: staticRadio.checked
                Label { text: "Ağ Geçidi:"; Layout.minimumWidth: 130; font.pixelSize: 13 }
                TextField {
                    id: gwField
                    placeholderText: "192.168.1.1"
                    Layout.fillWidth: true
                    font.pixelSize: 13
                    enabled: staticRadio.checked
                }
            }

            Rectangle { height: 1; color: "#cccccc"; Layout.fillWidth: true }

            // DNS 1
            RowLayout {
                Layout.fillWidth: true
                Label { text: "DNS 1:"; Layout.minimumWidth: 130; font.pixelSize: 13 }
                TextField {
                    id: dns1Field
                    text: "8.8.8.8"
                    placeholderText: "8.8.8.8"
                    Layout.fillWidth: true
                    font.pixelSize: 13
                }
            }

            // DNS 2
            RowLayout {
                Layout.fillWidth: true
                Label { text: "DNS 2:"; Layout.minimumWidth: 130; font.pixelSize: 13 }
                TextField {
                    id: dns2Field
                    text: "8.8.4.4"
                    placeholderText: "8.8.4.4"
                    Layout.fillWidth: true
                    font.pixelSize: 13
                }
            }

            // Durum etiketi
            Label {
                id: statusLabel
                text: ""
                font.pixelSize: 12
                font.italic: true
                Layout.fillWidth: true
                Layout.topMargin: 4
            }

            Item { height: 20 }
        }
    }
}
