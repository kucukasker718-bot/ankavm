#!/bin/bash
# ============================================================
# ankavm Hypervisor â€” Tam KaldÄ±rma Scripti
# Sistemi sÄ±fÄ±rdan kaldÄ±rÄ±r, temiz kurulum iÃ§in hazÄ±rlar
# ============================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; WHITE='\033[1;37m'; NC='\033[0m'

log() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }
step() { echo -e "\n${CYAN}â”â”â” $1 â”â”â”${NC}"; }
info() { echo -e "${BLUE}[i]${NC} $1"; }

[[ $EUID -ne 0 ]] && err "Root yetkisi gerekli: sudo bash uninstall.sh"

clear
echo -e "${RED}"
cat << 'BANNER'
 â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•— â–ˆâ–ˆâ•— â–ˆâ–ˆâ•—â–ˆâ–ˆâ•— â–ˆâ–ˆâ•— â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•— â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•— â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•—
 â–ˆâ–ˆâ•”â•â•â•â–ˆâ–ˆâ•—â•šâ–ˆâ–ˆâ•—â–ˆâ–ˆâ•”â•â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â•â•â–ˆâ–ˆâ•—â–ˆâ–ˆâ•”â•â•â–ˆâ–ˆâ•—â–ˆâ–ˆâ•”â•â•â•â•â•
 â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•‘ â•šâ–ˆâ–ˆâ–ˆâ•”â• â–ˆâ–ˆâ•‘ â–ˆâ•— â–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•”â•â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•—
 â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•”â–ˆâ–ˆâ•— â–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ•—â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â•â•â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â•â•â–ˆâ–ˆâ•—â–ˆâ–ˆâ•”â•â•â•
 â•šâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•”â•â–ˆâ–ˆâ•”â• â–ˆâ–ˆâ•—â•šâ–ˆâ–ˆâ–ˆâ•”â–ˆâ–ˆâ–ˆâ•”â•â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•—
 â•šâ•â•â•â•â•â• â•šâ•â• â•šâ•â• â•šâ•â•â•â•šâ•â•â• â•šâ•â• â•šâ•â•â•šâ•â• â•šâ•â•â•šâ•â•â•â•â•â•â•
BANNER
echo -e "${WHITE} Hypervisor Management System â€” TAM KALDIRMA${NC}"
echo -e "${RED} Bu iÅŸlem ankavm'i tamamen sistemden siler!${NC}"
echo ""

# â”€â”€ UyarÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo -e "${RED}â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—"
echo -e "â•‘ WARN DÄ°KKAT â€” AÅŸaÄŸÄ±dakiler silinecek: â•‘"
echo -e "â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£"
echo -e "â•‘${NC} â€¢ ankavm servisi ve tÃ¼m dosyalarÄ± ${RED}â•‘"
echo -e "â•‘${NC} â€¢ /opt/ankavm/ (uygulama + git repo) ${RED}â•‘"
echo -e "â•‘${NC} â€¢ /etc/ankavm/ (konfigÃ¼rasyon + SSL sertifikasÄ±) ${RED}â•‘"
echo -e "â•‘${NC} â€¢ /var/log/ankavm/ (loglar) ${RED}â•‘"
echo -e "â•‘${NC} â€¢ ox, oxupdate CLI komutlarÄ± ${RED}â•‘"
echo -e "â•‘${NC} â€¢ Fail2ban ankavm kurallarÄ± ${RED}â•‘"
echo -e "â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£"
echo -e "â•‘${NC} Sanal Makineler (VM'ler) ETKÄ°LENMEZ. ${RED}â•‘"
echo -e "â•‘${NC} KVM/libvirt kurulumu ETKÄ°LENMEZ. ${RED}â•‘"
echo -e "â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•${NC}"
echo ""
echo -e "${WHITE}Devam etmek istediÄŸine emin misin?${NC}"
read -p "Evet, tamamen kaldÄ±r [EVET yaz / Enter ile iptal]: " -r CONFIRM
if [[ "$CONFIRM" != "EVET" ]]; then
 echo "Ä°ptal edildi."
 exit 0
fi

# â”€â”€ Veri dizini sorusu â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo ""
echo -e "${YELLOW}Lisans aktivasyon kayÄ±tlarÄ± ve ISO dizini (/var/lib/ankavm/) silinsin mi?${NC}"
echo -e "${BLUE}[E] Evet, her ÅŸeyi sil (tam temizlik)${NC}"
echo -e "${BLUE}[H] HayÄ±r, veriyi koru (ISO'lar, aktivasyon loglarÄ±)${NC}"
read -p "SeÃ§im [E/H]: " -r DELETE_DATA

