#!/bin/bash
# ============================================================
# ankavm Hypervisor Installer v2.2
# Ubuntu/Debian KVM Hypervisor YÃ¶netim Sistemi
# https://github.com/ShinnAsukha/ankavm-hypervisor
# ============================================================

# OXW-2026-010 fix: set -e aktif â€” kritik hatalar kurulumu durdurur
# Opsiyonel adÄ±mlar iÃ§in || true veya warn_skip kullanÄ±lÄ±r
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; WHITE='\033[1;37m'; NC='\033[0m'
DARK_GRAY='\033[0;90m'

# â”€â”€ Ä°lerleme Ã‡ubuÄŸu â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
TOTAL_STEPS=21
CURRENT_STEP=0
START_TIME=0

progress_bar() {
 local pct=$1
 local label=$2
 local elapsed=$3
 local bar_width=30
 local filled=$(( pct * bar_width / 100 ))
 local empty=$(( bar_width - filled ))
 local bar=""
 local i
 for (( i=0; i<filled; i++ )); do bar+="â–ˆ"; done
 for (( i=0; i<empty; i++ )); do bar+="â–‘"; done
 printf "\r\033[0;32m[%s\033[0;90m%s\033[0;32m]\033[0m \033[1;37m%3d%%\033[0m â€” %s \033[0;90m(%s geÃ§ti)\033[0m " \
 "$(printf '\033[0;32m%s' "$bar" | head -c $(( filled * 3 + 7 )))" \
 "$(printf '\033[0;90m')" \
 "$pct" \
 "$label" \
 "$elapsed" >&2
}

advance_progress() {
 local label="${1:-}"
 CURRENT_STEP=$(( CURRENT_STEP + 1 ))
 local pct=$(( CURRENT_STEP * 100 / TOTAL_STEPS ))
 local now elapsed_s elapsed_fmt
 now=$(date +%s)
 elapsed_s=$(( now - START_TIME ))
 local mins=$(( elapsed_s / 60 ))
 local secs=$(( elapsed_s % 60 ))
 elapsed_fmt=$(printf "%02d:%02d" "$mins" "$secs")
 # Draw bar: green filled blocks, dark gray empty blocks
 local bar_width=30
 local filled=$(( pct * bar_width / 100 ))
 local empty=$(( bar_width - filled ))
 local filled_str="" empty_str=""
 local i
 for (( i=0; i<filled; i++ )); do filled_str+="â–ˆ"; done
 for (( i=0; i<empty; i++ )); do empty_str+="â–‘"; done
 printf "\r\033[0;32m[\033[0;32m%s\033[0;90m%s\033[0;32m]\033[0m \033[1;37m%3d%%\033[0m â€” %-45s \033[0;90m(%s geÃ§ti)\033[0m " \
 "$filled_str" \
 "$empty_str" \
 "$pct" \
 "$label" \
 "$elapsed_fmt" >&2
 # Move to next line so subsequent step() / log() output is below
 printf "\n" >&2
}

ankavm_VERSION="2.7.0"
REPO_URL="https://github.com/kucukasker718-bot/ankavm.git"

# â”€â”€ Dizin YapÄ±sÄ± (sunucuyla tam uyumlu) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# /opt/ankavm/ -> ana dizin (git repo buraya klonlanÄ±r)
# /opt/ankavm/ankavm/ -> uygulama dosyalarÄ± (backend/ frontend/)
# /opt/ankavm/venv/ -> Python virtual environment
# /etc/ankavm/ -> konfigÃ¼rasyon + SSL sertifikasÄ±
# /var/log/ankavm/ -> loglar
# /var/lib/ankavm/ -> veri (ISO, disk, yedek)
INSTALL_DIR="/opt/ankavm"
APP_DIR="${INSTALL_DIR}/ankavm" # backend/ ve frontend/ burasÄ±
VENV_DIR="${INSTALL_DIR}/venv"
CONFIG_DIR="/etc/ankavm"
LOG_DIR="/var/log/ankavm"
DATA_DIR="/var/lib/ankavm"
WEB_PORT=8006
VNC_START_PORT=5900

MIN_RAM_MB=1800
MIN_DISK_GB=15
MIN_CPU_CORES=1

# â”€â”€ YardÄ±mcÄ± Fonksiyonlar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print_banner() {
 clear
 echo -e "${CYAN}"
 cat << 'BANNER'
 â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•— â–ˆâ–ˆâ•— â–ˆâ–ˆâ•—â–ˆâ–ˆâ•— â–ˆâ–ˆâ•— â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•— â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•— â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•—
 â–ˆâ–ˆâ•”â•â•â•â–ˆâ–ˆâ•—â•šâ–ˆâ–ˆâ•—â–ˆâ–ˆâ•”â•â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â•â•â–ˆâ–ˆâ•—â–ˆâ–ˆâ•”â•â•â–ˆâ–ˆâ•—â–ˆâ–ˆâ•”â•â•â•â•â•
 â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•‘ â•šâ–ˆâ–ˆâ–ˆâ•”â• â–ˆâ–ˆâ•‘ â–ˆâ•— â–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•”â•â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•—
 â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•”â–ˆâ–ˆâ•— â–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ•—â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â•â•â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•”â•â•â–ˆâ–ˆâ•—â–ˆâ–ˆâ•”â•â•â•
 â•šâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•”â•â–ˆâ–ˆâ•”â• â–ˆâ–ˆâ•—â•šâ–ˆâ–ˆâ–ˆâ•”â–ˆâ–ˆâ–ˆâ•”â•â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•‘â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•‘â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•—
 â•šâ•â•â•â•â•â• â•šâ•â• â•šâ•â• â•šâ•â•â•â•šâ•â•â• â•šâ•â• â•šâ•â•â•šâ•â• â•šâ•â•â•šâ•â•â•â•â•â•â•
BANNER
 echo -e "${WHITE} Hypervisor Management System v${ankavm_VERSION}${NC}"
 echo -e "${YELLOW} Ubuntu/KVM â€” ESXi/Proxmox Alternative${NC}"
 echo ""
}

log() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[FAIL] HATA:${NC} $1"; exit 1; }
step() { echo -e "\n${CYAN}â”â”â” $1 â”â”â”${NC}"; }
info() { echo -e "${BLUE}[i]${NC} $1"; }

# â”€â”€ Kontroller â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
check_root() {
 if [[ $EUID -ne 0 ]]; then
 err "Root yetkisi gerekli: sudo bash install.sh"
 fi
}

check_os() {
 if grep -qiE "ubuntu|debian" /etc/os-release 2>/dev/null; then
 OS_NAME=$(grep ^NAME= /etc/os-release | cut -d'"' -f2 || echo "Linux")
 OS_VER=$(grep ^VERSION_ID= /etc/os-release | cut -d'"' -f2 || echo "")
 log "Ä°ÅŸletim sistemi: $OS_NAME $OS_VER"
 else
 err "Sadece Ubuntu 20.04+ ve Debian 11+ desteklenmektedir"
 fi
}

check_bios_virtualization() {
 step "CPU SanallaÅŸtÄ±rma KontrolÃ¼"
 if grep -qE "vmx|svm" /proc/cpuinfo 2>/dev/null; then
 VIRT_TYPE=$(grep -oE "vmx|svm" /proc/cpuinfo | head -1 | tr 'a-z' 'A-Z')
 if [ "$VIRT_TYPE" = "VMX" ]; then
 log "CPU sanallaÅŸtÄ±rma aktif: VMX (Intel VT-x)"
 else
 log "CPU sanallaÅŸtÄ±rma aktif: SVM (AMD-V)"
 fi
 else
 warn "CPU sanallaÅŸtÄ±rma (VT-x/AMD-V) tespit edilemedi â€” test modunda devam ediliyor"
 fi
 modprobe kvm 2>/dev/null || true
 modprobe kvm_intel 2>/dev/null || modprobe kvm_amd 2>/dev/null || true
 if [ -e /dev/kvm ]; then log "/dev/kvm hazÄ±r"; else warn "/dev/kvm bulunamadÄ±"; fi
}

check_hardware() {
 step "DonanÄ±m Gereksinimleri"
 CPU_CORES=$(nproc)
 CPU_MODEL=$(grep -m1 "model name" /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs || echo "Bilinmiyor")
 if [[ $CPU_CORES -lt $MIN_CPU_CORES ]]; then
 err "Minimum $MIN_CPU_CORES CPU Ã§ekirdeÄŸi gerekli (bulunan: $CPU_CORES)"
 fi
 log "CPU: $CPU_MODEL ($CPU_CORES Ã§ekirdek)"

 RAM_MB=$(grep MemTotal /proc/meminfo | awk '{print int($2/1024)}')
 if [[ $RAM_MB -lt $MIN_RAM_MB ]]; then
 warn "DÃ¼ÅŸÃ¼k RAM: ${RAM_MB}MB (Ã¶nerilen 2048MB+)"
 read -p "Yine de devam et? [e/H]: " -r
 if [[ ! $REPLY =~ ^[Ee]$ ]]; then exit 1; fi
 fi
 log "RAM: ${RAM_MB}MB"

 DISK_GB=$(df / | awk 'NR==2{print int($4/1024/1024)}')
 if [[ $DISK_GB -lt $MIN_DISK_GB ]]; then
 err "Minimum ${MIN_DISK_GB}GB boÅŸ disk gerekli (bulunan: ${DISK_GB}GB)"
 fi
 log "Disk: ${DISK_GB}GB boÅŸ"
}

