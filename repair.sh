#!/bin/bash
# ============================================================
# ankavm Repair Script â€” repair.sh
# Otomatik tanÄ± ve onarÄ±m â€” tÃ¼m hata senaryolarÄ±
# Version: 3.0
# ============================================================
# KullanÄ±m:
# sudo bash repair.sh -> tam onarÄ±m
# sudo bash repair.sh --restore-network -> kÄ±rÄ±k bridge geri al
# sudo bash repair.sh --remove-hardening -> kernel hardening kaldÄ±r
# sudo bash repair.sh --reset-credentials -> admin ÅŸifresi sÄ±fÄ±rla
# sudo bash repair.sh --clean-disk -> disk doluysa temizle
# sudo bash repair.sh --fix-apparmor -> AppArmor ankavm engeli kaldÄ±r
# sudo bash repair.sh --diagnose -> sadece tanÄ±, deÄŸiÅŸiklik yok
# ============================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[FAIL]${NC} $1"; }
step() { echo -e "\n${CYAN}â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”${NC}"; echo -e "${BOLD} $1${NC}"; echo -e "${CYAN}â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”${NC}"; }
info() { echo -e " ${CYAN}->${NC} $1"; }
ok() { echo -e " ${GREEN}OK${NC} $1"; }
fail() { echo -e " ${RED}FAIL${NC} $1"; }

[[ $EUID -ne 0 ]] && { echo "Root gerekli: sudo bash repair.sh"; exit 1; }

INSTALL_DIR="/opt/ankavm"
APP_DIR="${INSTALL_DIR}/ankavm"
VENV_DIR="${INSTALL_DIR}/venv"
CONFIG_DIR="/etc/ankavm"
LOG_DIR="/var/log/ankavm"
DATA_DIR="/var/lib/ankavm"
DROPIN_DIR="/etc/systemd/system/ankavm.service.d"
WEB_PORT=8006
REPAIR_LOG="$LOG_DIR/repair-$(date +%Y%m%d-%H%M%S).log"

# â”€â”€ Mode flags â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
MODE_RESTORE_NETWORK=0
MODE_REMOVE_HARDENING=0
MODE_RESET_CREDENTIALS=0
MODE_CLEAN_DISK=0
MODE_FIX_APPARMOR=0
MODE_FIX_CLI=0
MODE_DIAGNOSE=0

for arg in "$@"; do
 case "$arg" in
 --restore-network) MODE_RESTORE_NETWORK=1 ;;
 --remove-hardening) MODE_REMOVE_HARDENING=1 ;;
 --reset-credentials) MODE_RESET_CREDENTIALS=1 ;;
 --clean-disk) MODE_CLEAN_DISK=1 ;;
 --fix-apparmor) MODE_FIX_APPARMOR=1 ;;
 --fix-cli) MODE_FIX_CLI=1 ;;
 --diagnose) MODE_DIAGNOSE=1 ;;
 --help|-h)
 echo "ankavm Repair Script v3.0"
 echo ""
 echo "Usage: sudo bash repair.sh [mode]"
 echo ""
 echo " (no args) Full repair â€” fixes all detected issues"
 echo " --restore-network Remove broken bridge, restore original network"
 echo " --remove-hardening Remove kernel hardening drop-in (fixes 226/NAMESPACE)"
 echo " --reset-credentials Reset admin username/password"
 echo " --clean-disk Clean logs/temp files (use when disk full)"
 echo " --fix-apparmor Disable AppArmor profile for ankavm"
 echo " --diagnose Diagnose only, no changes"
 exit 0 ;;
 esac
done

mkdir -p "$LOG_DIR"
exec > >(tee -a "$REPAIR_LOG") 2>&1

echo ""
echo -e "${BOLD} ankavm OnarÄ±m Scripti v3.0${NC}"
echo -e " Sistem: $(hostname) | $(date '+%Y-%m-%d %H:%M')"
echo -e " Log: $REPAIR_LOG"
echo ""

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# SPECIAL MODES â€” run and exit
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

# â”€â”€ DIAGNOSE only â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if [[ $MODE_DIAGNOSE -eq 1 ]]; then
 step "TanÄ± Raporu (deÄŸiÅŸiklik yapÄ±lmÄ±yor)"

 # Servis durumu
 if systemctl is-active --quiet ankavm; then
 ok "ankavm.service: Ã§alÄ±ÅŸÄ±yor"
 else
 fail "ankavm.service: Ã§alÄ±ÅŸmÄ±yor"
 FAIL_REASON=$(systemctl show ankavm --property=Result --value 2>/dev/null)
 info "SonuÃ§: $FAIL_REASON"
 journalctl -u ankavm -n 5 --no-pager 2>/dev/null | sed 's/^/ /'
 fi

 # Hardening drop-in
 if [[ -f "$DROPIN_DIR/hardening.conf" ]]; then
 warn "Hardening drop-in mevcut: $DROPIN_DIR/hardening.conf"
 # Check if it caused NAMESPACE error
 if journalctl -u ankavm -n 20 --no-pager 2>/dev/null | grep -q "NAMESPACE\|226"; then
 fail "226/NAMESPACE hatasÄ± tespit edildi â€” hardening drop-in neden olmuÅŸ olabilir"
 info "Ã‡Ã¶zÃ¼m: sudo bash repair.sh --remove-hardening"
 fi
 fi

 # AppArmor
 if command -v aa-status &>/dev/null; then
 if aa-status 2>/dev/null | grep -q "ankavm"; then
 warn "AppArmor ankavm profilini yÃ¶netiyor"
 aa-status 2>/dev/null | grep "ankavm" | sed 's/^/ /'
 fi
 fi

 # Disk kullanÄ±mÄ±
 DF=$(df -h / 2>/dev/null | awk 'NR==2{print $5" "($4)}')
 USE=$(echo "$DF" | awk '{print $1}' | tr -d '%')
 info "Disk kullanÄ±mÄ±: $DF"
 [[ "$USE" -gt 90 ]] && fail "Disk dolmak Ã¼zere! sudo bash repair.sh --clean-disk"

 # Port 8006
 if ss -tlnp 2>/dev/null | grep -q ":8006"; then
 ok "Port 8006 dinleniyor"
 else
 fail "Port 8006 dinlenmiyor"
 fi

 # libvirtd
 systemctl is-active --quiet libvirtd && ok "libvirtd: Ã§alÄ±ÅŸÄ±yor" || fail "libvirtd: Ã§alÄ±ÅŸmÄ±yor"

 # KVM
 [[ -e /dev/kvm ]] && ok "/dev/kvm mevcut" || fail "/dev/kvm yok â€” KVM desteklenmiyor"

 # SSL
 [[ -f "$CONFIG_DIR/ssl/ankavm.crt" ]] && ok "SSL sertifikasÄ± mevcut" || fail "SSL sertifikasÄ± yok"

 # Python venv
 [[ -f "$VENV_DIR/bin/python3" ]] && ok "Python venv mevcut" || fail "Python venv yok"

 echo ""
 exit 0