# â”€â”€ 1. Servis Durdur ve Devre DÄ±ÅŸÄ± BÄ±rak â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "1. Servis Durduruluyor"
if systemctl is-active --quiet ankavm 2>/dev/null; then
 systemctl stop ankavm
 log "ankavm servisi durduruldu"
else
 info "ankavm servisi zaten Ã§alÄ±ÅŸmÄ±yor"
fi

if systemctl is-enabled --quiet ankavm 2>/dev/null; then
 systemctl disable ankavm
 log "ankavm servisi devre dÄ±ÅŸÄ± bÄ±rakÄ±ldÄ±"
fi

# â”€â”€ 2. Service DosyasÄ±nÄ± Sil â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "2. Systemd Servis DosyasÄ± Siliniyor"
if [ -f /etc/systemd/system/ankavm.service ]; then
 rm -f /etc/systemd/system/ankavm.service
 systemctl daemon-reload
 log "ankavm.service silindi"
else
 info "Servis dosyasÄ± bulunamadÄ± (zaten silinmiÅŸ)"
fi

# â”€â”€ 3. Uygulama Dizini â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "3. Uygulama DosyalarÄ± Siliniyor"

# /opt/ankavm altÄ±ndaki tÃ¼m ankavm klasÃ¶rleri
for DIR in /opt/ankavm /opt/ankavm-src; do
 if [ -d "$DIR" ]; then
 rm -rf "$DIR"
 log "Silindi: $DIR"
 fi
done

# â”€â”€ 4. KonfigÃ¼rasyon â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "4. KonfigÃ¼rasyon Siliniyor"
if [ -d /etc/ankavm ]; then
 rm -rf /etc/ankavm
 log "Silindi: /etc/ankavm"
fi

# â”€â”€ 5. Loglar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "5. Log DosyalarÄ± Siliniyor"
if [ -d /var/log/ankavm ]; then
 rm -rf /var/log/ankavm
 log "Silindi: /var/log/ankavm"
fi

# â”€â”€ 6. Veri Dizini (isteÄŸe baÄŸlÄ±) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "6. Veri Dizini"
if [ -d /var/lib/ankavm ]; then
 if [[ "$DELETE_DATA" =~ ^[Ee]$ ]]; then
 rm -rf /var/lib/ankavm
 log "Silindi: /var/lib/ankavm (ISO'lar, lisans kayÄ±tlarÄ± dahil)"
 else
 warn "Korundu: /var/lib/ankavm (ISO'lar ve aktivasyon kayÄ±tlarÄ±)"
 info "Temiz kurulum sonrasÄ± veri kurtarmak iÃ§in bu dizini kontrol et"
 fi
fi

# â”€â”€ 7. CLI AraÃ§larÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "7. CLI KomutlarÄ± KaldÄ±rÄ±lÄ±yor"
for CMD in /usr/local/bin/ox /usr/local/bin/oxupdate; do
 if [ -f "$CMD" ]; then
 rm -f "$CMD"
 log "Silindi: $CMD"
 fi
done

# â”€â”€ 8. Fail2ban KurallarÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "8. Fail2ban ankavm KurallarÄ± KaldÄ±rÄ±lÄ±yor"
rm -f /etc/fail2ban/jail.d/ankavm.conf 2>/dev/null
rm -f /etc/fail2ban/filter.d/ankavm-web.conf 2>/dev/null
if systemctl is-active --quiet fail2ban 2>/dev/null; then
 systemctl reload fail2ban 2>/dev/null || true
 log "Fail2ban yeniden yÃ¼klendi"
fi
log "ankavm fail2ban kurallarÄ± kaldÄ±rÄ±ldÄ±"