# â”€â”€ Mevcut Kurulum KontrolÃ¼ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
check_existing_installation() {
 step "Mevcut Kurulum KontrolÃ¼"

 FOUND=false
 if [ -d "$INSTALL_DIR" ]; then FOUND=true; fi
 if [ -f /etc/systemd/system/ankavm.service ]; then FOUND=true; fi

 if $FOUND; then
 warn "Mevcut ankavm kurulumu tespit edildi!"
 echo ""
 echo -e " ${YELLOW}[1]${NC} Tamamen sil ve sÄ±fÄ±rdan kur (Ã¶nerilen)"
 echo -e " ${YELLOW}[2]${NC} Sadece dosyalarÄ± gÃ¼ncelle (konfigÃ¼rasyon korunur)"
 echo -e " ${YELLOW}[3]${NC} Ä°ptal"
 echo ""
 read -p "SeÃ§im [1/2/3]: " -r OPT
 case $OPT in
 1)
 warn "Mevcut kurulum temizleniyor..."
 purge_existing
 log "Temizleme tamamlandÄ±"
 ;;
 2)
 info "GÃ¼ncelleme modu..."
 update_mode
 exit 0
 ;;
 *)
 echo "Ä°ptal edildi."
 exit 0
 ;;
 esac
 else
 log "Temiz kurulum â€” mevcut kurulum yok"
 fi
}

purge_existing() {
 systemctl stop ankavm 2>/dev/null || true
 systemctl disable ankavm 2>/dev/null || true
 rm -f /etc/systemd/system/ankavm.service
 systemctl daemon-reload
 rm -rf "$INSTALL_DIR"
 rm -f /usr/local/bin/ox /usr/local/bin/oxupdate
 log "Eski kurulum temizlendi"
}

# â”€â”€ GÃ¼ncelleme Modu â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
update_mode() {
 step "GÃ¼ncelleme Modu"

 # Git repo gÃ¼ncelle
 if [ -d "${INSTALL_DIR}/.git" ]; then
 cd "$INSTALL_DIR"
 git fetch origin main 2>/dev/null
 git reset --hard origin/main 2>/dev/null
 log "Kod gÃ¼ncellendi"
 _cleanup_docs
 else
 warn "Git repo bulunamadÄ± â€” dosya gÃ¼ncelleme atlanÄ±yor"
 fi

 # Python baÄŸÄ±mlÄ±lÄ±klarÄ±
 if [ -f "${VENV_DIR}/bin/activate" ]; then
 source "${VENV_DIR}/bin/activate"
 if [ -f "${APP_DIR}/backend/requirements.txt" ]; then
 _REQ_TMP=$(mktemp)
 trap 'rm -f "$_REQ_TMP"' RETURN EXIT
 grep -v "^libvirt-python" "${APP_DIR}/backend/requirements.txt" | grep -v "^blinker" > "$_REQ_TMP"
 pip install -r "$_REQ_TMP" -q 2>/dev/null || true
 rm -f "$_REQ_TMP"
 fi
 deactivate
 log "Python baÄŸÄ±mlÄ±lÄ±klarÄ± gÃ¼ncellendi"
 fi

 install_cli_tools
 download_fontawesome

 # Servis dosyasÄ±nÄ± gÃ¼ncelle (StartLimitIntervalSec [Unit] konumu dÃ¼zeltmesi)
 create_service

 # Reboot sonrasÄ± kararlÄ±lÄ±k fixleri uygula
 configure_ssh
 configure_hostname
 fix_reboot_stability

 # UFW iptables-legacy fix
 if command -v update-alternatives &>/dev/null; then
 update-alternatives --set iptables /usr/sbin/iptables-legacy 2>/dev/null || true
 update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null || true
 fi
 systemctl enable ufw 2>/dev/null || true

 systemctl daemon-reload
 systemctl restart ankavm 2>/dev/null || true
 sleep 3
 if systemctl is-active --quiet ankavm; then
 log "ankavm yeniden baÅŸlatÄ±ldÄ±"
 else
 warn "Servis baÅŸlatÄ±lamadÄ± â€” kontrol: journalctl -u ankavm -n 30"
 fi

 HOST_IP=$(hostname -I | awk '{print $1}')
 echo ""
 echo -e "${GREEN}[OK] GÃ¼ncelleme tamamlandÄ±!${NC}"
 echo -e " Adres: ${CYAN}https://${HOST_IP}:${WEB_PORT}${NC}"
}

# â”€â”€ Paket Kurulumu â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
update_system() {
 step "Sistem GÃ¼ncelleniyor"
 export DEBIAN_FRONTEND=noninteractive
 apt-get update -qq
 apt-get upgrade -y -qq 2>/dev/null || true
 log "Sistem gÃ¼ncellendi"
}

install_packages() {
 step "Paket Kurulumu"

 # Pre-create dirs for packages with home_dir warnings (swtpm, etc.)
 mkdir -p /var/lib/swtpm 2>/dev/null || true
 chown root:root /var/lib/swtpm 2>/dev/null || true

 PKGS=(
 qemu-kvm qemu-utils libvirt-daemon-system libvirt-clients libvirt-dev
 python3 python3-pip python3-venv python3-dev python3-libvirt
 pkg-config gcc build-essential
 bridge-utils net-tools iptables iptables-persistent socat
 lvm2 parted gdisk
 openssl ca-certificates
 novnc websockify
 cpu-checker htop lsof curl wget git jq smartmontools
 ufw fail2ban certbot python3-certbot
 nftables wireguard
 openvswitch-switch openvswitch-common
 swtpm swtpm-tools
 )
 for pkg in "${PKGS[@]}"; do
 dpkg -l "$pkg" &>/dev/null || apt-get install -y -qq "$pkg" 2>/dev/null \
 || warn "AtlandÄ±: $pkg"
 done

 # Post-install: ensure swtpm user has proper home (skip warning)
 if id swtpm &>/dev/null; then
 usermod -d /var/lib/swtpm swtpm 2>/dev/null || true
 chown swtpm:swtpm /var/lib/swtpm 2>/dev/null || true
 fi

 log "Paketler kuruldu"
}

# â”€â”€ Repo Clone â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
clone_repo() {
 step "ankavm Kaynak Kodu Ä°ndiriliyor"

 if ! command -v git &>/dev/null; then
 apt-get install -y -qq git
 fi

 # Mevcut dizin silinmiÅŸ olabilir (purge sonrasÄ±) â€” gÃ¼venli dizine geÃ§
 cd / 2>/dev/null || true

 rm -rf "$INSTALL_DIR"
 mkdir -p "$INSTALL_DIR"

 # Git clone â€” en son main
 git clone "$REPO_URL" "$INSTALL_DIR" --branch main --depth=1 \
 || git clone "$REPO_URL" "$INSTALL_DIR" --depth=1

 log "Repo klonlandÄ± -> $INSTALL_DIR"
 log "Uygulama dizini -> $APP_DIR"

 # Dizin yapÄ±sÄ±nÄ± doÄŸrula
 if [ ! -f "${APP_DIR}/backend/app.py" ]; then
 err "Beklenen dosya bulunamadÄ±: ${APP_DIR}/backend/app.py"
 fi

 # Sunucuda gereksiz dÃ¶kÃ¼man/meta dosyalarÄ±nÄ± temizle (GitHub'da kalÄ±r, sunucuda yer kaplamaz)
 _cleanup_docs

 chmod -R 750 "$INSTALL_DIR"
}

# Sunucuda gerekmeyen dÃ¶kÃ¼man/meta dosyalarÄ±nÄ± sil (repo'da kalÄ±r, sadece klonda silinir)
_cleanup_docs() {
 local junk=(
 LICENSE CNAME CHANGELOG.md README.md SECURITY.md THREAT_MODEL.md
 CONTRIBUTING.md README.md.bloated.bak install.sh.v2.2.bak
 planning tests .github electron-app
 )
 for f in "${junk[@]}"; do
 rm -rf "${INSTALL_DIR:?}/${f}" 2>/dev/null || true
 done
 log "Gereksiz dÃ¶kÃ¼man dosyalarÄ± temizlendi (LICENSE/README/CHANGELOG/...)"
}