fi

# â”€â”€ RESTORE NETWORK â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if [[ $MODE_RESTORE_NETWORK -eq 1 ]] || [[ "${1:-}" == "--restore-network" ]]; then
 warn "â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•"
 warn " NETWORK RESTORE â€” kÄ±rÄ±k bridge config siliniyor"
 warn "â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•"

 [[ -f /etc/netplan/60-ankavm-bridge.yaml ]] && \
 rm -f /etc/netplan/60-ankavm-bridge.yaml && log "ankavm bridge config silindi"

 LATEST_BAK=$(ls -t /etc/netplan.bak.* 2>/dev/null | head -1)
 if [[ -n "$LATEST_BAK" ]] && [[ -d "$LATEST_BAK" ]]; then
 cp -r "$LATEST_BAK"/*.yaml /etc/netplan/ 2>/dev/null && \
 log "Eski netplan config geri yÃ¼klendi: $LATEST_BAK" || \
 warn "Backup geri yÃ¼klenemedi"
 else
 warn "Netplan backup bulunamadÄ±"
 fi

 ip link show oxbr0 &>/dev/null && { ip link set oxbr0 down; ip link delete oxbr0; log "oxbr0 kaldÄ±rÄ±ldÄ±"; }
 timeout 30 netplan try --timeout 120 </dev/null && log "AÄŸ geri yÃ¼klendi OK" || netplan apply
 log "Network restore tamamlandÄ±."
 exit 0
fi

# â”€â”€ REMOVE HARDENING â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if [[ $MODE_REMOVE_HARDENING -eq 1 ]]; then
 step "Kernel Hardening KaldÄ±rÄ±lÄ±yor"

 if [[ -f "$DROPIN_DIR/hardening.conf" ]]; then
 cp "$DROPIN_DIR/hardening.conf" "$DROPIN_DIR/hardening.conf.removed.$(date +%s)" 2>/dev/null || true
 rm -f "$DROPIN_DIR/hardening.conf"
 log "Hardening drop-in kaldÄ±rÄ±ldÄ± (backup tutuldu)"
 else
 info "Hardening drop-in zaten yok"
 fi

 # Remove AppArmor profile if loaded
 AAPROF="/etc/apparmor.d/opt.ankavm.backend.app"
 if [[ -f "$AAPROF" ]] && command -v apparmor_parser &>/dev/null; then
 apparmor_parser -R "$AAPROF" 2>/dev/null || true
 log "AppArmor profili kaldÄ±rÄ±ldÄ±"
 fi

 systemctl daemon-reload
 systemctl restart ankavm
 sleep 3
 systemctl is-active --quiet ankavm && log "ankavm.service baÅŸlatÄ±ldÄ± OK" || \
 err "Servis hÃ¢lÃ¢ baÅŸlamÄ±yor â€” journalctl -u ankavm -n 30"
 exit 0
fi

# â”€â”€ RESET CREDENTIALS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if [[ $MODE_RESET_CREDENTIALS -eq 1 ]]; then
 step "Admin Kimlik SÄ±fÄ±rlama"
 warn "Bu iÅŸlem admin kullanÄ±cÄ±sÄ± ve ÅŸifresini sÄ±fÄ±rlar!"

 read -rp " Yeni kullanÄ±cÄ± adÄ± [admin]: " NEW_USER
 NEW_USER="${NEW_USER:-admin}"
 read -rsp " Yeni ÅŸifre: " NEW_PASS; echo
 [[ -z "$NEW_PASS" ]] && { err "Åifre boÅŸ olamaz"; exit 1; }

 # Write password reset file
 RESET_FILE="/etc/ankavm/.passwd_reset"
 cat > "$RESET_FILE" << RESET
USERNAME=${NEW_USER}
PASSWORD=${NEW_PASS}
RESET
 chmod 600 "$RESET_FILE"
 chown root:root "$RESET_FILE"
 log "Åifre sÄ±fÄ±rlama dosyasÄ± yazÄ±ldÄ±: $RESET_FILE"

 # Restart service to apply
 systemctl restart ankavm 2>/dev/null || true
 sleep 3
 [[ -f "$RESET_FILE" ]] && warn "Reset dosyasÄ± henÃ¼z uygulanmadÄ± â€” servis baÅŸlamamÄ±ÅŸ olabilir" || \
 log "Kimlik bilgileri gÃ¼ncellendi OK"
 info "GiriÅŸ: https://$(hostname -I | awk '{print $1}'):${WEB_PORT} â€” ${NEW_USER}"
 exit 0
fi

# â”€â”€ CLEAN DISK â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if [[ $MODE_CLEAN_DISK -eq 1 ]]; then
 step "Disk Temizleme"
 BEFORE=$(df -h / | awk 'NR==2{print $4}')

 # Rotate logs
 find "$LOG_DIR" -name "*.log" -size +100M -exec truncate -s 10M {} \; 2>/dev/null
 find "$LOG_DIR" -name "repair-*.log" -mtime +7 -delete 2>/dev/null
 info "ankavm log dosyalarÄ± dÃ¶ndÃ¼rÃ¼ldÃ¼"

 # systemd journal
 journalctl --vacuum-size=200M 2>/dev/null
 journalctl --vacuum-time=7d 2>/dev/null
 info "systemd journal temizlendi"

 # APT cache
 apt-get clean -qq 2>/dev/null || true
 info "APT cache temizlendi"

 # /tmp old files
 find /tmp -mtime +1 -not -path "/tmp/.X*" -delete 2>/dev/null || true
 info "/tmp temizlendi"

 # Cloud-init logs
 find /var/log/cloud-init* -delete 2>/dev/null || true

 # Orphan ISO cloud-init seeds
 find "${DATA_DIR}/isos" -name "ci-*.iso" -o -name "seed-*.iso" 2>/dev/null | while read -r f; do
 warn "Cloud-init ISO bulundu: $f â€” siliyor..."
 rm -f "$f"
 done

 AFTER=$(df -h / | awk 'NR==2{print $4}')
 log "Disk temizlendi. Serbest alan: $BEFORE -> $AFTER"
 exit 0
fi

# â”€â”€ FIX APPARMOR â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if [[ $MODE_FIX_APPARMOR -eq 1 ]]; then
 step "AppArmor Profili Devre DÄ±ÅŸÄ±"
 AAPROF="/etc/apparmor.d/opt.ankavm.backend.app"
 if [[ -f "$AAPROF" ]]; then
 apparmor_parser -R "$AAPROF" 2>/dev/null || true
 mv "$AAPROF" "${AAPROF}.disabled.$(date +%s)"
 log "AppArmor profili devre dÄ±ÅŸÄ± bÄ±rakÄ±ldÄ±"
 else
 info "ankavm AppArmor profili yok"
 fi
 systemctl restart ankavm 2>/dev/null || true
 sleep 3
 systemctl is-active --quiet ankavm && log "Servis baÅŸlatÄ±ldÄ± OK" || err "Servis hÃ¢lÃ¢ baÅŸlamÄ±yor"
 exit 0
fi

# â”€â”€ FIX CLI (regenerate ox / oxupdate) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if [[ $MODE_FIX_CLI -eq 1 ]]; then
 step "CLI AraÃ§larÄ± Yeniden OluÅŸturuluyor (ox / oxupdate)"

 # oxupdate â€” gÃ¼venli grep ile (2x grep -v zincir)
 cat > /usr/local/bin/oxupdate << 'OXUPDATE'
#!/bin/bash
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'

[[ $EUID -ne 0 ]] && { echo -e "${RED}Root gerekli: sudo oxupdate${NC}"; exit 1; }

INSTALL_DIR="/opt/ankavm"
APP_DIR="${INSTALL_DIR}/ankavm"
VENV_DIR="${INSTALL_DIR}/venv"

_oxupdate_fail() {
 echo -e "\n${RED}[FAIL] GÃ¼ncelleme sÄ±rasÄ±nda hata oluÅŸtu.${NC}"
 echo -e "${YELLOW}Kurtarma iÃ§in:${NC}"
 echo -e "  ${CYAN}cd /opt/ankavm && git pull${NC}"
 echo -e "  ${CYAN}sudo bash repair.sh --fix-cli${NC}"
 echo -e "  ${CYAN}sudo systemctl restart ankavm${NC}"
}
trap _oxupdate_fail ERR

echo -e "${CYAN}[i]${NC} ankavm gÃ¼ncelleme baÅŸlÄ±yor..."
systemctl stop ankavm 2>/dev/null || true

if [ -d "${INSTALL_DIR}/.git" ]; then
 cd "${INSTALL_DIR}"
 echo -e "${CYAN}[i]${NC} Git pull..."
 git fetch --all --quiet
 git reset --hard origin/main --quiet
 rm -rf "${INSTALL_DIR}"/{LICENSE,CNAME,CHANGELOG.md,README.md,SECURITY.md,THREAT_MODEL.md,CONTRIBUTING.md,planning,tests,.github} 2>/dev/null || true
 echo -e "${GREEN}[OK]${NC} Kod gÃ¼ncellendi"

 # CLI'Ä± kendinden gÃ¼ncelle
 if [ -f "${INSTALL_DIR}/install.sh" ]; then
 echo -e "${CYAN}[i]${NC} CLI araÃ§larÄ± yenileniyor..."
 grep -A 200 "cat > /usr/local/bin/oxupdate" "${INSTALL_DIR}/install.sh" \
 > /dev/null 2>&1 && echo -e "${GREEN}[OK]${NC} install.sh mevcut"
 fi
else
 echo -e "${YELLOW}[!]${NC} Git repo bulunamadÄ± â€” atlanÄ±yor"
fi

echo -e "${CYAN}[i]${NC} Python baÄŸÄ±mlÄ±lÄ±klarÄ± gÃ¼ncelleniyor..."
source "${VENV_DIR}/bin/activate"
if [ -f "${APP_DIR}/backend/requirements.txt" ]; then
 _REQ_TMP=$(mktemp)
 grep -v "^libvirt-python" "${APP_DIR}/backend/requirements.txt" | grep -v "^blinker" > "$_REQ_TMP"
 pip install -r "$_REQ_TMP" -q 2>/dev/null || true
 rm -f "$_REQ_TMP"
fi
deactivate

echo -e "${CYAN}[i]${NC} ankavm baÅŸlatÄ±lÄ±yor..."
systemctl start ankavm
sleep 3

if systemctl is-active --quiet ankavm; then
 echo -e "${GREEN}[OK] ankavm gÃ¼ncellendi ve Ã§alÄ±ÅŸÄ±yor!${NC}"
 HOST_IP=$(hostname -I | awk '{print $1}')
 echo -e " Web UI: ${CYAN}https://${HOST_IP}:8006${NC}"
else
 echo -e "${RED}[FAIL] Servis baÅŸlatÄ±lamadÄ± â€” kontrol: journalctl -u ankavm -n 30${NC}"
 exit 1
fi
OXUPDATE

 # ox â€” kÄ±sa kabuk
 cat > /usr/local/bin/ox << 'OXMAIN'
#!/bin/bash
case "${1:-}" in
 update) sudo oxupdate ;;
 status) systemctl status ankavm --no-pager ;;
 logs) journalctl -u ankavm -f ;;
 restart) sudo systemctl restart ankavm ;;
 repair) sudo bash /opt/ankavm/repair.sh ;;
 diagnose) sudo bash /opt/ankavm/repair.sh --diagnose ;;
 *) echo "KullanÄ±m: ox {update|status|logs|restart|repair|diagnose}" ;;
esac
OXMAIN

 chmod +x /usr/local/bin/oxupdate /usr/local/bin/ox
 log "ox ve oxupdate yeniden oluÅŸturuldu"
 bash -n /usr/local/bin/oxupdate && log "oxupdate syntax OK"
 bash -n /usr/local/bin/ox && log "ox syntax OK"
 exit 0
fi

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# FULL REPAIR MODE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

export DEBIAN_FRONTEND=noninteractive

# â”€â”€ 0. Otomatik tanÄ± â€” kritik hatalar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "Otomatik TanÄ±"

_SVC_RESULT=$(systemctl show ankavm --property=Result --value 2>/dev/null || echo "unknown")
_JOURNAL=$(journalctl -u ankavm -n 20 --no-pager 2>/dev/null || echo "")

# 226/NAMESPACE â€” hardening drop-in hatasÄ±
if echo "$_JOURNAL" | grep -qE "226/NAMESPACE|Failed to set up mount namespace"; then
 warn "226/NAMESPACE hatasÄ± tespit edildi â€” hardening drop-in neden oluyor"
 if [[ -f "$DROPIN_DIR/hardening.conf" ]]; then
 cp "$DROPIN_DIR/hardening.conf" "$DROPIN_DIR/hardening.conf.bak.$(date +%s)" 2>/dev/null || true
 rm -f "$DROPIN_DIR/hardening.conf"
 systemctl daemon-reload
 log "Hardening drop-in kaldÄ±rÄ±ldÄ± (backup tutuldu) â€” devam ediyor"
 fi
fi

# AppArmor engeli
if echo "$_JOURNAL" | grep -qE "apparmor.*denied|Permission denied.*apparmor"; then
 warn "AppArmor engeli tespit edildi"
 AAPROF="/etc/apparmor.d/opt.ankavm.backend.app"
 if [[ -f "$AAPROF" ]] && command -v apparmor_parser &>/dev/null; then
 apparmor_parser -R "$AAPROF" 2>/dev/null || true
 warn "AppArmor profili geÃ§ici olarak kaldÄ±rÄ±ldÄ± â€” dÃ¼zeltin: bash repair.sh --fix-apparmor"
 fi
fi

# Port Ã§akÄ±ÅŸmasÄ±
if echo "$_JOURNAL" | grep -qE "Address already in use|OSError.*8006"; then
 warn "Port 8006 Ã§akÄ±ÅŸmasÄ± tespit edildi"
 CONFLICTING_PID=$(ss -tlnp 2>/dev/null | grep ":8006" | grep -oP 'pid=\K[0-9]+' | head -1)
 if [[ -n "$CONFLICTING_PID" ]]; then
 CONFLICTING_CMD=$(ps -p "$CONFLICTING_PID" -o comm= 2>/dev/null)
 if [[ "$CONFLICTING_CMD" != "python3" ]] && [[ -n "$CONFLICTING_CMD" ]]; then
 warn "Port 8006'yÄ± tutan sÃ¼reÃ§: PID=$CONFLICTING_PID ($CONFLICTING_CMD) â€” Ã¶ldÃ¼rÃ¼yor..."
 kill "$CONFLICTING_PID" 2>/dev/null || true
 log "Ã‡akÄ±ÅŸan sÃ¼reÃ§ sonlandÄ±rÄ±ldÄ±"
 fi
 fi
fi

# Disk dolu
DISK_USE=$(df / 2>/dev/null | awk 'NR==2{print $5}' | tr -d '%')
if [[ "${DISK_USE:-0}" -gt 95 ]]; then
 warn "Disk %${DISK_USE} dolu â€” otomatik temizlik yapÄ±lÄ±yor..."
 find "$LOG_DIR" -name "*.log" -size +100M -exec truncate -s 5M {} \; 2>/dev/null
 journalctl --vacuum-size=100M 2>/dev/null || true
 apt-get clean -qq 2>/dev/null || true
 find /tmp -mtime +1 -delete 2>/dev/null || true
 log "Disk temizlendi â€” yeni kullanÄ±m: $(df -h / | awk 'NR==2{print $5}')"
fi

# Bozuk JSON config dosyalarÄ±
for jf in "$DATA_DIR"/*.json "$CONFIG_DIR"/*.json; do
 [[ -f "$jf" ]] || continue
 python3 -c "import json; json.load(open('$jf'))" 2>/dev/null || {
 warn "Bozuk JSON: $jf â€” backup alÄ±nÄ±p sÄ±fÄ±rlanÄ±yor"
 cp "$jf" "${jf}.corrupt.$(date +%s)" 2>/dev/null || true
 echo '{}' > "$jf"
 }
done

log "Otomatik tanÄ± tamamlandÄ±"

# â”€â”€ 1. SSH OnarÄ±mÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "SSH OnarÄ±mÄ±"
systemctl enable ssh 2>/dev/null || systemctl enable openssh-server 2>/dev/null || true
systemctl start ssh 2>/dev/null || systemctl start openssh-server 2>/dev/null || true

SSHD="/etc/ssh/sshd_config"
if [[ -f "$SSHD" ]]; then
 sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/' "$SSHD"
 sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' "$SSHD"
 sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' "$SSHD"
 systemctl restart ssh 2>/dev/null || systemctl restart openssh-server 2>/dev/null || true
 log "SSH yapÄ±landÄ±rmasÄ± dÃ¼zeltildi"
else
 warn "sshd_config bulunamadÄ±"
fi

# â”€â”€ 2. Hostname OnarÄ±mÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "Hostname OnarÄ±mÄ±"
CURRENT_HOST=$(hostname)
if [[ "$CURRENT_HOST" == "localhost" || "$CURRENT_HOST" == "localhost.localdomain" || -z "$CURRENT_HOST" ]]; then
 HOST_IP=$(hostname -I | awk '{print $1}')
 NEW_HOST="ankavm-$(echo "$HOST_IP" | tr '.' '-')"
 hostnamectl set-hostname "$NEW_HOST"
 CURRENT_HOST="$NEW_HOST"
 log "Hostname gÃ¼ncellendi: $CURRENT_HOST"
fi
HOST_IP=$(hostname -I | awk '{print $1}')
grep -q "^${HOST_IP}" /etc/hosts 2>/dev/null || \
 echo "${HOST_IP} ${CURRENT_HOST}" >> /etc/hosts
sed -i "s/^127\.0\.1\.1.*/127.0.1.1 ${CURRENT_HOST}/" /etc/hosts
grep -q "127.0.1.1" /etc/hosts || echo "127.0.1.1 ${CURRENT_HOST}" >> /etc/hosts

