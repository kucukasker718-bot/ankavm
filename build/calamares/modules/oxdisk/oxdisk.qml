/* OXware Hypervisor — Disk Seçimi
   Calamares QML viewmodule — kpmcore kullanmaz, lsblk JSON okur.
   /tmp/oxware-disks.json  : oxware-start.sh tarafından oluşturulur
   /tmp/oxware-disk.json   : seçilen disk buraya yazılır (main.py okur) */

import QtQuick 2.10
import QtQuick.Controls 2.10
import QtQuick.Layouts 1.3

Item {
    id: root
    anchors.fill: parent

    // ── Calamares QML viewmodule interface ──────────────────────────────────
    property bool isNextEnabled:  selectedDisk !== ""
    property bool isBackEnabled:  true
    property bool isAtEnd:        true
    property bool isAtBeginning:  true

    property string selectedDisk: ""
    property var    diskModel:    []

    function onActivate() {
        loadDisks()
    }

    function onLeave() {
        saveDisk()
    }

    // ── Disk listesini yükle ────────────────────────────────────────────────
    function loadDisks() {
        try {
            var r = new XMLHttpRequest()
            r.open("GET", "file:///tmp/oxware-disks.json", false)
            r.send()
            if (r.responseText.trim()) {
                var data = JSON.parse(r.responseText)
                var disks = []
                var blockdevices = data.blockdevices || data.disks || data
                if (Array.isArray(blockdevices)) {
                    for (var i = 0; i < blockdevices.length; i++) {
                        var d = blockdevices[i]
                        disks.push({
                            "name":  "/dev/" + (d.name || d.kname || ""),
                            "size":  d.size || "?",
                            "model": d.model || d["model-name"] || "",
                            "tran":  d.tran  || ""
                        })
                    }
                }
                diskModel = disks
                listView.model = disks.length

                // Tek disk varsa otomatik seç
                if (disks.length === 1) {
                    selectedDisk = disks[0].name
                    listView.currentIndex = 0
                    statusLabel.text = "Disk otomatik seçildi: " + selectedDisk
                    statusLabel.color = "#1565C0"
                } else if (disks.length === 0) {
                    statusLabel.text = "⚠ Disk bulunamadı! /tmp/oxware-disks.json kontrol edin."
                    statusLabel.color = "#c62828"
                } else {
                    statusLabel.text = "Kurulum yapılacak diski seçin."
                    statusLabel.color = "#555555"
                }
            } else {
                statusLabel.text = "⚠ Disk listesi okunamadı. Lütfen geri dönüp tekrar deneyin."
                statusLabel.color = "#c62828"
            }
        } catch(e) {
            statusLabel.text = "⚠ Hata: " + e
            statusLabel.color = "#c62828"
        }
    }

    // ── Seçilen diski kaydet ────────────────────────────────────────────────
    function saveDisk() {
        if (!selectedDisk) return
        var cfg = { "disk": selectedDisk }
        try {
            var xhr = new XMLHttpRequest()
            xhr.open("PUT", "file:///tmp/oxware-disk.json", false)
            xhr.send(JSON.stringify(cfg, null, 2))
        } catch(e) {
            console.log("oxdisk: save error:", e)
        }
    }

    // ── UI ──────────────────────────────────────────────────────────────────
    ScrollView {
        anchors.fill: parent
        clip: true

        ColumnLayout {
            x: 40
            y: 30
            width: Math.min(root.width - 80, 620)
            spacing: 16

            Label {
                text: "Kurulum Diski Seçimi"
                font.pixelSize: 22
                font.bold: true
                Layout.fillWidth: true
            }
            Label {
                text: "OXware Hypervisor'ın kurulacağı diski seçin. SEÇİLEN DİSK TAMAMEN SİLİNECEKTİR."
                font.pixelSize: 12
                color: "#b71c1c"
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Rectangle { height: 1; color: "#cccccc"; Layout.fillWidth: true; Layout.topMargin: 4 }

            // Disk listesi
            ListView {
                id: listView
                Layout.fillWidth: true
                height: Math.min(diskModel.length * 72, 360)
                model: diskModel.length
                clip: true
                currentIndex: -1

                delegate: Rectangle {
                    width:  listView.width
                    height: 64
                    color:  listView.currentIndex === index ? "#E3F2FD" : (mouseArea.containsMouse ? "#F5F5F5" : "white")
                    border.color: listView.currentIndex === index ? "#1565C0" : "#dddddd"
                    border.width: listView.currentIndex === index ? 2 : 1
                    radius: 4

                    property var disk: diskModel[index] || {}

                    MouseArea {
                        id: mouseArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            listView.currentIndex = index
                            selectedDisk = disk.name
                            statusLabel.text = "Seçildi: " + disk.name + " (" + disk.size + ")"
                            statusLabel.color = "#1565C0"
                        }
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 12

                        // Disk ikonu
                        Rectangle {
                            width: 40; height: 40
                            color: listView.currentIndex === index ? "#1565C0" : "#546E7A"
                            radius: 4
                            Label {
                                anchors.centerIn: parent
                                text: disk.tran === "nvme" ? "NVMe" :
                                      disk.tran === "sata" ? "SSD" :
                                      disk.tran === "usb"  ? "USB" : "HDD"
                                font.pixelSize: 9
                                font.bold: true
                                color: "white"
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3
                            Label {
                                text: (disk.name || "") + "  —  " + (disk.size || "?")
                                font.pixelSize: 14
                                font.bold: true
                                color: "#1a1a1a"
                            }
                            Label {
                                text: disk.model || ("Disk " + (index + 1))
                                font.pixelSize: 12
                                color: "#555555"
                            }
                        }

                        // Seçim işareti
                        Label {
                            text: "✓"
                            font.pixelSize: 20
                            color: "#1565C0"
                            visible: listView.currentIndex === index
                        }
                    }
                }
            }

            Label {
                id: statusLabel
                text: ""
                font.pixelSize: 12
                font.italic: true
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }

            Item { height: 10 }
        }
    }
}