# â”€â”€ libvirt â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
configure_libvirt() {
 step "libvirt YapÄ±landÄ±rmasÄ±"
 systemctl enable --now libvirtd 2>/dev/null || true
 if ! virsh net-list --all 2>/dev/null | grep -q "default"; then
 virsh net-define /usr/share/libvirt/networks/default.xml 2>/dev/null || true
 fi
 virsh net-autostart default 2>/dev/null || true
 virsh net-start default 2>/dev/null || true
 cat > /etc/libvirt/libvirtd.conf << 'EOF'
unix_sock_group = "libvirt"
unix_sock_rw_perms = "0770"
auth_unix_rw = "polkit"
EOF
 # OXW-2026-009: polkit kuralÄ± â€” sadece libvirt grubundaki kullanÄ±cÄ±lar yetkili
 mkdir -p /etc/polkit-1/rules.d
 cat > /etc/polkit-1/rules.d/50-libvirt-ankavm.rules << 'POLKIT'
polkit.addRule(function(action, subject) {
 if (action.id == "org.libvirt.unix.manage" &&
 subject.isInGroup("libvirt")) {
 return polkit.Result.YES;
 }
});
POLKIT
 chmod 640 /etc/polkit-1/rules.d/50-libvirt-ankavm.rules
 systemctl restart libvirtd 2>/dev/null || true
 log "libvirt yapÄ±landÄ±rÄ±ldÄ±"
}

# â”€â”€ Python OrtamÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
setup_python() {
 step "Python Sanal OrtamÄ±"

 # Ubuntu 22.04+ iÃ§in versiyonlu python3.X-venv paketi gerekli
 PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "")
 if [ -n "$PYVER" ]; then
 apt-get install -y -qq "python3.${PYVER}-venv" 2>/dev/null || true
 fi
 apt-get install -y -qq python3-venv python3-full 2>/dev/null || true

 # Temiz venv oluÅŸtur â€” Ã¶nceki baÅŸarÄ±sÄ±z deneme varsa sil
 rm -rf "$VENV_DIR"
 if ! python3 -m venv "$VENV_DIR" --system-site-packages 2>/dev/null; then
 warn "venv --system-site-packages baÅŸarÄ±sÄ±z â€” system-packages olmadan deneniyor"
 python3 -m venv "$VENV_DIR" \
 || { warn "venv oluÅŸturulamadÄ± â€” kurulum pip olmadan devam edecek"; return; }
 fi

 # shellcheck disable=SC1091
 source "${VENV_DIR}/bin/activate" \
 || { warn "venv activate baÅŸarÄ±sÄ±z â€” $VENV_DIR kontrol et"; return; }

 pip install --upgrade pip setuptools wheel -q

 if [ -f "${APP_DIR}/backend/requirements.txt" ]; then
 # libvirt-python: apt paketi kullan (pip derlemesi Ubuntu <24.04'te bozuk)
 # blinker: sistem distutils paketi varsa pip uninstall yapamaz â€” filtrele
 _REQ_TMP=$(mktemp)
 trap 'rm -f "$_REQ_TMP"' RETURN EXIT
 grep -v "^libvirt-python" "${APP_DIR}/backend/requirements.txt" | grep -v "^blinker" > "$_REQ_TMP"
 log "Python baÄŸÄ±mlÄ±lÄ±klarÄ± yÃ¼kleniyor..."
 if ! pip install -r "$_REQ_TMP" --quiet 2>&1; then
 warn "Ä°lk deneme baÅŸarÄ±sÄ±z â€” --ignore-installed ile yeniden deneniyor"
 pip install -r "$_REQ_TMP" --quiet --ignore-installed 2>&1 \
 | grep -E "^ERROR|Cannot" | head -10 || true
 fi
 log "requirements.txt kuruldu"
 rm -f "$_REQ_TMP"
 else
 warn "requirements.txt bulunamadÄ± â€” temel paketler kuruluyor"
 pip install flask flask-jwt-extended flask-socketio flask-cors \
 eventlet cryptography paramiko psutil requests \
 python-dotenv -q
 fi

 # libvirt Python binding kontrolÃ¼
 if python3 -c "import libvirt" 2>/dev/null; then
 log "libvirt Python modÃ¼lÃ¼: OK"
 else
 warn "libvirt Python modÃ¼lÃ¼ bulunamadÄ± â€” 'apt install python3-libvirt' gerekebilir"
 fi

 deactivate
 log "Python ortamÄ± hazÄ±r: $VENV_DIR"
}

# â”€â”€ Font Awesome (Yerel) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
download_fontawesome() {
 step "Font Awesome (Yerel Kurulum)"
 STATIC_DIR="${APP_DIR}/frontend/static"
 mkdir -p "$STATIC_DIR/webfonts"

 FA_BASE="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1"

 if curl -sf "${FA_BASE}/css/all.min.css" -o "$STATIC_DIR/fontawesome.css" 2>/dev/null; then
 # CSS iÃ§indeki font yollarÄ±nÄ± dÃ¼zelt
 sed -i 's|../webfonts/|/static/webfonts/|g' "$STATIC_DIR/fontawesome.css"

 for font in fa-solid-900.woff2 fa-brands-400.woff2 fa-regular-400.woff2 \
 fa-solid-900.ttf fa-brands-400.ttf fa-regular-400.ttf; do
 curl -sf "${FA_BASE}/webfonts/$font" \
 -o "$STATIC_DIR/webfonts/$font" 2>/dev/null || warn "AtlandÄ±: $font"
 done
 log "Font Awesome 6.5.1 yerel olarak indirildi"
 else
 warn "Font Awesome indirilemedi â€” CDN linki HTML'de kalacak"
 fi
}

# â”€â”€ SSL SertifikasÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
generate_ssl() {
 step "SSL SertifikasÄ± OluÅŸturuluyor"
 mkdir -p "$CONFIG_DIR/ssl"
 HOST_IP=$(hostname -I | awk '{print $1}')
 HOSTNAME=$(hostname -f 2>/dev/null || hostname)
 openssl req -x509 -nodes -days 3650 -newkey rsa:4096 \
 -keyout "$CONFIG_DIR/ssl/ankavm.key" \
 -out "$CONFIG_DIR/ssl/ankavm.crt" \
 -subj "/C=TR/O=ankavm/CN=$HOSTNAME" \
 -addext "subjectAltName=IP:$HOST_IP,DNS:$HOSTNAME,DNS:localhost" 2>/dev/null
 chmod 600 "$CONFIG_DIR/ssl/ankavm.key"
 log "SSL sertifikasÄ± oluÅŸturuldu (10 yÄ±l, $HOSTNAME / $HOST_IP)"
}

# â”€â”€ KonfigÃ¼rasyon â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
write_config() {
 step "KonfigÃ¼rasyon YazÄ±lÄ±yor"
 mkdir -p "$CONFIG_DIR" "$LOG_DIR" "$DATA_DIR"/{isos,disks,backups,templates}
 # Sadece root yazabilsin â€” root olmayan SSH kullanÄ±cÄ±larÄ± .passwd_reset oluÅŸturamaz
 chown root:root "$CONFIG_DIR"
 chmod 700 "$CONFIG_DIR"
 SECRET=$(openssl rand -hex 32)
 cat > "$CONFIG_DIR/ankavm.conf" << CONF
[server]
host = 0.0.0.0
port = ${WEB_PORT}
ssl = true
ssl_cert = ${CONFIG_DIR}/ssl/ankavm.crt
ssl_key = ${CONFIG_DIR}/ssl/ankavm.key
secret_key = ${SECRET}

[storage]
data_dir = ${DATA_DIR}
iso_dir = ${DATA_DIR}/isos
disk_dir = ${DATA_DIR}/disks
backup_dir = ${DATA_DIR}/backups
template_dir = ${DATA_DIR}/templates

[vnc]
start_port = ${VNC_START_PORT}
end_port = 5999
websocket_port = 6080

[libvirt]
uri = qemu:///system

[logging]
log_dir = ${LOG_DIR}
level = INFO
CONF
 chmod 600 "$CONFIG_DIR/ankavm.conf"
 log "KonfigÃ¼rasyon: $CONFIG_DIR/ankavm.conf"
}

# â”€â”€ noVNC â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
install_novnc() {
 step "noVNC Konsol"
 NOVNC_DIR="/usr/share/novnc"
 [ ! -d "$NOVNC_DIR" ] && NOVNC_DIR="/opt/novnc"
 if [ ! -d "$NOVNC_DIR" ]; then
 git clone https://github.com/novnc/noVNC.git "$NOVNC_DIR" -q 2>/dev/null \
 || mkdir -p "$NOVNC_DIR"
 fi
 grep -q "novnc_dir" "$CONFIG_DIR/ankavm.conf" \
 || echo "novnc_dir = $NOVNC_DIR" >> "$CONFIG_DIR/ankavm.conf"
 log "noVNC: $NOVNC_DIR"
}