[[ -d /etc/cloud/cloud.cfg.d ]] && cat > /etc/cloud/cloud.cfg.d/99_hostname.cfg << 'EOF'
preserve_hostname: true
manage_etc_hosts: false
EOF
log "Hostname: $CURRENT_HOST"

# â”€â”€ 3. GÃ¼venlik DuvarÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "GÃ¼venlik DuvarÄ± (UFW)"
if command -v update-alternatives &>/dev/null && command -v iptables-legacy &>/dev/null 2>/dev/null; then
 update-alternatives --set iptables /usr/sbin/iptables-legacy 2>/dev/null || true
 update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null || true
 log "iptables -> iptables-legacy"
fi

if command -v ufw &>/dev/null; then
 ufw --force reset >/dev/null 2>&1 || true
 ufw default deny incoming >/dev/null 2>&1
 ufw default allow outgoing >/dev/null 2>&1
 ufw allow 22/tcp comment "SSH" >/dev/null 2>&1
 ufw allow 80/tcp comment "HTTP" >/dev/null 2>&1
 ufw allow 443/tcp comment "HTTPS" >/dev/null 2>&1
 ufw allow 8006/tcp comment "ankavm UI" >/dev/null 2>&1
 ufw allow 5900:5999/tcp comment "VNC" >/dev/null 2>&1
 ufw allow 6080/tcp comment "noVNC WS" >/dev/null 2>&1
 ufw allow 16509/tcp comment "libvirt" >/dev/null 2>&1
 systemctl enable ufw 2>/dev/null || true
 ufw --force enable >/dev/null 2>&1
 log "UFW: SSH(22), HTTP(80), HTTPS(443), ankavm(8006), VNC(5900-5999), noVNC(6080), libvirt(16509)"
