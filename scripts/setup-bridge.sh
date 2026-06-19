#!/bin/bash
# ankavm Host Bridge Setup â€” opt-in, SSH-safe (netplan try ile 120s rollback)
# KullanÄ±m: sudo /opt/ankavm/scripts/setup-bridge.sh
set -uo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

[[ $EUID -ne 0 ]] && { echo -e "${RED}Root gerekli${NC}"; exit 1; }

echo -e "${YELLOW}âš  Host Bridge Kurulumu â€” SSH baÄŸlantÄ±n 10sn iÃ§in dÃ¼ÅŸebilir.${NC}"
echo -e "${YELLOW}âš  netplan try kullanÄ±lÄ±yor: 120sn iÃ§inde Enter basmazsan eski config geri gelir.${NC}"
read -p "Devam et? [e/H]: " -r
[[ ! $REPLY =~ ^[Ee]$ ]] && exit 0

PIFACE=$(ip route show default 2>/dev/null | awk '/^default/{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
[ -z "$PIFACE" ] && { echo -e "${RED}Interface tespit edilemedi${NC}"; exit 1; }
PIP=$(ip addr show "$PIFACE" 2>/dev/null | awk '/inet /{print $2; exit}')
PGW=$(ip route show default 2>/dev/null | awk '/^default/{for(i=1;i<=NF;i++) if($i=="via"){print $(i+1); exit}}')

echo -e "${GREEN}Bulundu: $PIFACE ($PIP) â†’ oxbr0, gw: $PGW${NC}"

cp -r /etc/netplan "/etc/netplan.bak.$(date +%s)"

cat > /etc/netplan/60-ankavm-bridge.yaml << NP
network:
  version: 2
  ethernets:
    ${PIFACE}:
      dhcp4: false
  bridges:
    oxbr0:
      interfaces: [${PIFACE}]
      dhcp4: false
      addresses: [${PIP}]
      routes:
        - to: default
          via: ${PGW}
      nameservers:
        addresses: [8.8.8.8, 1.1.1.1]
      parameters:
        stp: false
        forward-delay: 0
NP
chmod 600 /etc/netplan/60-ankavm-bridge.yaml

netplan try --timeout 120