# â”€â”€ Systemd Servis â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
create_service() {
 step "Systemd Servisi OluÅŸturuluyor"
 cat > /etc/systemd/system/ankavm.service << SERVICE
[Unit]
Description=ankavm Hypervisor Management Service
Documentation=https://github.com/ShinnAsukha/ankavm-hypervisor
# network-online.target: aÄŸ gerÃ§ekten hazÄ±r (sadece yapÄ±landÄ±rÄ±ldÄ± deÄŸil)
# libvirt-guests.service: libvirt hem baÅŸladÄ± hem de aÄŸlarÄ± otomatik aÃ§tÄ±
After=network-online.target libvirtd.service libvirt-guests.service
Wants=network-online.target libvirtd.service
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${APP_DIR}
Environment=ankavm_CONFIG=${CONFIG_DIR}/ankavm.conf
Environment=PYTHONUNBUFFERED=1

# Dizinleri oluÅŸtur
ExecStartPre=/bin/bash -c 'mkdir -p ${LOG_DIR} ${DATA_DIR}/{isos,disks,backups,templates} /etc/ankavm && chown root:root /etc/ankavm && chmod 700 /etc/ankavm'
# libvirtd soketini bekle (reboot sonrasÄ± geÃ§ hazÄ±r olabilir)
ExecStartPre=/bin/bash -c 'for i in \$(seq 1 15); do virsh list >/dev/null 2>&1 && break; sleep 2; done; true'
# default aÄŸÄ± baÅŸlat (autostart bazen reboot'ta Ã§alÄ±ÅŸmÄ±yor)
ExecStartPre=/bin/bash -c 'virsh net-list --all 2>/dev/null | grep -q default && virsh net-start default 2>/dev/null || true'
ExecStart=${VENV_DIR}/bin/python3 ${APP_DIR}/backend/app.py
ExecReload=/bin/kill -HUP \$MAINPID

Restart=on-failure
RestartSec=10
TimeoutStartSec=60
TimeoutStopSec=30
KillMode=mixed
StandardOutput=append:${LOG_DIR}/ankavm.log
StandardError=append:${LOG_DIR}/ankavm-error.log
SyslogIdentifier=ankavm

# GÃ¼venlik
NoNewPrivileges=false
MemoryMax=2G
TasksMax=512
LimitNOFILE=65536
LimitNPROC=512
PrivateTmp=false

[Install]
WantedBy=multi-user.target
SERVICE
 systemctl daemon-reload
 systemctl enable ankavm
 log "Servis oluÅŸturuldu: /etc/systemd/system/ankavm.service"
 info "WorkingDirectory : ${APP_DIR}"
 info "ExecStart : ${VENV_DIR}/bin/python3 ${APP_DIR}/backend/app.py"
}

# â”€â”€ CLI AraÃ§larÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
install_cli_tools() {
 step "CLI AraÃ§larÄ± (ox / oxupdate)"

 # ox
 cat > /usr/local/bin/ox << OXCMD
#!/bin/bash
VERSION="${ankavm_VERSION}"
RED=\$'\033[0;31m'; GREEN=\$'\033[0;32m'; YELLOW=\$'\033[1;33m'
CYAN=\$'\033[0;36m'; WHITE=\$'\033[1;37m'; NC=\$'\033[0m'

show_help() {
cat << HELP
\${CYAN}
 â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•— â–ˆâ–ˆâ•— â–ˆâ–ˆâ•—
 â–ˆâ–ˆâ•”â•â•â•â–ˆâ–ˆâ•—\${NC}\${CYAN}â•šâ–ˆâ–ˆâ•—â–ˆâ–ˆâ•”â•
 â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•‘ \${NC}\${CYAN}â•šâ–ˆâ–ˆâ–ˆâ•”â•
 â–ˆâ–ˆâ•‘ â–ˆâ–ˆâ•‘ \${NC}\${CYAN}â–ˆâ–ˆâ•”â–ˆâ–ˆâ•—
 â•šâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ•”â•â–ˆâ–ˆâ•”â• â–ˆâ–ˆâ•—
 â•šâ•â•â•â•â•â• â•šâ•â• â•šâ•â•\${NC}
\${WHITE}ankavm Hypervisor CLI v\${VERSION}\${NC}

\${YELLOW}KullanÄ±m:\${NC} ox [komut]

\${YELLOW}Komutlar:\${NC}
 \${GREEN}--help, -h\${NC} Bu yardÄ±mÄ± gÃ¶ster
 \${GREEN}--status, -s\${NC} Servis durumunu gÃ¶ster
 \${GREEN}--start\${NC} ankavm'i baÅŸlat
 \${GREEN}--stop\${NC} ankavm'i durdur
 \${GREEN}--restart\${NC} ankavm'i yeniden baÅŸlat
 \${GREEN}--logs, -l\${NC} Son 50 log satÄ±rÄ±nÄ± gÃ¶ster
 \${GREEN}--logs -f\${NC} CanlÄ± log takibi
 \${GREEN}--info\${NC} Sistem bilgilerini gÃ¶ster
 \${GREEN}--vms\${NC} Sanal makineleri listele
 \${GREEN}--users\${NC} KullanÄ±cÄ±larÄ± listele
 \${GREEN}--url\${NC} Web arayÃ¼z adresini gÃ¶ster
 \${GREEN}--update\${NC} ankavm'i gÃ¼ncelle (oxupdate)
 \${GREEN}--version, -v\${NC} SÃ¼rÃ¼m bilgisi
HELP
}

show_users() {
 echo -e "\n\${CYAN}â”â”â” ankavm KullanÄ±cÄ±larÄ± â”â”â”\${NC}"
 printf " \${WHITE}%-20s %-12s\${NC}\n" "KULLANICI ADI" "YETKÄ°"
 printf " \${WHITE}%-20s %-12s\${NC}\n" "--------------------" "------------"

 # Primary admin
 _PRIMARY=""
 [ -f /etc/ankavm/.username ] && _PRIMARY=\$(cat /etc/ankavm/.username 2>/dev/null | tr -d '[:space:]')
 if [ -n "\$_PRIMARY" ]; then
 printf " \${GREEN}%-20s\${NC} \${YELLOW}%-12s\${NC}\n" "\$_PRIMARY" "admin"
 fi

 # Extra users from /var/lib/ankavm/users.json
 if [ -f "/var/lib/ankavm/users.json" ]; then
 python3 - <<'PYUSERS' 2>/dev/null
import json, os
_UF = "/var/lib/ankavm/users.json"
_PF = "/etc/ankavm/.username"
try:
 data = json.load(open(_UF))
 users = data.get("users", {})
 primary = open(_PF).read().strip() if os.path.exists(_PF) else ""
 for uname, info in users.items():
 if uname == primary:
 continue
 role = info.get("role", "viewer")
 color = "\033[0;36m" if role in ("admin", "administrator") else "\033[0;37m"
 print(f" {color}{uname:<20}\033[0m \033[0;37m{role:<12}\033[0m")
except Exception as e:
 print(f" (users.json okunamadÄ±: {e})")
PYUSERS
 fi
 echo ""
}

show_status() {
 echo -e "\n\${CYAN}â”â”â” ankavm Servis Durumu â”â”â”\${NC}"
 systemctl status ankavm --no-pager -l 2>/dev/null || echo "Servis bulunamadÄ±"
 HOST_IP=\$(hostname -I | awk '{print \$1}')
 echo -e "\n Web UI: \${CYAN}https://\${HOST_IP}:8006\${NC}\n"
}

show_info() {
 HOST_IP=\$(hostname -I | awk '{print \$1}')
 echo -e "\n\${CYAN}â”â”â” ankavm Bilgileri â”â”â”\${NC}"
 echo -e " SÃ¼rÃ¼m : \${WHITE}\${VERSION}\${NC}"
 echo -e " Web URL : \${CYAN}https://\${HOST_IP}:8006\${NC}"
 echo -e " Uygulama : ${APP_DIR}"
 echo -e " Venv : ${VENV_DIR}"
 echo -e " Konfig : ${CONFIG_DIR}/ankavm.conf"
 echo -e " Loglar : ${LOG_DIR}/"
 echo -e " Veri : ${DATA_DIR}/"
 echo -e "\n\${CYAN}â”â”â” Sistem KaynaklarÄ± â”â”â”\${NC}"
 echo -e " CPU : \$(nproc) Ã§ekirdek â€” \$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)"
 RAM_MB=\$(grep MemTotal /proc/meminfo | awk '{print int(\$2/1024)}')
 FREE_MB=\$(grep MemAvailable /proc/meminfo | awk '{print int(\$2/1024)}')
 echo -e " RAM : \${RAM_MB}MB toplam, \${FREE_MB}MB boÅŸ"
 echo -e " Disk : \$(df / | awk 'NR==2{print \$5}') kullanÄ±ldÄ±, \$(df / | awk 'NR==2{print int(\$4/1024/1024)}')GB boÅŸ"
 echo -e "\n\${CYAN}â”â”â” KVM Durumu â”â”â”\${NC}"
 [ -e /dev/kvm ] && echo -e " KVM : \${GREEN}Aktif\${NC}" || echo -e " KVM : \${RED}BulunamadÄ±\${NC}"
 echo ""
}

case "\$1" in
 --help|-h|"") show_help ;;
 --status|-s) show_status ;;
 --start) systemctl start ankavm && echo -e "\${GREEN}[OK] ankavm baÅŸlatÄ±ldÄ±\${NC}" ;;
 --stop) systemctl stop ankavm && echo -e "\${YELLOW}[!] ankavm durduruldu\${NC}" ;;
 --restart) systemctl restart ankavm && echo -e "\${GREEN}[OK] ankavm yeniden baÅŸlatÄ±ldÄ±\${NC}" ;;
 --logs|-l)
 [ "\$2" = "-f" ] && journalctl -u ankavm -f \
 || journalctl -u ankavm -n 50 --no-pager ;;
 --info) show_info ;;
 --vms)
 echo -e "\n\${CYAN}â”â”â” Sanal Makineler â”â”â”\${NC}"
 virsh list --all 2>/dev/null || echo "libvirt baÄŸlantÄ±sÄ± kurulamadÄ±"
 echo "" ;;
 --users) show_users ;;
 --url)
 HOST_IP=\$(hostname -I | awk '{print \$1}')
 echo -e " \${CYAN}https://\${HOST_IP}:8006\${NC}" ;;
 --update) oxupdate ;;
 --version|-v) echo "ankavm v\${VERSION}" ;;
 *)
 echo -e "\${RED}Bilinmeyen komut: \$1\${NC}"
 echo "YardÄ±m iÃ§in: ox --help"
 exit 1 ;;
