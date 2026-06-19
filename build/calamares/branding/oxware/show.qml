/* OXware Hypervisor — Calamares installer slideshow
   Proxmox tarzı: koyu lacivert, Ubuntu font, modern layout */
import QtQuick 2.0
import calamares.slideshow 1.0

Presentation {
    id: presentation
    timer.interval: 6000

    // ── Slayt 1: Karşılama ────────────────────────────────────────────────────
    Slide {
        anchors.fill: parent

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#080f1e" }
                GradientStop { position: 1.0; color: "#0a1628" }
            }
        }

        Column {
            anchors.centerIn: parent
            spacing: 20

            Image {
                source: "oxware_logo.png"
                height: 80
                fillMode: Image.PreserveAspectFit
                anchors.horizontalCenter: parent.horizontalCenter
                smooth: true
                mipmap: true
            }

            Text {
                text: "OXware Hypervisor 2.0"
                color: "#ffffff"
                font.family: "Ubuntu"
                font.pixelSize: 32
                font.weight: Font.Light
                letterSpacing: 0.5
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Rectangle {
                width: 64; height: 2
                color: "#1565c0"
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Text {
                text: "KVM · QEMU · libvirt · noVNC"
                color: "#4a7ea0"
                font.family: "Ubuntu"
                font.pixelSize: 14
                letterSpacing: 2.5
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Item { width: 1; height: 8 }

            Text {
                text: "Sistem kuruluyor, lütfen bekleyin…"
                color: "#3d6a8a"
                font.family: "Ubuntu"
                font.pixelSize: 13
                anchors.horizontalCenter: parent.horizontalCenter
            }
        }
    }

    // ── Slayt 2: Yüksek Performans ────────────────────────────────────────────
    Slide {
        anchors.fill: parent

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#080f1e" }
                GradientStop { position: 1.0; color: "#0a1628" }
            }
        }

        Column {
            anchors.centerIn: parent
            spacing: 18
            width: 560

            Image {
                source: "oxware_icon.png"
                height: 44
                fillMode: Image.PreserveAspectFit
                anchors.horizontalCenter: parent.horizontalCenter
                smooth: true
                mipmap: true
            }

            Text {
                text: "Yüksek Performans Sanallaştırma"
                color: "#5b9bd5"
                font.family: "Ubuntu"
                font.pixelSize: 24
                font.weight: Font.Medium
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Rectangle {
                width: 64; height: 2
                color: "#1565c0"
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Text {
                text: "KVM donanım hızlandırması ile fiziksel sunucunuzu\ntam kapasite sanal makine ortamına dönüştürün."
                color: "#8ab0cc"
                font.family: "Ubuntu"
                font.pixelSize: 14
                lineHeight: 1.6
                horizontalAlignment: Text.AlignHCenter
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Item { width: 1; height: 4 }

            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 10

                Repeater {
                    model: [
                        "   CPU pinning ve NUMA desteği",
                        "   VirtIO ağ / disk sürücüleri",
                        "   PCIe passthrough — GPU, NIC",
                        "   Anlık snapshot ve klonlama"
                    ]
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 0

                        Rectangle {
                            width: 4; height: 4; radius: 2
                            color: "#1565c0"
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Text {
                            text: modelData
                            color: "#6a9ab8"
                            font.family: "Ubuntu"
                            font.pixelSize: 13
                            leftPadding: 10
                        }
                    }
                }
            }
        }
    }

    // ── Slayt 3: Web Paneli ───────────────────────────────────────────────────
    Slide {
        anchors.fill: parent

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#080f1e" }
                GradientStop { position: 1.0; color: "#0a1628" }
            }
        }

        Column {
            anchors.centerIn: parent
            spacing: 18
            width: 560

            Image {
                source: "oxware_icon.png"
                height: 44
                fillMode: Image.PreserveAspectFit
                anchors.horizontalCenter: parent.horizontalCenter
                smooth: true
                mipmap: true
            }

            Text {
                text: "Web Tabanlı Yönetim Paneli"
                color: "#5b9bd5"
                font.family: "Ubuntu"
                font.pixelSize: 24
                font.weight: Font.Medium
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Rectangle {
                width: 64; height: 2
                color: "#1565c0"
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Text {
                text: "Tüm sanal makinelerinizi tarayıcıdan\nhızlı ve güvenli şekilde yönetin."
                color: "#8ab0cc"
                font.family: "Ubuntu"
                font.pixelSize: 14
                lineHeight: 1.6
                horizontalAlignment: Text.AlignHCenter
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Item { width: 1; height: 4 }

            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 10

                Repeater {
                    model: [
                        "   HTTPS güvenli web arayüzü",
                        "   Gerçek zamanlı kaynak izleme",
                        "   noVNC konsol erişimi",
                        "   WiseCP / WHMCS entegrasyonu"
                    ]
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter

                        Rectangle {
                            width: 4; height: 4; radius: 2
                            color: "#1565c0"
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Text {
                            text: modelData
                            color: "#6a9ab8"
                            font.family: "Ubuntu"
                            font.pixelSize: 13
                            leftPadding: 10
                        }
                    }
                }
            }
        }
    }

    // ── Slayt 4: Güvenlik ─────────────────────────────────────────────────────
    Slide {
        anchors.fill: parent

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#080f1e" }
                GradientStop { position: 1.0; color: "#0a1628" }
            }
        }

        Column {
            anchors.centerIn: parent
            spacing: 18
            width: 560

            Image {
                source: "oxware_icon.png"
                height: 44
                fillMode: Image.PreserveAspectFit
                anchors.horizontalCenter: parent.horizontalCenter
                smooth: true
                mipmap: true
            }

            Text {
                text: "Kurumsal Güvenlik"
                color: "#5b9bd5"
                font.family: "Ubuntu"
                font.pixelSize: 24
                font.weight: Font.Medium
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Rectangle {
                width: 64; height: 2
                color: "#1565c0"
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Text {
                text: "İki faktörlü doğrulama, şifreli iletişim\nve rol tabanlı erişim kontrolü."
                color: "#8ab0cc"
                font.family: "Ubuntu"
                font.pixelSize: 14
                lineHeight: 1.6
                horizontalAlignment: Text.AlignHCenter
                anchors.horizontalCenter: parent.horizontalCenter
            }

            Item { width: 1; height: 4 }

            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 10

                Repeater {
                    model: [
                        "   TOTP iki faktörlü doğrulama",
                        "   TLS 1.2+  zorunlu şifreleme",
                        "   PBKDF2 şifre hashleme",
                        "   API anahtarı yönetimi"
                    ]
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter

                        Rectangle {
                            width: 4; height: 4; radius: 2
                            color: "#1565c0"
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Text {
                            text: modelData
                            color: "#6a9ab8"
                            font.family: "Ubuntu"
                            font.pixelSize: 13
                            leftPadding: 10
                        }
                    }
                }
            }
        }
    }
}