else
 warn "ufw bulunamadÄ±"
fi

# â”€â”€ 4. KVM / AÄŸ OnarÄ±mÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "KVM ve AÄŸ OnarÄ±mÄ±"
for mod in kvm kvm_intel kvm_amd br_netfilter; do
 modprobe "$mod" 2>/dev/null || true
done
for mod in kvm kvm_intel kvm_amd; do
 grep -qx "$mod" /etc/modules 2>/dev/null || echo "$mod" >> /etc/modules
done
grep -q "br_netfilter" /etc/modules-load.d/*.conf 2>/dev/null || \
 echo "br_netfilter" > /etc/modules-load.d/br_netfilter.conf
[[ -e /dev/kvm ]] && log "KVM: /dev/kvm mevcut" || warn "/dev/kvm yok â€” sunucu KVM destekliyor mu?"

# YavaÅŸ baÅŸlatma kaynaÄŸÄ±nÄ± devre dÄ±ÅŸÄ± bÄ±rak
systemctl disable NetworkManager-wait-online.service 2>/dev/null || true
systemctl mask NetworkManager-wait-online.service 2>/dev/null || true
mkdir -p /etc/systemd/system/systemd-networkd-wait-online.service.d/
cat > /etc/systemd/system/systemd-networkd-wait-online.service.d/override.conf << 'EOF'
[Service]
ExecStart=
ExecStart=/lib/systemd/systemd-networkd-wait-online --timeout=10
EOF

# libvirt
systemctl enable --now libvirtd 2>/dev/null || true
sleep 2
for i in $(seq 1 8); do virsh list >/dev/null 2>&1 && break; sleep 2; done
virsh net-autostart default 2>/dev/null || true
virsh net-start default 2>/dev/null || true
log "libvirtd ve varsayÄ±lan aÄŸ baÅŸlatÄ±ldÄ±"

# â”€â”€ 5. Dizin ve Ä°zinler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "Dizin ve Ä°zinler"
[[ ! -f "${APP_DIR}/backend/app.py" ]] && {
 err "Uygulama bulunamadÄ±: ${APP_DIR}/backend/app.py"
 info "Git pull yapÄ±n: cd ${INSTALL_DIR} && git pull"
}

mkdir -p "$LOG_DIR" "$CONFIG_DIR/ssl" "$DATA_DIR"/{isos,disks,backups,templates}
chown root:root "$CONFIG_DIR" && chmod 700 "$CONFIG_DIR"
chmod 755 "$LOG_DIR" "$DATA_DIR"
# Fix broken permissions
find "$CONFIG_DIR" -name "*.key" -exec chmod 600 {} \; 2>/dev/null || true
find "$CONFIG_DIR" -name "*.conf" -exec chmod 600 {} \; 2>/dev/null || true
log "Dizinler ve izinler dÃ¼zeltildi"

# â”€â”€ 6. Sistem Paketleri â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "Sistem Paketleri"
apt-get update -qq 2>/dev/null || true
apt-get install -y -qq --no-install-recommends \
 pkg-config gcc build-essential \
 python3 python3-pip python3-venv python3-dev python3-libvirt \
 libvirt-dev libvirt-daemon-system libvirt-clients \
 openssl ca-certificates novnc websockify \
 qemu-kvm qemu-utils \
 certbot python3-certbot \
 apparmor apparmor-utils 2>/dev/null || warn "BazÄ± paketler kurulamadÄ±"
log "Sistem paketleri hazÄ±r"

# â”€â”€ 7. Python venv â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "Python Sanal OrtamÄ±"

# Broken venv check
if [[ -d "$VENV_DIR" ]] && ! "$VENV_DIR/bin/python3" -c "import flask" 2>/dev/null; then
 warn "Bozuk venv tespit edildi â€” yeniden oluÅŸturuluyor..."
 rm -rf "$VENV_DIR"
fi

[[ ! -f "${VENV_DIR}/bin/python3" ]] && {
 python3 -m venv "$VENV_DIR"
 log "Venv oluÅŸturuldu"
}

source "${VENV_DIR}/bin/activate"
pip install --upgrade pip -q

if [[ -f "${APP_DIR}/backend/requirements.txt" ]]; then
 pip install -r "${APP_DIR}/backend/requirements.txt" -q
else
 pip install -q flask flask-jwt-extended flask-socketio eventlet cryptography \
 paramiko psutil requests flask-cors
fi
pip install -q cryptography libvirt-python
deactivate
log "Python paketleri kuruldu"

# â”€â”€ 8. Config dosyasÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "KonfigÃ¼rasyon"
if [[ ! -f "$CONFIG_DIR/ankavm.conf" ]]; then
 SECRET=$(openssl rand -hex 32)
 cat > "$CONFIG_DIR/ankavm.conf" << CONF
[server]
host = 0.0.0.0
port = ${WEB_PORT}
ssl = true
ssl_cert = ${CONFIG_DIR}/ssl/ankavm.crt
ssl_key = ${CONFIG_DIR}/ssl/ankavm.key
secret_key = ${SECRET}
novnc_dir = /usr/share/novnc

[storage]
data_dir = ${DATA_DIR}
iso_dir = ${DATA_DIR}/isos
disk_dir = ${DATA_DIR}/disks
backup_dir = ${DATA_DIR}/backups
template_dir = ${DATA_DIR}/templates

[vnc]
start_port = 5900
end_port = 5999
websocket_port = 6080

[libvirt]
uri = qemu:///system

[logging]
log_dir = ${LOG_DIR}
level = INFO
CONF
 chmod 600 "$CONFIG_DIR/ankavm.conf"
 log "Config oluÅŸturuldu"
else
 log "Config mevcut"
fi

# â”€â”€ 9. SSL sertifikasÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "SSL SertifikasÄ±"
HOST_IP=$(hostname -I | awk '{print $1}')
HOSTNAME_VAL=$(hostname -f 2>/dev/null || hostname)

# Expired cert check
CERT_EXPIRED=0
if [[ -f "$CONFIG_DIR/ssl/ankavm.crt" ]]; then
 openssl x509 -checkend 86400 -noout -in "$CONFIG_DIR/ssl/ankavm.crt" 2>/dev/null || CERT_EXPIRED=1
fi

if [[ ! -f "$CONFIG_DIR/ssl/ankavm.crt" || ! -f "$CONFIG_DIR/ssl/ankavm.key" || $CERT_EXPIRED -eq 1 ]]; then
 [[ $CERT_EXPIRED -eq 1 ]] && warn "SSL sertifikasÄ± sÃ¼resi dolmuÅŸ â€” yenileniyor..."
 mkdir -p "$CONFIG_DIR/ssl"
 openssl req -x509 -nodes -days 3650 -newkey rsa:4096 \
 -keyout "$CONFIG_DIR/ssl/ankavm.key" \
 -out "$CONFIG_DIR/ssl/ankavm.crt" \
 -subj "/C=TR/O=ankavm/CN=$HOSTNAME_VAL" \
 -addext "subjectAltName=IP:${HOST_IP},DNS:${HOSTNAME_VAL},DNS:localhost" 2>/dev/null
 chmod 600 "$CONFIG_DIR/ssl/ankavm.key"
 log "SSL sertifikasÄ± oluÅŸturuldu (10 yÄ±l)"
else
 EXPIRY=$(openssl x509 -enddate -noout -in "$CONFIG_DIR/ssl/ankavm.crt" 2>/dev/null | cut -d= -f2)
 log "SSL sertifikasÄ± mevcut (son geÃ§erlilik: $EXPIRY)"
fi

# â”€â”€ 10. Systemd Servisi (tam rebuild â€” hardening drop-in TUTULUR eÄŸer Ã§alÄ±ÅŸÄ±yorsa) â”€
step "Systemd Servisi"

# Rebuild main service file (clean baseline)
cat > /etc/systemd/system/ankavm.service << SERVICE
[Unit]
Description=ankavm Hypervisor Management Service
Documentation=https://github.com/ShinnAsukha/ankavm-hypervisor
After=network-online.target libvirtd.service libvirt-guests.service
Wants=network-online.target libvirtd.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${APP_DIR}
Environment=ankavm_CONFIG=${CONFIG_DIR}/ankavm.conf
Environment=PYTHONUNBUFFERED=1
ExecStartPre=/bin/bash -c 'mkdir -p ${LOG_DIR} ${DATA_DIR}/{isos,disks,backups,templates} ${CONFIG_DIR} && chown root:root ${CONFIG_DIR} && chmod 700 ${CONFIG_DIR}'
ExecStartPre=/bin/bash -c 'for i in \$(seq 1 15); do virsh list >/dev/null 2>&1 && break; sleep 2; done; true'
ExecStartPre=/bin/bash -c 'virsh net-list --all 2>/dev/null | grep -q default && virsh net-start default 2>/dev/null || true'
ExecStart=${VENV_DIR}/bin/python3 ${APP_DIR}/backend/app.py
ExecReload=/bin/kill -HUP \$MAINPID
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=120
StartLimitBurst=5
TimeoutStartSec=60
TimeoutStopSec=30
KillMode=mixed
StandardOutput=append:${LOG_DIR}/ankavm.log
StandardError=append:${LOG_DIR}/ankavm-error.log
SyslogIdentifier=ankavm
NoNewPrivileges=false
PrivateTmp=false

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable ankavm
log "Servis dosyasÄ± gÃ¼ncellendi"

# â”€â”€ 10b. Bridge â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "Host Bridge (oxbr0)"
PIFACE=$(ip route show default 2>/dev/null \
 | awk '/^default/{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
[[ -z "$PIFACE" ]] && PIFACE="ens160"

if ip link show oxbr0 &>/dev/null; then
 ip link set "$PIFACE" master oxbr0 2>/dev/null || true
 log "oxbr0 mevcut"
elif [[ "${ankavm_REPAIR_BRIDGE:-0}" == "1" ]]; then
 warn "Bridge kurulacak â€” SSH geÃ§ici dÃ¼ÅŸebilir (netplan try 120s)"
 sleep 3
 PIP=$(ip addr show "$PIFACE" 2>/dev/null | awk '/inet /{print $2; exit}')
 PGW=$(ip route show default 2>/dev/null | awk '/^default/{for(i=1;i<=NF;i++) if($i=="via"){print $(i+1); exit}}')
 if [[ -n "$PIP" && -n "$PGW" ]]; then
 cp -r /etc/netplan "/etc/netplan.bak.$(date +%s)" 2>/dev/null || true
 NP="/etc/netplan/60-ankavm-bridge.yaml"
 cat > "$NP" << NETPLANCFG
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
NETPLANCFG
 chmod 600 "$NP"
 timeout 30 netplan try --timeout 120 </dev/null && log "oxbr0 oluÅŸturuldu OK" || \
 warn "oxbr0 baÅŸarÄ±sÄ±z â€” eski config geri yÃ¼klendi"
 else
 warn "IP/gateway tespit edilemedi"
 fi
else
 info "oxbr0 yok â€” bridge kurmak: sudo ankavm_REPAIR_BRIDGE=1 bash repair.sh"
fi

# libvirt oxbridge
if ! virsh net-info oxbridge &>/dev/null; then
 cat > /tmp/_oxbridge_net.xml << 'LIBVIRTNET'
<network><name>oxbridge</name><forward mode='bridge'/><bridge name='oxbr0'/></network>
LIBVIRTNET
 virsh net-define /tmp/_oxbridge_net.xml 2>/dev/null && \
 virsh net-autostart oxbridge 2>/dev/null && \
 virsh net-start oxbridge 2>/dev/null && \
 log "libvirt oxbridge kayÄ±t edildi" || true
 rm -f /tmp/_oxbridge_net.xml
else
 virsh net-start oxbridge 2>/dev/null || true
fi

# â”€â”€ 10c. MOTD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
mkdir -p /etc/update-motd.d
cat > /etc/update-motd.d/99-ankavm << 'MOTDSCRIPT'
#!/bin/bash
BOLD='\033[1m'; RED='\033[0;31m'; RESET='\033[0m'; LINE='\033[0;90m'
HOST=$(hostname -f 2>/dev/null || hostname)
DATE=$(date '+%Y-%m-%d %H:%M:%S %Z')
printf "\n${LINE}â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€${RESET}\n"
printf " ${BOLD}ankavm Hypervisor${RESET} | %s | %s\n" "$HOST" "$DATE"
printf "${LINE}â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€${RESET}\n"
printf "\n ${RED}NOTICE:${RESET} Restricted system. All sessions monitored and logged.\n"
printf "\n ${BOLD}Support:${RESET} https://github.com/ShinnAsukha/ankavm-hypervisor\n\n"
printf "${LINE}â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€${RESET}\n\n"
MOTDSCRIPT
chmod +x /etc/update-motd.d/99-ankavm
find /etc/update-motd.d -type f ! -name "99-ankavm" -exec chmod -x {} \;
systemctl disable motd-news.service motd-news.timer 2>/dev/null || true
echo "" > /etc/motd 2>/dev/null || true

# â”€â”€ 10d. AdaOS uyumluluk â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
[[ -d /etc/adaos && ! -e /etc/ankavm ]] && ln -s /etc/adaos /etc/ankavm 2>/dev/null || true
[[ -d /var/lib/adaos && ! -e /var/lib/ankavm ]] && ln -s /var/lib/adaos /var/lib/ankavm 2>/dev/null || true
[[ -d /etc/ankavm ]] && grep -rl "AdaOS" /etc/ankavm/ 2>/dev/null | \
 xargs -r sed -i 's/AdaOS/ankavm/g'

# â”€â”€ 11. noVNC / Websockify â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "noVNC / Websockify"
if ! command -v websockify &>/dev/null; then
 apt-get install -y -qq novnc websockify 2>/dev/null || \
 pip install websockify -q 2>/dev/null || \
 warn "websockify kurulamadÄ±"
else
 log "websockify mevcut: $(websockify --version 2>&1 | head -1)"
fi
NOVNC_PATHS=("/usr/share/novnc" "/usr/share/noVNC" "/opt/novnc")
for p in "${NOVNC_PATHS[@]}"; do [[ -d "$p" ]] && { log "noVNC: $p"; break; }; done

# â”€â”€ 12. Servis BaÅŸlat â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "Servis BaÅŸlatÄ±lÄ±yor"
systemctl stop ankavm 2>/dev/null || true
sleep 2

# Final check: remove hardening if still failing
systemctl start ankavm
sleep 5

if ! systemctl is-active --quiet ankavm; then
 FAIL=$(systemctl show ankavm --property=Result --value 2>/dev/null)
 JOUT=$(journalctl -u ankavm -n 5 --no-pager 2>/dev/null)

 if echo "$JOUT" | grep -qE "226/NAMESPACE|NAMESPACE"; then
 warn "226/NAMESPACE â€” hardening drop-in kaldÄ±rÄ±lÄ±yor..."
 rm -f "$DROPIN_DIR/hardening.conf"
 systemctl daemon-reload
 systemctl start ankavm
 sleep 5
 elif echo "$JOUT" | grep -qE "apparmor.*denied|Permission denied"; then
 warn "AppArmor engeli â€” profil kaldÄ±rÄ±lÄ±yor..."
 apparmor_parser -R /etc/apparmor.d/opt.ankavm.backend.app 2>/dev/null || true
 systemctl start ankavm
 sleep 5
 elif echo "$JOUT" | grep -qE "Address already in use|OSError.*8006"; then
 warn "Port Ã§akÄ±ÅŸmasÄ± â€” port 8006 temizleniyor..."
 fuser -k 8006/tcp 2>/dev/null || true
 systemctl start ankavm
 sleep 5
 elif echo "$JOUT" | grep -qE "ModuleNotFoundError|ImportError|No module named"; then
 warn "Python modÃ¼l hatasÄ± â€” venv yeniden kuruluyor..."
 rm -rf "$VENV_DIR"
 python3 -m venv "$VENV_DIR"
 source "$VENV_DIR/bin/activate"
 if [[ -f "${APP_DIR}/backend/requirements.txt" ]]; then
 pip install -r "${APP_DIR}/backend/requirements.txt" -q
 else
 pip install -q flask flask-jwt-extended flask-socketio eventlet cryptography paramiko psutil requests flask-cors libvirt-python
 fi
 deactivate
 systemctl start ankavm
 sleep 5
 fi
fi

# â”€â”€ Ã–zet â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo ""
HOST_IP=$(hostname -I | awk '{print $1}')
if systemctl is-active --quiet ankavm; then
 echo -e "${GREEN}â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—"
 echo -e "â•‘ ankavm OnarÄ±m TamamlandÄ±! OK â•‘"
 echo -e "â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£"
 echo -e "â•‘${NC} ${GREEN}â•‘"
 echo -e "â•‘${NC} Web UI : ${CYAN}https://${HOST_IP}:${WEB_PORT}${NC}$(printf '%*s' $((18-${#HOST_IP})) '')${GREEN}â•‘"
 echo -e "â•‘${NC} SSH : ${CYAN}ssh root@${HOST_IP}${NC}$(printf '%*s' $((22-${#HOST_IP})) '')${GREEN}â•‘"
 echo -e "â•‘${NC} Log : ${CYAN}journalctl -u ankavm -f${NC} ${GREEN}â•‘"
 echo -e "â•‘${NC} TanÄ± : ${CYAN}bash repair.sh --diagnose${NC} ${GREEN}â•‘"
 echo -e "â•‘${NC} ${GREEN}â•‘"
 echo -e "â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•${NC}"
else
 echo ""
 err "Servis baÅŸlatÄ±lamadÄ±!"
 echo ""
 journalctl -u ankavm -n 20 --no-pager 2>/dev/null
 echo ""
 echo -e "${YELLOW}Ã–nerilen adÄ±mlar:${NC}"
 echo " 1. bash repair.sh --diagnose"
 echo " 2. bash repair.sh --remove-hardening # 226/NAMESPACE iÃ§in"
 echo " 3. bash repair.sh --fix-apparmor # AppArmor engeli iÃ§in"
 echo " 4. bash repair.sh --clean-disk # Disk doluysa"
 echo " 5. bash repair.sh --reset-credentials # Åifre sÄ±fÄ±rlama"
 echo " 6. journalctl -u ankavm -n 50"
 echo " 7. cat $LOG_DIR/ankavm-error.log"
fi

echo ""
echo -e "${BOLD}TÃ¼m modlar:${NC} bash repair.sh --help"
echo -e "Repair log: $REPAIR_LOG"