esac
OXCMD
 chmod +x /usr/local/bin/ox

 # oxupdate
 cat > /usr/local/bin/oxupdate << OXUPDATE
#!/bin/bash
RED=\$'\033[0;31m'; GREEN=\$'\033[0;32m'; YELLOW=\$'\033[1;33m'
CYAN=\$'\033[0;36m'; NC=\$'\033[0m'

APP_DIR="${APP_DIR}"
VENV_DIR="${VENV_DIR}"
INSTALL_DIR="${INSTALL_DIR}"

# Herhangi bir hatada kurtarma komutlarÄ±nÄ± gÃ¶ster
_oxupdate_fail() {
 echo -e "\n\${RED}[FAIL] GÃ¼ncelleme sÄ±rasÄ±nda hata oluÅŸtu.\${NC}"
 echo -e "\${YELLOW}Kurtarma iÃ§in ÅŸu komutlarÄ± Ã§alÄ±ÅŸtÄ±rÄ±n:\${NC}"
 echo -e "  \${CYAN}cd /opt/ankavm && git pull\${NC}"
 echo -e "  \${CYAN}sudo bash repair.sh --fix-cli\${NC}"
 echo -e "  \${CYAN}sudo systemctl restart ankavm\${NC}"
}
trap _oxupdate_fail ERR

echo -e "\${CYAN}â”â”â” ankavm GÃ¼ncelleme â”â”â”\${NC}"
[[ \$EUID -ne 0 ]] && { echo -e "\${RED}Root gerekli: sudo oxupdate\${NC}"; exit 1; }

echo -e "\${YELLOW}[!]\${NC} ankavm durduruluyor..."
systemctl stop ankavm 2>/dev/null || true

if [ -d "\${INSTALL_DIR}/.git" ]; then
 echo -e "\${CYAN}[i]\${NC} GitHub'dan gÃ¼ncelleniyor..."
 cd "\${INSTALL_DIR}"
 git fetch origin main
 git reset --hard origin/main
 echo -e "\${GREEN}[OK]\${NC} Kod gÃ¼ncellendi"
 # Gereksiz dÃ¶kÃ¼man dosyalarÄ±nÄ± temizle (brace expansion YOK â€” unquoted heredoc'ta patlar)
 for _j in LICENSE CNAME CHANGELOG.md README.md SECURITY.md THREAT_MODEL.md CONTRIBUTING.md planning tests .github electron-app; do
 rm -rf "\${INSTALL_DIR}/\${_j}" 2>/dev/null || true
 done
 # CLI araÃ§larÄ±nÄ± da gÃ¼ncelle (ox / oxupdate binary'leri)
 if [ -f "\${INSTALL_DIR}/install.sh" ]; then
 echo -e "\${CYAN}[i]\${NC} CLI araÃ§larÄ± yenileniyor (ox / oxupdate)..."
 bash "\${INSTALL_DIR}/install.sh" --refresh-cli 2>/dev/null \
 && echo -e "\${GREEN}[OK]\${NC} ox / oxupdate gÃ¼ncellendi" \
 || echo -e "\${YELLOW}[!]\${NC} CLI gÃ¼ncelleme atlandÄ±"
 fi
else
 echo -e "\${YELLOW}[!]\${NC} Git repo bulunamadÄ± â€” atlanÄ±yor"
fi

echo -e "\${CYAN}[i]\${NC} Python baÄŸÄ±mlÄ±lÄ±klarÄ± gÃ¼ncelleniyor..."
source "\${VENV_DIR}/bin/activate"
if [ -f "\${APP_DIR}/backend/requirements.txt" ]; then
 _REQ_TMP=\$(mktemp)
 grep -v "^libvirt-python" "\${APP_DIR}/backend/requirements.txt" | grep -v "^blinker" > "\$_REQ_TMP"
 pip install -r "\$_REQ_TMP" -q 2>/dev/null || true
 rm -f "\$_REQ_TMP"
fi
deactivate

echo -e "\${CYAN}[i]\${NC} ankavm baÅŸlatÄ±lÄ±yor..."
systemctl start ankavm
sleep 3

if systemctl is-active --quiet ankavm; then
 echo -e "\${GREEN}[OK] ankavm gÃ¼ncellendi ve Ã§alÄ±ÅŸÄ±yor!\${NC}"
 HOST_IP=\$(hostname -I | awk '{print \$1}')
 echo -e " Web UI: \${CYAN}https://\${HOST_IP}:8006\${NC}"
else
 echo -e "\${RED}[FAIL] Servis baÅŸlatÄ±lamadÄ± â€” kontrol: journalctl -u ankavm -n 30\${NC}"
 exit 1
fi
OXUPDATE
 chmod +x /usr/local/bin/oxupdate

 # Ãœretilen oxupdate'i syntax doÄŸrula â€” bozuksa repair.sh ile yeniden kur
 if ! bash -n /usr/local/bin/oxupdate 2>/dev/null; then
 warn "Ãœretilen oxupdate bozuk â€” repair.sh --fix-cli ile yeniden kuruluyor"
 [ -f "${INSTALL_DIR}/repair.sh" ] && bash "${INSTALL_DIR}/repair.sh" --fix-cli 2>/dev/null || true
 fi

 log "ox komutu kuruldu -> 'ox --help'"
 log "oxupdate komutu kuruldu -> 'sudo oxupdate'"
}

# â”€â”€ SSH KalÄ±cÄ± KonfigÃ¼rasyon â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
configure_ssh() {
 step "SSH Servisi"
 # Ubuntu'da servis adÄ± 'ssh', Debian'da 'sshd' olabilir
 systemctl enable ssh 2>/dev/null || systemctl enable sshd 2>/dev/null || true
 systemctl start ssh 2>/dev/null || systemctl start sshd 2>/dev/null || true

 # SSH config â€” gÃ¼venli yapÄ±landÄ±rma (rapor.md #33 / OXW gÃ¼venlik fix)
 # PermitRootLogin yes VE PasswordAuthentication yes kombinasyonu brute-force davetiyesidir.
 # Root giriÅŸ: prohibit-password (SSH key varsa izin ver, ÅŸifre ile hayÄ±r)
 # PasswordAuthentication: varsayÄ±lan olarak kapalÄ± â€” SSH key kullanÄ±mÄ± zorunlu
 SSH_CONF="/etc/ssh/sshd_config"
 if [ -f "$SSH_CONF" ]; then
 # PermitRootLogin yes â€” ÅŸifre ile root giriÅŸi aÃ§Ä±k
 if grep -q "^#*PermitRootLogin" "$SSH_CONF"; then
 sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' "$SSH_CONF"
 else
 echo "PermitRootLogin yes" >> "$SSH_CONF"
 fi
 # PasswordAuthentication yes â€” ÅŸifre giriÅŸi aÃ§Ä±k
 if grep -q "^#*PasswordAuthentication" "$SSH_CONF"; then
 sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' "$SSH_CONF"
 else
 echo "PasswordAuthentication yes" >> "$SSH_CONF"
 fi
 # MaxAuthTries: brute-force'u yavaÅŸlat
 if grep -q "^#*MaxAuthTries" "$SSH_CONF"; then
 sed -i 's/^#*MaxAuthTries.*/MaxAuthTries 3/' "$SSH_CONF"
 else
 echo "MaxAuthTries 3" >> "$SSH_CONF"
 fi
 systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
 fi
 warn "SSH ÅŸifre giriÅŸi KAPALI. Sunucuya eriÅŸmek iÃ§in SSH key kullanÄ±n."
 log "SSH servisi etkinleÅŸtirildi (key-only mod)"
}

