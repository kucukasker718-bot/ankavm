#!/bin/bash
# ankavm Network Restore â€” SSH koptuÄŸunda bridge'i geri al
# Console'dan veya rescue mode'dan Ã§alÄ±ÅŸtÄ±r:
#   curl -sSL https://raw.githubusercontent.com/ShinnAsukha/ankavm-hypervisor/main/scripts/restore-network.sh | sudo bash
# Veya local: sudo bash /opt/ankavm/scripts/restore-network.sh

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

[[ $EUID -ne 0 ]] && { echo -e "${RED}Root gerekli: sudo bash $0${NC}"; exit 1; }

echo -e "${CYAN}â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—"
echo -e "â•‘   ankavm Network Restore â€” Bridge'i Geri Al           â•‘"
echo -e "â•‘   SSH kopmuÅŸsa konsoldan Ã§alÄ±ÅŸtÄ±r.                    â•‘"
echo -e "â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•${NC}"
echo ""

# 1. ankavm bridge config'i kaldÄ±r
if [ -f /etc/netplan/60-ankavm-bridge.yaml ]; then
    rm -f /etc/netplan/60-ankavm-bridge.yaml
    echo -e "${GREEN}[âœ“]${NC} ankavm bridge config silindi"
fi

# 2. En son backup'Ä± bul + geri yÃ¼kle
LATEST_BAK=$(ls -td /etc/netplan.bak.* 2>/dev/null | head -1)
if [ -n "$LATEST_BAK" ] && [ -d "$LATEST_BAK" ]; then
    echo -e "${CYAN}[i]${NC} Backup bulundu: $LATEST_BAK"
    # Sadece backup'taki dosyalarÄ± al (mevcutlarÄ± override etme)
    for src in "$LATEST_BAK"/*.yaml; do
        [ -f "$src" ] || continue
        fname=$(basename "$src")
        # ankavm bridge dosyasÄ±nÄ± atla (zaten sildik)
        [ "$fname" = "60-ankavm-bridge.yaml" ] && continue
        cp "$src" "/etc/netplan/$fname"
        chmod 600 "/etc/netplan/$fname"
        echo -e "${GREEN}[âœ“]${NC} Geri yÃ¼klendi: /etc/netplan/$fname"
    done
else
    echo -e "${YELLOW}[!]${NC} Backup yok â€” minimal DHCP config oluÅŸturuluyor"
    # Detect primary iface from /sys (route gone, can't use ip route)
    PIFACE=""
    for i in /sys/class/net/e*/operstate /sys/class/net/en*/operstate; do
        [ -f "$i" ] || continue
        ifname=$(basename "$(dirname "$i")")
        [ "$ifname" = "lo" ] && continue
        [ "$(cat "$i")" = "up" ] && PIFACE="$ifname" && break
    done
    [ -z "$PIFACE" ] && PIFACE="ens160"

    cat > /etc/netplan/01-ankavm-restore.yaml << NP
network:
  version: 2
  ethernets:
    ${PIFACE}:
      dhcp4: true
      dhcp6: false
NP
    chmod 600 /etc/netplan/01-ankavm-restore.yaml
    echo -e "${GREEN}[âœ“]${NC} Minimal DHCP config: /etc/netplan/01-ankavm-restore.yaml ($PIFACE)"
fi

# 3. Bridge interface kaldÄ±r
if ip link show oxbr0 &>/dev/null 2>&1; then
    ip link set oxbr0 down 2>/dev/null || true
    ip link delete oxbr0 2>/dev/null || true
    echo -e "${GREEN}[âœ“]${NC} oxbr0 kaldÄ±rÄ±ldÄ±"
fi

# 4. netplan apply (try yok â€” kullanÄ±cÄ± zaten konsoldan koÅŸuyor, rollback gereksiz)
echo -e "${CYAN}[i]${NC} netplan apply yapÄ±lÄ±yor..."
netplan apply 2>&1 | tail -5

sleep 3

# 5. Durum
echo ""
echo -e "${CYAN}â•â•â•â•â•â•â•â•â•â•â•â•â•â•â• SonuÃ§ â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•${NC}"
ip addr show | grep -E "^[0-9]+:|inet " | head -20
echo ""
echo -e "${GREEN}[âœ“]${NC} Network restore tamamlandÄ±. SSH baÄŸlantÄ±nÄ± dene."
echo -e "${CYAN}[i]${NC} Servisi yeniden baÅŸlat: systemctl restart ankavm"