# â”€â”€ 9. UFW KurallarÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "9. Firewall KurallarÄ±"
echo ""
echo -e "${YELLOW}ankavm iÃ§in aÃ§Ä±lmÄ±ÅŸ UFW portlarÄ± kaldÄ±rÄ±lsÄ±n mÄ±?${NC}"
echo -e " Port 8006 (ankavm Web UI)"
echo -e " Port 5900-5999 (VNC)"
echo -e " Port 6080 (noVNC)"
echo -e "${BLUE}(SSH 22 dokunulmaz)${NC}"
read -p "UFW kurallarÄ±nÄ± kaldÄ±r? [e/H]: " -r DEL_UFW
if [[ "$DEL_UFW" =~ ^[Ee]$ ]]; then
 ufw delete allow 8006/tcp 2>/dev/null || true
 ufw delete allow 5900:5999/tcp 2>/dev/null || true
 ufw delete allow 6080/tcp 2>/dev/null || true
 log "UFW ankavm kurallarÄ± kaldÄ±rÄ±ldÄ±"
else
 info "UFW kurallarÄ± korundu"
fi

# â”€â”€ 10. Python Cache TemizliÄŸi â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "10. Python Cache TemizliÄŸi"
find /tmp -name "*.pyc" -delete 2>/dev/null || true
find /tmp -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
log "Python cache temizlendi"

# â”€â”€ 11. Cloudflare Tunnel Servisleri (rapor #34 ghost persistence fix) â”€â”€â”€â”€â”€
step "11. Cloudflare Tunnel Servisleri KaldÄ±rÄ±lÄ±yor"
for svc_file in /etc/systemd/system/ankavm-tunnel-*.service; do
 [ -f "$svc_file" ] || continue
 svc_name=$(basename "$svc_file" .service)
 systemctl stop "$svc_name" 2>/dev/null || true
 systemctl disable "$svc_name" 2>/dev/null || true
 rm -f "$svc_file"
 log "KaldÄ±rÄ±ldÄ±: $svc_name"
done
systemctl daemon-reload 2>/dev/null || true

# â”€â”€ 12. Polkit KurallarÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "12. Polkit KurallarÄ± KaldÄ±rÄ±lÄ±yor"
if [ -f /etc/polkit-1/rules.d/50-libvirt-ankavm.rules ]; then
 rm -f /etc/polkit-1/rules.d/50-libvirt-ankavm.rules
 log "Silindi: /etc/polkit-1/rules.d/50-libvirt-ankavm.rules"
fi

# â”€â”€ 13. Cron / Systemd Timer TemizliÄŸi â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "13. Cron/Timer TemizliÄŸi"
# ankavm crontab giriÅŸlerini temizle
crontab -l 2>/dev/null | grep -v "ankavm" | crontab - 2>/dev/null || true
for timer in /etc/systemd/system/ankavm*.timer; do
 [ -f "$timer" ] || continue
 timer_name=$(basename "$timer")
 systemctl stop "$timer_name" 2>/dev/null || true
 systemctl disable "$timer_name" 2>/dev/null || true
 rm -f "$timer"
done
log "Cron/timer temizlendi"

# â”€â”€ SonuÃ§ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo ""
echo -e "${GREEN}â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—"
echo -e "â•‘ ankavm baÅŸarÄ±yla kaldÄ±rÄ±ldÄ±! â•‘"
echo -e "â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£"
echo -e "â•‘${NC} ${GREEN}â•‘"
echo -e "â•‘${NC} OK Servis durduruldu ve devre dÄ±ÅŸÄ± bÄ±rakÄ±ldÄ± ${GREEN}â•‘"
echo -e "â•‘${NC} OK Uygulama dosyalarÄ± silindi ${GREEN}â•‘"
echo -e "â•‘${NC} OK KonfigÃ¼rasyon silindi ${GREEN}â•‘"
echo -e "â•‘${NC} OK Loglar silindi ${GREEN}â•‘"
echo -e "â•‘${NC} OK CLI araÃ§larÄ± kaldÄ±rÄ±ldÄ± ${GREEN}â•‘"
echo -e "â•‘${NC} ${GREEN}â•‘"
echo -e "â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£"
echo -e "â•‘${NC} KVM/libvirt ve sanal makineler etkilenmedi. ${GREEN}â•‘"
echo -e "â•‘${NC} ${GREEN}â•‘"
echo -e "â•‘${NC} Temiz kurulum iÃ§in: ${GREEN}â•‘"
echo -e "â•‘${NC} ${CYAN}curl -fsSL https://raw.githubusercontent.com/ ${GREEN}â•‘"
echo -e "â•‘${NC} ${CYAN}ShinnAsukha/ankavm-hypervisor/master/install.sh ${GREEN}â•‘"
echo -e "â•‘${NC} ${CYAN}| sudo bash${NC} ${GREEN}â•‘"
echo -e "â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•${NC}"
echo ""