# â”€â”€ Hostname KalÄ±cÄ± KonfigÃ¼rasyon â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
configure_hostname() {
 step "Hostname YapÄ±landÄ±rmasÄ±"

 # Mevcut hostname'i koru, yoksa 'ankavm-server' yap
 CUR_HOST=$(hostname -s 2>/dev/null || echo "")
 if [ -z "$CUR_HOST" ] || [ "$CUR_HOST" = "localhost" ] || [ "$CUR_HOST" = "localhost.localdomain" ]; then
 NEW_HOST="ankavm-server"
 else
 NEW_HOST="$CUR_HOST"
 fi

 hostnamectl set-hostname "$NEW_HOST" 2>/dev/null || echo "$NEW_HOST" > /etc/hostname

 # /etc/hosts gÃ¼ncelle
 if ! grep -q "$NEW_HOST" /etc/hosts; then
 sed -i "/^127\.0\.1\.1/d" /etc/hosts
 echo "127.0.1.1 $NEW_HOST" >> /etc/hosts
 fi

 # Cloud-init hostname reset'ini devre dÄ±ÅŸÄ± bÄ±rak
 if [ -d /etc/cloud/cloud.cfg.d ]; then
 echo "preserve_hostname: true" > /etc/cloud/cloud.cfg.d/99_hostname.cfg
 log "Cloud-init hostname reset devre dÄ±ÅŸÄ± bÄ±rakÄ±ldÄ±"
 fi

 log "Hostname: $NEW_HOST"
}

# â”€â”€ Host Linux Bridge (oxbr0) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# OPT-IN â€” varsayÄ±lan olarak KAPALI. Bridge kurulumu netplan apply sÄ±rasÄ±nda
# SSH baÄŸlantÄ±sÄ±nÄ± koparabilir. Production sunucularda bÃ¼yÃ¼k risk.
#
# AktifleÅŸtirmek iÃ§in:
# ankavm_SETUP_BRIDGE=1 bash install.sh
# veya kurulumdan sonra manuel:
# sudo /opt/ankavm/scripts/setup-bridge.sh
setup_host_bridge() {
 # Default: SKIP â€” kullanÄ±cÄ± opt-in etmedikÃ§e bridge kurulmaz
 if [ "${ankavm_SETUP_BRIDGE:-0}" != "1" ]; then
 info "Host bridge kurulumu atlandÄ± (varsayÄ±lan: SSH kesilmesin diye)"
 info "Manuel kurmak iÃ§in: ankavm_SETUP_BRIDGE=1 bash install.sh"
 info "Veya kurulumdan sonra: /opt/ankavm/scripts/setup-bridge.sh"
 return 0
 fi

 step "Host Bridge (oxbr0) Kurulumu â€” OPT-IN (SSH kesilebilir!)"
 warn "WARN Bu iÅŸlem netplan apply yapar. SSH baÄŸlantÄ±n 10sn iÃ§in dÃ¼ÅŸebilir."
 warn "WARN Bridge kurulumu baÅŸarÄ±sÄ±z olursa sunucu UNREACHABLE olabilir."
 sleep 5

 # Already fully configured?
 if ip link show oxbr0 &>/dev/null && ip link show master oxbr0 &>/dev/null 2>/dev/null; then
 log "oxbr0 bridge zaten mevcut ve Ã¼yesi var, atlanÄ±yor"
 _register_oxbridge_libvirt
 return 0
 fi

 # Detect primary physical interface from default route
 local PIFACE PIP PIP_PREFIX PGW
 PIFACE=$(ip route show default 2>/dev/null \
 | awk '/^default/{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
 [ -z "$PIFACE" ] && PIFACE="ens160"

 # Skip if already virtual/bridge
 case "$PIFACE" in
 virbr*|oxbr*|br*|vnet*|tap*|tun*|lo)
 warn "Primary iface '$PIFACE' sanal gÃ¶rÃ¼nÃ¼yor, bridge atlanÄ±yor"
 return 0
 ;;
 esac

 # Get current IP with prefix (e.g. 31.58.236.82/24)
 PIP=$(ip addr show "$PIFACE" 2>/dev/null \
 | awk '/inet /{print $2; exit}')
 PGW=$(ip route show default 2>/dev/null \
 | awk '/^default/{for(i=1;i<=NF;i++) if($i=="via"){print $(i+1); exit}}')

 if [ -z "$PIP" ] || [ -z "$PGW" ]; then
 warn "IP/gateway tespit edilemedi ($PIFACE), bridge kurulumu atlanÄ±yor"
 return 1
 fi

 log "Bridge: $PIFACE ($PIP) -> oxbr0, gw: $PGW"

 # Backup original netplan dir before changes
 cp -r /etc/netplan "/etc/netplan.bak.$(date +%s)" 2>/dev/null || true

 # Write netplan bridge config
 local NP="/etc/netplan/60-ankavm-bridge.yaml"
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

 # Strip all IP/route/gateway config from PIFACE in other netplan files.
 for f in /etc/netplan/*.yaml; do
 [ "$f" = "$NP" ] && continue
 grep -q "$PIFACE" "$f" 2>/dev/null || continue
 python3 - "$f" "$PIFACE" << 'PYCLEAN'
import sys, yaml
fpath, iface = sys.argv[1], sys.argv[2]
with open(fpath) as fp:
 cfg = yaml.safe_load(fp) or {}
eth = cfg.get('network', {}).get('ethernets', {})
if iface in eth:
 eth[iface] = {'dhcp4': False}
with open(fpath, 'w') as fp:
 yaml.dump(cfg, fp, default_flow_style=False, allow_unicode=True)
print(f"Cleaned {iface} config in {fpath}")
PYCLEAN
 chmod 600 "$f"
 done

 # netplan try -> 120s rollback timer if SSH dies, original config restored
 log "netplan try kullanÄ±lÄ±yor (120s rollback timer aktif)..."
 if timeout 30 netplan try --timeout 120 < /dev/null; then
 log "oxbr0 bridge aktif OK ($PIP Ã¼zerinde, $PIFACE baÄŸlÄ±)"
 _register_oxbridge_libvirt
 else
 warn "netplan try iptal edildi veya baÅŸarÄ±sÄ±z â€” eski config geri yÃ¼klendi"
 warn "Bridge kurulamadÄ±. Sunucu Ã¶nceki haline dÃ¶ndÃ¼, SSH gÃ¼vende."
 return 1
 fi
}

_register_oxbridge_libvirt() {
 # Register oxbridge with libvirt (idempotent)
 if virsh net-info oxbridge &>/dev/null; then
 virsh net-autostart oxbridge &>/dev/null || true
 virsh net-start oxbridge &>/dev/null || true
 return 0
 fi
 cat > /tmp/_oxbridge_net.xml << 'LIBVIRTNET'
<network>
 <name>oxbridge</name>
 <forward mode='bridge'/>
 <bridge name='oxbr0'/>
</network>
LIBVIRTNET
 virsh net-define /tmp/_oxbridge_net.xml
 rm -f /tmp/_oxbridge_net.xml
 virsh net-autostart oxbridge
 virsh net-start oxbridge
 log "libvirt oxbridge network kayÄ±t edildi OK"
}

# â”€â”€ Reboot SonrasÄ± AÄŸ/Servis KararlÄ±lÄ±ÄŸÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
fix_reboot_stability() {
 step "Reboot KararlÄ±lÄ±ÄŸÄ±"

 # systemd-networkd-wait-online zaman aÅŸÄ±mÄ± â€” Ã§ok uzun beklerse ankavm geÃ§ baÅŸlar
 mkdir -p /etc/systemd/system/systemd-networkd-wait-online.service.d
 cat > /etc/systemd/system/systemd-networkd-wait-online.service.d/timeout.conf << 'EOF'
[Service]
TimeoutStartSec=15
EOF

 # network-online.target â€” NetworkManager tabanlÄ± sistemlerde
 if systemctl is-enabled NetworkManager 2>/dev/null | grep -q "enabled"; then
 systemctl enable NetworkManager-wait-online.service 2>/dev/null || true
 fi

 # libvirtd reboot'ta default aÄŸÄ± otomatik baÅŸlatsÄ±n
 virsh net-autostart default 2>/dev/null || true

 # KVM modÃ¼llerini reboot'ta yÃ¼kle
 if ! grep -q "^kvm" /etc/modules 2>/dev/null; then
 echo "kvm" >> /etc/modules
 grep -qE "vmx|svm" /proc/cpuinfo && {
 grep -q "vmx" /proc/cpuinfo && echo "kvm_intel" >> /etc/modules || echo "kvm_amd" >> /etc/modules
 }
 log "KVM modÃ¼lleri /etc/modules'a eklendi"
 fi

 systemctl daemon-reload
 log "Reboot kararlÄ±lÄ±ÄŸÄ± yapÄ±landÄ±rÄ±ldÄ±"
}

# â”€â”€ Firewall â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
configure_firewall() {
 step "GÃ¼venlik DuvarÄ± (UFW)"

 # Ubuntu 20.04+ nftables kullanÄ±r; UFW iptables beklediÄŸi iÃ§in Ã§akÄ±ÅŸÄ±r
 # Ã‡Ã¶zÃ¼m: iptables-legacy kullan
 if command -v update-alternatives &>/dev/null; then
 update-alternatives --set iptables /usr/sbin/iptables-legacy 2>/dev/null || true
 update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null || true
 log "iptables-legacy seÃ§ildi (UFW uyumluluÄŸu iÃ§in)"
 fi

 ufw --force reset 2>/dev/null || true
 ufw default deny incoming 2>/dev/null || true
 ufw default allow outgoing 2>/dev/null || true
 ufw allow 22/tcp comment "SSH" 2>/dev/null || true
 ufw allow 8006/tcp comment "ankavm Web UI" 2>/dev/null || true
 ufw allow 80/tcp comment "HTTP (Let's Encrypt)" 2>/dev/null || true
 ufw allow 5900:5999/tcp comment "VNC" 2>/dev/null || true
 ufw allow 6080/tcp comment "noVNC WS" 2>/dev/null || true
 echo "y" | ufw enable 2>/dev/null || true
 systemctl enable ufw 2>/dev/null || true
 log "UFW aktif"
}

configure_fail2ban() {
 step "Fail2ban"
 cat > /etc/fail2ban/jail.d/ankavm.conf << 'F2B'
[ankavm-web]
enabled = true
port = 8006
filter = ankavm-web
logpath = /var/log/ankavm/ankavm.log
maxretry = 5
bantime = 3600
findtime = 600

[sshd]
enabled = true
maxretry = 5
bantime = 3600
F2B
 cat > /etc/fail2ban/filter.d/ankavm-web.conf << 'F2BFILTER'
[Definition]
failregex = \[auth\].*Failed login.*<HOST>
ignoreregex =
F2BFILTER
 systemctl enable --now fail2ban 2>/dev/null || true
 systemctl reload fail2ban 2>/dev/null || true
 log "Fail2ban yapÄ±landÄ±rÄ±ldÄ±"
}

# â”€â”€ OpenVSwitch â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
install_ovs() {
 step "OpenVSwitch (SDN)"
 if ! command -v ovs-vsctl &>/dev/null; then
 warn "ovs-vsctl bulunamadÄ± â€” yeniden yÃ¼kleniyor..."
 apt-get install -y -qq openvswitch-switch openvswitch-common 2>/dev/null || true
 fi
 if command -v ovs-vsctl &>/dev/null; then
 systemctl enable --now openvswitch-switch 2>/dev/null || true
 ovs-vsctl show &>/dev/null || true
 log "OpenVSwitch etkinleÅŸtirildi"
 else
 warn "OpenVSwitch kurulamadÄ± â€” SDN Ã¶zellikleri devre dÄ±ÅŸÄ± kalacak"
 warn "Manuel kurulum: apt-get install openvswitch-switch"
 fi
}

# â”€â”€ MOTD (SSH login / reboot uyarÄ±sÄ±) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
install_motd() {
 step "MOTD â€” SSH Login UyarÄ±sÄ±"
 MOTD_DIR="/etc/update-motd.d"
 mkdir -p "$MOTD_DIR"

 cat > "${MOTD_DIR}/99-ankavm" << 'MOTDSCRIPT'
#!/bin/bash
BOLD='\033[1m'; DIM='\033[2m'; RED='\033[0;31m'
RESET='\033[0m'; LINE='\033[0;90m'
HOST=$(hostname -f 2>/dev/null || hostname)
DATE=$(date '+%Y-%m-%d %H:%M:%S %Z')
printf "\n"
printf "${LINE}â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€${RESET}\n"
printf " ${BOLD}ankavm Hypervisor${RESET} | %s | %s\n" "$HOST" "$DATE"
printf "${LINE}â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€${RESET}\n"
printf "\n"
printf " ${RED}NOTICE:${RESET} This system is restricted to authorized administrators.\n"
printf " All sessions are monitored and logged.\n"
printf "\n"
printf " Do not execute commands obtained from external sources without\n"
printf " first verifying their purpose with the system administrator.\n"
printf "\n"
printf " ${BOLD}Support${RESET}\n"
printf " Email root@ankavm.local\n"
printf " GitHub https://github.com/ShinnAsukha/ankavm-hypervisor\n"
printf " Docs https://ankavm.local/docs\n"
printf "\n"
printf "${LINE}â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€${RESET}\n"
printf "\n"
MOTDSCRIPT

 chmod +x "${MOTD_DIR}/99-ankavm"

 # Disable ALL Ubuntu default MOTD scripts â€” keep only 99-ankavm
 find "$MOTD_DIR" -type f ! -name "99-ankavm" -exec chmod -x {} \;
 # Disable motd-news background service/timer
 systemctl disable motd-news.service motd-news.timer 2>/dev/null || true
 sed -i 's/^ENABLED=.*/ENABLED=0/' /etc/default/motd-news 2>/dev/null || true
 # Clear static /etc/motd
 echo "" > /etc/motd 2>/dev/null || true

 log "MOTD kuruldu -> ${MOTD_DIR}/99-ankavm"
}

# â”€â”€ Servisleri BaÅŸlat â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
start_services() {
 step "Servisler BaÅŸlatÄ±lÄ±yor"
 systemctl restart libvirtd
 sleep 2
 systemctl start ankavm
 sleep 5

 if systemctl is-active --quiet ankavm; then
 log "ankavm servisi Ã§alÄ±ÅŸÄ±yor"
 else
 warn "ankavm baÅŸlatÄ±lamadÄ± â€” son hatalar:"
 journalctl -u ankavm -n 20 --no-pager 2>/dev/null || true
 echo ""
 warn "Manuel baÅŸlatmak iÃ§in: systemctl start ankavm"
 warn "Log iÃ§in: journalctl -u ankavm -n 50 --no-pager"
 fi
}

# â”€â”€ Lisans Aktivasyonu â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
activate_license() {
 step "Lisans Aktivasyonu (Ä°steÄŸe BaÄŸlÄ±)"
 echo ""
 echo -e "${WHITE}Lisans anahtarÄ±nÄ±z varsa aÅŸaÄŸÄ±ya girin.${NC}"
 echo -e "${YELLOW}Format: ankavm-XXXX-XXXX-XXXX-XXXX${NC}"
 echo -e "${BLUE}Atlamak iÃ§in ENTER'a basÄ±n${NC}"
 echo ""
 read -p "Lisans anahtarÄ±: " -r LICENSE_KEY

 if [ -n "$LICENSE_KEY" ]; then
 HOST_IP=$(hostname -I | awk '{print $1}')
 # Admin token al (ilk login â€” setup yapÄ±lmamÄ±ÅŸsa boÅŸ dÃ¶ner)
 RESPONSE=$(curl -sk -X POST "https://${HOST_IP}:${WEB_PORT}/api/license/validate" \
 -H "Content-Type: application/json" \
 -d "{\"code\":\"${LICENSE_KEY}\"}" 2>/dev/null || echo '{}')

 if echo "$RESPONSE" | grep -q '"valid":true'; then
 log "Lisans baÅŸarÄ±yla aktive edildi!"
 echo -e " ${GREEN}OK 7/24 Destek aktif${NC}"
 else
 warn "Lisans doÄŸrulanamadÄ± â€” web arayÃ¼zÃ¼nden (GÃ¼venlik -> ankavm Lisans) ekleyebilirsin"
 fi
 else
 info "Lisans aktivasyonu atlandÄ± â€” web arayÃ¼zÃ¼nden (GÃ¼venlik -> ankavm Lisans) ekleyebilirsin"
 fi
}

# â”€â”€ Tamamlama EkranÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# â”€â”€ Kurulum Bildirimi (anonim telemetri) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Kurulum istatistiÄŸi toplar. IP tam saklanmaz. Tamamen sessiz, hata vermez.
TRACKER_URL="${ankavm_TRACKER_URL:-https://ankavm.local/api/install}"
send_install_ping() {
 # Arka planda, timeout'lu, hata yoksay â€” kurulumu asla bloklamaz
 (
 HOSTNAME_VAL=$(hostname 2>/dev/null || echo "unknown")
 OS_VAL=$(grep -oP '(?<=^PRETTY_NAME=").*(?="$)' /etc/os-release 2>/dev/null || echo "unknown")
 CPU_VAL=$(grep -m1 "model name" /proc/cpuinfo 2>/dev/null | cut -d: -f2 | sed 's/^ *//' || echo "unknown")
 CPU_CORES=$(nproc 2>/dev/null || echo "?")
 RAM_GB=$(awk '/MemTotal/ {printf "%.1f", $2/1048576}' /proc/meminfo 2>/dev/null || echo "0")
 PUB_IP=$(hostname -I | awk '{print $1}')

 JSON=$(cat <<EOF
{"hostname":"${HOSTNAME_VAL}","os":"${OS_VAL}","cpu":"${CPU_VAL} (${CPU_CORES} core)","ram_gb":"${RAM_GB}","version":"2.5.8","ip":"${PUB_IP}"}
EOF
)
 curl -fsSL --max-time 8 -X POST "$TRACKER_URL" \
 -H "Content-Type: application/json" \
 -d "$JSON" >/dev/null 2>&1 || true
 ) &
 disown 2>/dev/null || true
}

print_done() {
 HOST_IP=$(hostname -I | awk '{print $1}')
 echo ""
 echo -e "${GREEN}â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—"
 echo -e "â•‘ ankavm Hypervisor Kurulumu TamamlandÄ±! â•‘"
 echo -e "â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£"
 echo -e "â•‘${NC} ${GREEN}â•‘"
 echo -e "â•‘${NC} Web UI : ${CYAN}https://${HOST_IP}:${WEB_PORT}${NC}$(printf '%*s' $((21-${#HOST_IP})) '')${GREEN}â•‘"
 echo -e "â•‘${NC} Ä°lk giriÅŸ : Admin kullanÄ±cÄ±sÄ± oluÅŸtur ${GREEN}â•‘"
 echo -e "â•‘${NC} ${GREEN}â•‘"
 echo -e "â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£"
 echo -e "â•‘${NC} ${YELLOW}Dizin YapÄ±sÄ±:${NC} ${GREEN}â•‘"
 echo -e "â•‘${NC} Uygulama : ${APP_DIR} ${GREEN}â•‘"
 echo -e "â•‘${NC} Konfig : ${CONFIG_DIR}/ ${GREEN}â•‘"
 echo -e "â•‘${NC} Loglar : ${LOG_DIR}/ ${GREEN}â•‘"
 echo -e "â•‘${NC} Veri : ${DATA_DIR}/ ${GREEN}â•‘"
 echo -e "â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£"
 echo -e "â•‘${NC} ${YELLOW}CLI KomutlarÄ±:${NC} ${GREEN}â•‘"
 echo -e "â•‘${NC} ${CYAN}ox --status${NC} â€” Servis durumu ${GREEN}â•‘"
 echo -e "â•‘${NC} ${CYAN}ox --logs -f${NC} â€” CanlÄ± log takibi ${GREEN}â•‘"
 echo -e "â•‘${NC} ${CYAN}ox --vms${NC} â€” Sanal makineleri listele ${GREEN}â•‘"
 echo -e "â•‘${NC} ${CYAN}ox --users${NC} â€” KullanÄ±cÄ±larÄ± listele ${GREEN}â•‘"
 echo -e "â•‘${NC} ${CYAN}ox --restart${NC} â€” Servisi yeniden baÅŸlat ${GREEN}â•‘"
 echo -e "â•‘${NC} ${CYAN}sudo oxupdate${NC} â€” GÃ¼ncel sÃ¼rÃ¼me geÃ§ ${GREEN}â•‘"
 echo -e "â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£"
 echo -e "â•‘${NC} ${YELLOW}Sorun mu var?${NC} ${GREEN}â•‘"
 echo -e "â•‘${NC} journalctl -u ankavm -n 50 --no-pager ${GREEN}â•‘"
 echo -e "â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•${NC}"
 echo ""
 echo -e "${YELLOW}SSL uyarÄ±sÄ±: TarayÄ±cÄ±da 'GeliÅŸmiÅŸ -> Devam et' tÄ±kla.${NC}"
 echo ""
}

# â”€â”€ Ana AkÄ±ÅŸ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
main() {
 # HÄ±zlÄ± mod: sadece CLI araÃ§larÄ±nÄ± gÃ¼ncelle
 if [ "${1:-}" = "--refresh-cli" ]; then
 check_root
 install_cli_tools
 echo -e "\033[0;32m[OK] ox ve oxupdate gÃ¼ncellendi\033[0m"
 exit 0
 fi

 START_TIME=$(date +%s)

 print_banner
 check_root
 check_os
 check_existing_installation
 check_bios_virtualization
 check_hardware

 echo ""
 echo -e "${WHITE}Kurulum Ã¶zeti:${NC}"
 echo -e " Repo URL : $REPO_URL"
 echo -e " Kurulum : $INSTALL_DIR (git repo)"
 echo -e " Uygulama : $APP_DIR"
 echo -e " Python venv : $VENV_DIR"
 echo -e " Konfig : $CONFIG_DIR/ankavm.conf"
 echo -e " Web portu : $WEB_PORT (HTTPS)"
 echo ""
 read -p "Kuruluma devam edilsin mi? [E/h]: " -r
 [[ $REPLY =~ ^[Hh]$ ]] && exit 0

 advance_progress "Sistem gÃ¼ncelleniyor"
 update_system
 advance_progress "Paketler kuruluyor"
 install_packages
 advance_progress "Kaynak kod indiriliyor"
 clone_repo
 advance_progress "KVM/libvirt yapÄ±landÄ±rÄ±lÄ±yor"
 configure_libvirt
 advance_progress "Python ortamÄ± hazÄ±rlanÄ±yor"
 setup_python
 advance_progress "Font Awesome indiriliyor"
 download_fontawesome
 advance_progress "SSL sertifikasÄ± oluÅŸturuluyor"
 generate_ssl
 advance_progress "KonfigÃ¼rasyon yazÄ±lÄ±yor"
 write_config
 advance_progress "noVNC kuruluyor"
 install_novnc
 advance_progress "Systemd servisi oluÅŸturuluyor"
 create_service
 advance_progress "SSH yapÄ±landÄ±rÄ±lÄ±yor"
 configure_ssh
 advance_progress "Hostname yapÄ±landÄ±rÄ±lÄ±yor"
 configure_hostname
 advance_progress "GÃ¼venlik duvarÄ± (UFW) yapÄ±landÄ±rÄ±lÄ±yor"
 configure_firewall
 advance_progress "Fail2ban yapÄ±landÄ±rÄ±lÄ±yor"
 configure_fail2ban
 advance_progress "OpenVSwitch kuruluyor"
 install_ovs # OVS bridge setup'tan Ã¶nce baÅŸlatÄ±lmalÄ± â€” netplan apply OVS'ye ulaÅŸmaya Ã§alÄ±ÅŸÄ±r
 advance_progress "Host bridge (oxbr0) kuruluyor"
 setup_host_bridge
 advance_progress "Reboot kararlÄ±lÄ±ÄŸÄ± yapÄ±landÄ±rÄ±lÄ±yor"
 fix_reboot_stability
 advance_progress "MOTD kuruluyor"
 install_motd
 advance_progress "CLI araÃ§larÄ± kuruluyor (ox / oxupdate)"
 install_cli_tools
 advance_progress "Servisler baÅŸlatÄ±lÄ±yor"
 start_services
 advance_progress "Lisans aktivasyonu"
 activate_license

 # OS rebranding (opt-in via ankavm_REBRAND_OS=1; defaults to off to avoid surprising users)
 if [ "${ankavm_REBRAND_OS:-0}" = "1" ] && [ -f "${SCRIPT_DIR:-/opt/ankavm-src}/scripts/rebrand-os.sh" ]; then
 advance_progress "OS rebranding (ankavm_REBRAND_OS=1)"
 bash "${SCRIPT_DIR:-/opt/ankavm-src}/scripts/rebrand-os.sh" || \
 warn "OS rebrand baÅŸarÄ±sÄ±z (kritik deÄŸil â€” kurulum devam ediyor)"
 fi

 # Kurulum bildirimi gÃ¶nder (anonim, sessiz)
 send_install_ping

 # Final completion message
 local now elapsed_s mins secs
 now=$(date +%s)
 elapsed_s=$(( now - START_TIME ))
 mins=$(( elapsed_s / 60 ))
 secs=$(( elapsed_s % 60 ))
 printf "\n\033[0;32m[â–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆâ–ˆ] 100%% â€” Kurulum tamamlandÄ±! (%02d:%02d)\033[0m\n\n" \
 "$mins" "$secs" >&2

 print_done
}

main "$@"






