#!/usr/bin/env bash
# ============================================================
#  ANKAVM Hypervisor â€” ISO Builder v5.0
#  Base : Debian 12 (Bookworm) Live Standard
#  Boot : getty autologin root â†’ startx â†’ Calamares (fullscreen)
#  Proxmox VE ile aynÄ± mantÄ±k: desktop yok, DM yok, direkt installer
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; WHITE='\033[1;37m'; NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# â”€â”€ Versiyon â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
VERSION_FILE="$SCRIPT_DIR/VERSION"
[ -f "$VERSION_FILE" ] || echo "2.0.0" > "$VERSION_FILE"
_PREV="$(cat "$VERSION_FILE" | tr -d '[:space:]')"
_MAJ="$(echo "$_PREV" | cut -d. -f1)"
_MIN="$(echo "$_PREV" | cut -d. -f2)"
_PAT="$(echo "$_PREV" | cut -d. -f3)"
_PAT=$(( _PAT + 1 ))
ANKAVM_VERSION="${_MAJ}.${_MIN}.${_PAT}"
echo "$ANKAVM_VERSION" > "$VERSION_FILE"

# â”€â”€ Paths â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Debian 12 Live Standard â€” masaÃ¼stÃ¼ yok, sadece temel sistem
# "standard" variant ~700MB, bizim ihtiyacÄ±mÄ±za tam uygun
DEBIAN_VER="12.11.0"   # fallback â€” overridden by dynamic detection below
_DEBIAN_DIR_URL="https://cdimage.debian.org/debian-cd/current-live/amd64/iso-hybrid/"
_detected_ver="$(curl -s --connect-timeout 15 "$_DEBIAN_DIR_URL" 2>/dev/null \
    | grep -oP 'debian-live-\K[\d.]+(?=-amd64-standard\.iso)' \
    | head -1)"
if [ -n "$_detected_ver" ]; then
    DEBIAN_VER="$_detected_ver"
fi
_ISO_FILE="debian-live-${DEBIAN_VER}-amd64-standard.iso"
DEBIAN_LIVE_URL="https://cdimage.debian.org/debian-cd/current-live/amd64/iso-hybrid/${_ISO_FILE}"
DEBIAN_LIVE_MIRRORS=(
    "https://cdimage.debian.org/debian-cd/current-live/amd64/iso-hybrid/${_ISO_FILE}"
    "https://mirrors.kernel.org/debian-cd/current-live/amd64/iso-hybrid/${_ISO_FILE}"
    "https://mirror.csclub.uwaterloo.ca/debian-cd/current-live/amd64/iso-hybrid/${_ISO_FILE}"
    "https://ftp.halifax.rwth-aachen.de/debian-cd/current-live/amd64/iso-hybrid/${_ISO_FILE}"
    "https://mirror.init7.net/debian-cd/current-live/amd64/iso-hybrid/${_ISO_FILE}"
)
ISO_CACHE="/tmp/debian-12-live-standard-amd64.iso"
WORK_DIR="/tmp/ankavm-iso-build"
SQUASHFS_ROOT="$WORK_DIR/squashfs-root"
OUTPUT_ISO="$REPO_ROOT/ANKAVM-Hypervisor-${ANKAVM_VERSION}-amd64.iso"

log()  { echo -e "${GREEN}[BUILD]${NC}  $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}   $1"; }
err()  { echo -e "${RED}[ERROR]${NC}  $1"; exit 1; }
step() { echo -e "\n${CYAN}â”â”â” $1 â”â”â”${NC}"; }

[[ $EUID -ne 0 ]] && err "Root gerekli: sudo bash build/build-iso.sh"

# â”€â”€ BaÄŸÄ±mlÄ±lÄ±klar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "BaÄŸÄ±mlÄ±lÄ±klar"
apt-get update -qq
apt-get install -y -qq \
    xorriso squashfs-tools wget curl \
    grub-pc-bin grub-efi-amd64-bin mtools \
    debootstrap rsync python3 \
    genisoimage syslinux-utils 2>/dev/null || true

# gh CLI â€” GitHub release iÃ§in (opsiyonel, yoksa kurmaya Ã§alÄ±ÅŸ)
if ! command -v gh &>/dev/null; then
    warn "gh CLI bulunamadÄ±, kuruluyor..."
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null || true
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list 2>/dev/null || true
    apt-get update -qq 2>/dev/null && apt-get install -y -qq gh 2>/dev/null || \
        warn "gh kurulamadÄ± â€” GitHub release otomatik atlanacak"
fi
log "OK"

# â”€â”€ Disk alanÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_FREE_KB=$(df -k "$PWD" | awk 'NR==2{print $4}')
[ "$_FREE_KB" -lt 15728640 ] && \
    err "Yetersiz disk: $(df -h "$PWD" | awk 'NR==2{print $4}'), en az 15GB gerek"
log "Disk: $(df -h "$PWD" | awk 'NR==2{print $4}') boÅŸ"

# â”€â”€ Debian 12 Live ISO â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "Debian 12 Live Standard ISO"

# 1. Exact cache path exists and is large enough
if [ -f "$ISO_CACHE" ] && [ "$(stat -c%s "$ISO_CACHE" 2>/dev/null || echo 0)" -gt 500000000 ]; then
    log "Cache'de mevcut: $ISO_CACHE ($(du -sh "$ISO_CACHE" | cut -f1))"
else
    # 2. Scan /tmp for any Debian Live ISO already downloaded (any version/name)
    _found_iso=""
    while IFS= read -r -d '' _f; do
        _sz="$(stat -c%s "$_f" 2>/dev/null || echo 0)"
        if [ "$_sz" -gt 500000000 ]; then
            _found_iso="$_f"
            break
        fi
    done < <(find /tmp -maxdepth 2 -name "debian-live-*.iso" -print0 2>/dev/null)

    if [ -n "$_found_iso" ]; then
        log "Mevcut Debian ISO bulundu: $_found_iso ($(du -sh "$_found_iso" | cut -f1))"
        if [ "$_found_iso" != "$ISO_CACHE" ]; then
            log "ISO_CACHE'e baÄŸlanÄ±yor: $ISO_CACHE"
            ln -sf "$_found_iso" "$ISO_CACHE" 2>/dev/null \
                || cp "$_found_iso" "$ISO_CACHE"
        fi
    else
        # 3. Nothing cached â€” download from mirrors
        log "Ä°ndiriliyor... (${#DEBIAN_LIVE_MIRRORS[@]} mirror denenecek)"
        _dl_ok=false
        for _mirror in "${DEBIAN_LIVE_MIRRORS[@]}"; do
            log "Mirror: $_mirror"
            if wget -q --show-progress --tries=3 --timeout=60 -c -O "$ISO_CACHE" "$_mirror" 2>/dev/null; then
                _dl_ok=true
                break
            fi
            warn "Mirror baÅŸarÄ±sÄ±z: $_mirror"
        done
        if ! $_dl_ok; then
            err "TÃ¼m mirrorlar baÅŸarÄ±sÄ±z. Manuel indirme:\n  wget -O $ISO_CACHE $DEBIAN_LIVE_URL"
        fi
    fi
fi

# â”€â”€ ISO AyÄ±kla â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "ISO AyÄ±klama"
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR/iso"
xorriso -osirrox on -indev "$ISO_CACHE" -extract / "$WORK_DIR/iso" 2>/dev/null \
    || err "ISO ayÄ±klanamadÄ±"
chmod -R u+w "$WORK_DIR/iso"
log "ISO iÃ§eriÄŸi: $(du -sh "$WORK_DIR/iso" | cut -f1)"

# Debian live squashfs: /live/filesystem.squashfs
SQUASHFS_FILE=""
for f in \
    "$WORK_DIR/iso/live/filesystem.squashfs" \
    "$WORK_DIR/iso/casper/filesystem.squashfs"; do
    [ -f "$f" ] && SQUASHFS_FILE="$f" && break
done
[ -z "$SQUASHFS_FILE" ] && err "filesystem.squashfs bulunamadÄ±!"

# Live dizini bul (grub path iÃ§in)
LIVE_DIR="$(dirname "$SQUASHFS_FILE" | sed "s|$WORK_DIR/iso||")"
log "Squashfs: $SQUASHFS_FILE ($(du -sh "$SQUASHFS_FILE" | cut -f1))"
log "Live dir: $LIVE_DIR"

# â”€â”€ Squashfs AÃ§ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "Squashfs AÃ§Ä±lÄ±yor (~5-10 dk)"
unsquashfs -d "$SQUASHFS_ROOT" "$SQUASHFS_FILE"
log "AÃ§Ä±ldÄ±: $(du -sh "$SQUASHFS_ROOT" | cut -f1)"

# â”€â”€ Chroot: Paket Kurulum â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "Chroot: Calamares + X11 Kurulum (~10 dk)"

mkdir -p "$SQUASHFS_ROOT"/{proc,sys,dev,dev/pts,run,tmp}
cp /etc/resolv.conf "$SQUASHFS_ROOT/etc/resolv.conf" 2>/dev/null || true

_cleanup() {
    local _ec=$?
    # Chroot bind mount'larÄ± kaldÄ±r (zaten yoksa zararsÄ±z)
    for mp in dev/pts dev sys proc run; do
        umount "$SQUASHFS_ROOT/$mp" 2>/dev/null || true
    done
    # Ã‡alÄ±ÅŸma dizinini temizle â€” baÅŸarÄ± veya baÅŸarÄ±sÄ±zlÄ±k fark etmez
    if [ -d "$WORK_DIR" ]; then
        rm -rf "$WORK_DIR" 2>/dev/null || true
        echo -e "${YELLOW}[CLEAN]${NC}  Ã‡alÄ±ÅŸma dizini silindi: $WORK_DIR"
    fi
    [ "$_ec" -ne 0 ] && \
        echo -e "${RED}[BUILD FAILED]${NC} Ã‡Ä±kÄ±ÅŸ kodu: $_ec" || true
}
trap _cleanup EXIT

mount --bind /proc    "$SQUASHFS_ROOT/proc"
mount --bind /sys     "$SQUASHFS_ROOT/sys"
mount --bind /dev     "$SQUASHFS_ROOT/dev"
mount --bind /dev/pts "$SQUASHFS_ROOT/dev/pts"
mount --bind /run     "$SQUASHFS_ROOT/run"

chroot "$SQUASHFS_ROOT" /bin/bash << 'CHROOT'
export DEBIAN_FRONTEND=noninteractive
export LANG=C

# adduser/usbmuxd postinst uyarÄ±sÄ±nÄ± Ã¶nle
mkdir -p /var/lib/usbmux

# Debian 12 repo (backports dahil â€” Calamares yeni versiyonu iÃ§in)
cat > /etc/apt/sources.list << 'APT'
deb http://deb.debian.org/debian bookworm main contrib non-free non-free-firmware
deb http://deb.debian.org/debian bookworm-updates main contrib
deb http://security.debian.org/debian-security bookworm-security main contrib
deb http://deb.debian.org/debian bookworm-backports main contrib
APT

apt-get update -qq || { echo "[ERROR] apt-get update baÅŸarÄ±sÄ±z â€” network/DNS kontrolÃ¼ yap"; exit 1; }

# â”€â”€ ZORUNLU: xinit (startx saÄŸlar) â€” hata olursa build dur â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
apt-get install -y --no-install-recommends xinit || {
    echo "[FATAL] xinit kurulamadÄ±. 'startx' ISO'da olmayacak â€” build durduruluyor."
    exit 1
}

# â”€â”€ ZORUNLU: Xorg (X server binary saÄŸlar) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
apt-get install -y --no-install-recommends xserver-xorg-core xserver-xorg-input-all || {
    echo "[FATAL] xserver-xorg-core kurulamadÄ± â€” Xorg binary olmayacak. Build durduruluyor."
    exit 1
}

# â”€â”€ ZORUNLU: openbox (pencere yÃ¶neticisi â€” Qt/Tk render iÃ§in ÅŸart) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
apt-get install -y --no-install-recommends openbox || {
    echo "[FATAL] openbox kurulamadÄ±. Build durduruluyor."
    exit 1
}

# â”€â”€ Minimal X11 eklentiler (opsiyonel â€” hata olsa devam) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
apt-get install -y -qq --no-install-recommends \
    xorg \
    xserver-xorg-video-all \
    x11-xserver-utils \
    2>/dev/null || true

# â”€â”€ Calamares â€” tam baÄŸÄ±mlÄ±lÄ±klarÄ±yla kur (--no-install-recommends YASAK) â”€â”€â”€â”€â”€
echo "[*] Calamares kuruluyor..."
# calamares-data yalnÄ±zca Ubuntu/Kubuntu'da vardÄ±r â€” Debian'da yok, sadece calamares kur
apt-get install -y -t bookworm-backports calamares || \
apt-get install -y calamares || \
{ echo "[WARN] Calamares backports/stable baÅŸarÄ±sÄ±z, minimal deneniyor..."; \
  apt-get install -y --no-install-recommends calamares || true; }

# Calamares ek baÄŸÄ±mlÄ±lÄ±klarÄ± (kpmcore + Python partition)
apt-get install -y -qq --no-install-recommends \
    python3-yaml python3-parted \
    parted dosfstools e2fsprogs \
    2>/dev/null || true

# â”€â”€ Disk / aÄŸ araÃ§larÄ± (install.py --headless iÃ§in) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
apt-get install -y -qq --no-install-recommends \
    debootstrap \
    util-linux \
    iproute2 \
    net-tools \
    dhcpcd5 \
    curl \
    git \
    sudo \
    2>/dev/null || true

# â”€â”€ GUI / font / D-Bus araÃ§larÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
apt-get install -y -qq --no-install-recommends \
    python3-tk \
    fonts-ubuntu \
    fonts-noto-core \
    fontconfig \
    xterm \
    dbus \
    dbus-x11 \
    libdbus-1-3 \
    policykit-1 \
    udisks2 \
    xserver-xorg-video-qxl \
    xserver-xorg-video-vmware \
    xserver-xorg-video-fbdev \
    xserver-xorg-video-vesa \
    spice-vdagent \
    libqt5network5 \
    libqt5svg5 \
    xfonts-base \
    x11-apps \
    dmz-cursor-theme \
    python3-pyqt5 \
    2>/dev/null || true
fc-cache -f 2>/dev/null || true

# â”€â”€ TÃ¼rkÃ§e locale â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
apt-get install -y -qq locales 2>/dev/null || true
sed -i 's/# tr_TR.UTF-8/tr_TR.UTF-8/' /etc/locale.gen 2>/dev/null || true
sed -i 's/# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen 2>/dev/null || true
locale-gen 2>/dev/null || true

# â”€â”€ Root ÅŸifresi (installer ortamÄ± iÃ§in) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "root:ankavm" | chpasswd

# â”€â”€ Calamares binary kontrol â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if ! command -v calamares &>/dev/null; then
    echo "[WARN] calamares bulunamadÄ± â€” alternatif kaynak deneniyor..."
    apt-get install -y -qq calamares 2>/dev/null || true
fi
_CALA=$(command -v calamares 2>/dev/null || echo "")
echo "[INFO] calamares: ${_CALA:-BULUNAMADI}"
if [ -z "$_CALA" ]; then
    echo "[ERROR] Calamares kurulum BAÅARISIZ"
    exit 1
fi
echo "[OK] Chroot tamamlandÄ±"
CHROOT

# Bind mount'larÄ± burda kaldÄ±r â€” mksquashfs /proc okumadan Ã¶nce
for mp in dev/pts dev sys proc run; do
    umount "$SQUASHFS_ROOT/$mp" 2>/dev/null || true
done
log "Chroot paketler OK"

# â”€â”€ Kritik dosya doÄŸrulama â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "Kritik dosya doÄŸrulama"
_missing=0
# startx
if [ ! -f "$SQUASHFS_ROOT/usr/bin/startx" ]; then
    warn "EKSÄ°K: $SQUASHFS_ROOT/usr/bin/startx"
    _missing=1
else
    log "OK: usr/bin/startx"
fi

# Xorg: Debian 12'de /usr/lib/xorg/Xorg veya /usr/bin/Xorg olabilir
_xorg_found=0
for _xorgpath in \
    "$SQUASHFS_ROOT/usr/bin/Xorg" \
    "$SQUASHFS_ROOT/usr/lib/xorg/Xorg" \
    "$SQUASHFS_ROOT/usr/libexec/Xorg"
do
    if [ -f "$_xorgpath" ]; then
        log "OK: ${_xorgpath#$SQUASHFS_ROOT/}"
        _xorg_found=1
        break
    fi
done
if [ "$_xorg_found" -eq 0 ]; then
    warn "EKSÄ°K: Xorg binary (usr/bin/Xorg, usr/lib/xorg/Xorg â€” hiÃ§birinde yok)"
    _missing=1
fi

# openbox
if [ ! -f "$SQUASHFS_ROOT/usr/bin/openbox" ]; then
    warn "EKSÄ°K: $SQUASHFS_ROOT/usr/bin/openbox"
    _missing=1
else
    log "OK: usr/bin/openbox"
fi

[ "$_missing" -eq 1 ] && err "Kritik binary eksik â€” build iptal. Chroot iÃ§inde paket kurulumu baÅŸarÄ±sÄ±z olmuÅŸ olabilir."

# â”€â”€ ankavm Calamares Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "ankavm Calamares KonfigÃ¼rasyonu"

CALA_SRC="$SCRIPT_DIR/calamares"

rm -rf "$SQUASHFS_ROOT/etc/calamares"
mkdir -p "$SQUASHFS_ROOT/etc/calamares/modules"

cp "$CALA_SRC/settings.conf" "$SQUASHFS_ROOT/etc/calamares/"

for conf in welcome locale keyboard users summary finished; do
    [ -f "$CALA_SRC/modules/${conf}.conf" ] && \
        cp "$CALA_SRC/modules/${conf}.conf" "$SQUASHFS_ROOT/etc/calamares/modules/"
done
# partition.conf artÄ±k kullanÄ±lmÄ±yor â€” oxdisk QML modÃ¼lÃ¼ kpmcore olmadan Ã§alÄ±ÅŸÄ±r

# Custom Python job (Calamares â†’ install.py --headless)
mkdir -p "$SQUASHFS_ROOT/usr/lib/calamares/modules/ankavm_install"
cp "$CALA_SRC/modules/ankavm_install/module.desc" \
   "$SQUASHFS_ROOT/usr/lib/calamares/modules/ankavm_install/"
cp "$CALA_SRC/modules/ankavm_install/main.py" \   "$SQUASHFS_ROOT/usr/lib/calamares/modules/ankavm_install/"

# ANKAVM network viewmodule (Calamares QML â€” aÄŸ yapÄ±landÄ±rmasÄ± adÄ±mÄ±)
mkdir -p "$SQUASHFS_ROOT/usr/lib/calamares/modules/oxnetwork"
cp "$CALA_SRC/modules/oxnetwork/module.desc" \
   "$SQUASHFS_ROOT/usr/lib/calamares/modules/oxnetwork/"
cp "$CALA_SRC/modules/oxnetwork/oxnetwork.qml" \
   "$SQUASHFS_ROOT/usr/lib/calamares/modules/oxnetwork/"

# ANKAVM disk seÃ§imi viewmodule (kpmcore olmadan â€” kpmcore 2% donmasÄ±nÄ± Ã¶nler)
mkdir -p "$SQUASHFS_ROOT/usr/lib/calamares/modules/oxdisk"
cp "$CALA_SRC/modules/oxdisk/module.desc" \
   "$SQUASHFS_ROOT/usr/lib/calamares/modules/oxdisk/"
cp "$CALA_SRC/modules/oxdisk/oxdisk.qml" \
   "$SQUASHFS_ROOT/usr/lib/calamares/modules/oxdisk/"

# ANKAVM branding
mkdir -p "$SQUASHFS_ROOT/usr/share/calamares/branding/ankavm"
cp "$CALA_SRC/branding/ankavm/branding.desc" \
   "$SQUASHFS_ROOT/usr/share/calamares/branding/ankavm/"
cp "$CALA_SRC/branding/ankavm/show.qml" \
   "$SQUASHFS_ROOT/usr/share/calamares/branding/ankavm/"

if [ -f "$REPO_ROOT/ankavm/frontend/static/img/ankavm2.png" ]; then
    cp "$REPO_ROOT/ankavm/frontend/static/img/ankavm2.png" \
       "$SQUASHFS_ROOT/usr/share/calamares/branding/ankavm/ankavm_logo.png"
    cp "$REPO_ROOT/ankavm/frontend/static/img/ankavm2.png" \
       "$SQUASHFS_ROOT/usr/share/calamares/branding/ankavm/ankavm_welcome.png"
fi
[ -f "$REPO_ROOT/ankavm/frontend/static/img/sadeceikon.png" ] && \
    cp "$REPO_ROOT/ankavm/frontend/static/img/sadeceikon.png" \
       "$SQUASHFS_ROOT/usr/share/calamares/branding/ankavm/ankavm_icon.png"

# Xorg minimal config (driver otomatik â€” KVM, VMware, nomodeset destekli)
mkdir -p "$SQUASHFS_ROOT/etc/X11/xorg.conf.d"
cat > "$SQUASHFS_ROOT/etc/X11/xorg.conf.d/10-ankavm.conf" << 'XORGCONF'
# ANKAVM Display â€” Driver AÃ‡IKÃ‡A belirtilmedi: Xorg otomatik seÃ§er
# KVM/QEMU (qxl, cirrus, vga), VMware (vmware), nomodeset (fbdev/vesa)
# modesetting belirtmek â†’ DRM olmayan VM'lerde (nomodeset, basic VGA) SIYAH EKRAN
Section "Device"
    Identifier "ANKAVM-Display"
    Option     "SWcursor" "true"
EndSection

Section "Screen"
    Identifier "Default Screen"
    DefaultDepth 24
    SubSection "Display"
        Depth    24
        Modes    "1024x768" "800x600" "1280x1024"
    EndSubSection
EndSection
XORGCONF

log "Calamares config OK"

# â”€â”€ ANKAVM Installer Backend â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "ANKAVM Backend"

mkdir -p "$SQUASHFS_ROOT/opt/ankavm-installer"
cp "$SCRIPT_DIR/installer/install.py" "$SQUASHFS_ROOT/opt/ankavm-installer/"
chmod +x "$SQUASHFS_ROOT/opt/ankavm-installer/install.py"

# AÄŸ yapÄ±landÄ±rma GUI (Calamares sonrasÄ± Ã§alÄ±ÅŸÄ±r)
[ -f "$SCRIPT_DIR/installer/netcfg-gui.py" ] && {
    cp "$SCRIPT_DIR/installer/netcfg-gui.py" "$SQUASHFS_ROOT/opt/ankavm-installer/"
    chmod +x "$SQUASHFS_ROOT/opt/ankavm-installer/netcfg-gui.py"
    log "netcfg-gui.py kopyalandÄ±"
}
# AÄŸ config uygulayÄ±cÄ± (kurulumdan sonra kurulu sisteme yazar)
[ -f "$SCRIPT_DIR/installer/apply-netcfg.py" ] && {
    cp "$SCRIPT_DIR/installer/apply-netcfg.py" "$SQUASHFS_ROOT/opt/ankavm-installer/"
    chmod +x "$SQUASHFS_ROOT/opt/ankavm-installer/apply-netcfg.py"
    log "apply-netcfg.py kopyalandÄ±"
}

# debootstrap
[ -f "/usr/sbin/debootstrap" ] && {
    cp /usr/sbin/debootstrap "$SQUASHFS_ROOT/usr/sbin/debootstrap"
    chmod +x "$SQUASHFS_ROOT/usr/sbin/debootstrap"
}
[ -d "/usr/share/debootstrap" ] && {
    mkdir -p "$SQUASHFS_ROOT/usr/share/debootstrap"
    cp -r /usr/share/debootstrap/. "$SQUASHFS_ROOT/usr/share/debootstrap/"
}
for kdir in /usr/share/keyrings /etc/apt/trusted.gpg.d; do
    [ -d "$kdir" ] && {
        mkdir -p "$SQUASHFS_ROOT$kdir"
        cp "$kdir"/*.gpg "$SQUASHFS_ROOT$kdir/" 2>/dev/null || true
        cp "$kdir"/*.asc "$SQUASHFS_ROOT$kdir/" 2>/dev/null || true
    }
done

# ankavm web backend (offline)
rsync -a --exclude='.git' --exclude='*.pyc' --exclude='__pycache__' \
    "$REPO_ROOT/ankavm/" "$SQUASHFS_ROOT/opt/ankavm/"

log "Backend OK"

# â”€â”€ Boot: getty autologin root â†’ startx â†’ Calamares â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PROXMOX VE ile AYNI mantÄ±k: display manager YOK, desktop YOK
# Sadece: tty1 autologin â†’ X11 â†’ Calamares fullscreen
step "Boot: getty autologin root â†’ Calamares"

# 1. getty@tty1 autologin root
mkdir -p "$SQUASHFS_ROOT/etc/systemd/system/getty@tty1.service.d"
cat > "$SQUASHFS_ROOT/etc/systemd/system/getty@tty1.service.d/autologin.conf" << 'GETTY'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
Type=simple
GETTY

# 2. root .bash_profile: tty1'de otomatik startx
cat > "$SQUASHFS_ROOT/root/.bash_profile" << 'BASHPROF'
# ankavm Installer: tty1'de otomatik X baÅŸlat
if [ "$(tty)" = "/dev/tty1" ] && [ -z "$DISPLAY" ]; then
    # startx binary kontrol â€” eksikse anlamlÄ± hata ver
    if ! command -v startx &>/dev/null; then
        echo ""
        echo "============================================"
        echo "  HATA: startx bulunamadÄ± (kod: 127)"
        echo "  xinit paketi ISO'ya dahil edilmemiÅŸ."
        echo "  Acil dÃ¼zeltme iÃ§in:"
        echo "    apt-get install -y xinit"
        echo "  Sonra: startx /opt/ankavm-installer/ankavm-start.sh"
        echo "============================================"
        exec bash
    fi
    # exec kullanma â€” hata durumunda loglara bakabilmek iÃ§in
    startx /opt/ankavm-installer/ankavm-start.sh -- :0 -nolisten tcp vt1 \
        2>/tmp/startx-error.log
    _EC=$?
    if [ "$_EC" -ne 0 ]; then
        echo ""
        echo "============================================"
        echo "  X BAÅLATMA HATASI (kod: $_EC)"
        echo "============================================"
        echo "--- /tmp/startx-error.log (son 30 satÄ±r) ---"
        tail -30 /tmp/startx-error.log 2>/dev/null || echo "(log yok)"
        echo "--- /tmp/Xorg.0.log (son 20 satÄ±r) ---"
        tail -20 /tmp/Xorg.0.log 2>/dev/null || echo "(log yok)"
        echo ""
        echo "Yeniden denemek iÃ§in Enter'a basÄ±n (Ctrl+C ile Ã§Ä±kabilirsiniz)..."
        read -r _DUMMY
        exec bash
    fi
fi
BASHPROF

# 2b. /etc/profile.d fallback â€” hem root hem "user" iÃ§in Ã§alÄ±ÅŸÄ±r
# live-config "user" autologin'i kazanÄ±rsa bu devreye girer
cat > "$SQUASHFS_ROOT/etc/profile.d/ankavm-installer.sh" << 'PROFILED'
# ANKAVM Installer: tty1'de otomatik X baÅŸlat (root veya user)
if [ "$(tty)" = "/dev/tty1" ] && [ -z "$DISPLAY" ]; then
    if [ "$(id -u)" -eq 0 ]; then
        startx /opt/ankavm-installer/ankavm-start.sh -- :0 -nolisten tcp vt1 \
            2>/tmp/startx-error.log
        _EC=$?
        if [ "$_EC" -ne 0 ]; then
            echo "X HATASI (kod: $_EC) â€” /tmp/startx-error.log ve /tmp/Xorg.0.log inceleyin"
            tail -20 /tmp/startx-error.log 2>/dev/null || true
            tail -15 /tmp/Xorg.0.log 2>/dev/null || true
            echo "Enter ile devam..."
            read -r _D
        fi
    else
        sudo -n startx /opt/ankavm-installer/ankavm-start.sh -- :0 -nolisten tcp vt1 \
            2>/tmp/startx-error.log || \
            echo "X baÅŸlatÄ±lamadÄ± â€” /tmp/startx-error.log inceleyin"
    fi
fi
PROFILED
chmod +x "$SQUASHFS_ROOT/etc/profile.d/ankavm-installer.sh"

# sudoers: "user" da startx Ã§alÄ±ÅŸtÄ±rabilsin (live-config fallback iÃ§in)
echo "user ALL=(root) NOPASSWD: /usr/bin/startx" \
    > "$SQUASHFS_ROOT/etc/sudoers.d/ankavm-user"
chmod 440 "$SQUASHFS_ROOT/etc/sudoers.d/ankavm-user"

# 3. ankavm-start.sh: X oturumu baÅŸlat
cat > "$SQUASHFS_ROOT/opt/ankavm-installer/ankavm-start.sh" << 'STARTSH'
#!/bin/bash
# ankavm X Installer Session â€” Network config then Calamares
LOG=/tmp/ankavm-start.log
exec >> "$LOG" 2>&1
echo "=== ankavm start: $(date) uid=$(id -u) ==="

# PATH â€” minimal X oturumunda eksik olabilir
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

export DISPLAY=:0
export HOME=/root
export XDG_RUNTIME_DIR=/tmp/xdg-ankavm
export LANG=tr_TR.UTF-8
export FONTCONFIG_PATH=/etc/fonts
# Qt5 xcb platform â€” X11 gerekli
export QT_QPA_PLATFORM=xcb
export QT_QPA_PLATFORMTHEME=
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

# Lacivert arka plan
xsetroot -solid '#0d2340' 2>/dev/null || true
xrandr --auto 2>/dev/null || true
echo "X11 hazÄ±r"

# D-Bus system + session bus (Calamares partition backend iÃ§in zorunlu)
if command -v dbus-daemon &>/dev/null; then
    dbus-daemon --system 2>/dev/null || true
    sleep 0.5
fi
if command -v dbus-launch &>/dev/null; then
    eval "$(dbus-launch --auto-syntax)" || true
    echo "D-Bus session: $DBUS_SESSION_BUS_ADDRESS"
fi
# udisks2 â€” Calamares disk listesi iÃ§in
if command -v udisksd &>/dev/null; then
    udisksd --no-debug 2>/dev/null &
    sleep 0.5
fi

# Font cache
fc-cache -f 2>/dev/null || true

# Minimal window manager â€” tkinter + Qt pencere render iÃ§in gerekli
if command -v openbox &>/dev/null; then
    openbox --sm-disable &
    sleep 0.8
    echo "openbox baÅŸlatÄ±ldÄ±"
fi

# Ä°mleÃ§ â€” DMZ-White tema + X root cursor (openbox baÅŸladÄ±ktan sonra set edilmeli)
export XCURSOR_THEME=DMZ-White
export XCURSOR_SIZE=24
if command -v xsetroot &>/dev/null; then
    xsetroot -cursor_name left_ptr 2>/dev/null || true
fi

# â”€â”€ Otomatik DHCP + aÄŸ bilgisini QML modÃ¼lÃ¼ iÃ§in yaz â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_IFACE=$(ip -o link show 2>/dev/null \
    | awk -F': ' '$2 !~ /^(lo|vir|docker|br[0-9]|veth|dummy)/ {print $2; exit}')
if [ -n "$_IFACE" ]; then
    echo "Auto-DHCP: $_IFACE"
    (dhclient "$_IFACE" 2>/tmp/dhclient.log || \
     dhcpcd -n "$_IFACE" 2>/tmp/dhcpcd.log) &
    # Interface adÄ±nÄ± QML modÃ¼lÃ¼nÃ¼n okuyabileceÄŸi dosyaya yaz
    echo "$_IFACE" > /tmp/ankavm-iface.txt
    # KÄ±sa bekle sonra IP bilgisini yaz (DHCP bitince)
    sleep 2
    _IP=$(ip -4 -o addr show "$_IFACE" 2>/dev/null \
        | awk '{split($4,a,"/"); print a[1]; exit}')
    printf '{"iface":"%s","ip":"%s"}\n' "$_IFACE" "$_IP" \
        > /tmp/ankavm-netinfo.json
fi

# â”€â”€ polkitd baÅŸlat (kpmcore / udisks2 yetkilendirme iÃ§in) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if command -v polkitd &>/dev/null; then
    polkitd --no-debug 2>/dev/null &
    sleep 0.5
    echo "polkitd baÅŸlatÄ±ldÄ±"
elif command -v /usr/lib/polkit-1/polkitd &>/dev/null; then
    /usr/lib/polkit-1/polkitd --no-debug 2>/dev/null &
    sleep 0.5
    echo "polkitd baÅŸlatÄ±ldÄ± (/usr/lib/polkit-1/)"
fi

# â”€â”€ oxdisk QML modÃ¼lÃ¼ iÃ§in disk listesi oluÅŸtur â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "Disk listesi oluÅŸturuluyor..."
lsblk -d -J -o NAME,SIZE,TYPE,MODEL,TRAN,RM 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
disks = [d for d in data.get('blockdevices',[])
         if d.get('type','')=='disk' and str(d.get('rm','1'))=='0']
with open('/tmp/ankavm-disks.json','w') as f:
    json.dump({'blockdevices': disks}, f, indent=2)
print(f'Disk sayÄ±sÄ±: {len(disks)}')
for d in disks:
    print(f'  /dev/{d[\"name\"]}  {d[\"size\"]}  {d.get(\"model\",\"\")}')
" 2>/dev/null || \
lsblk -d -n -o NAME,SIZE,TYPE,MODEL,TRAN,RM 2>/dev/null \
    | awk '$3=="disk" && $6=="0" {print $1,$2,$4,$5}' \
    | python3 -c "
import sys, json
disks = []
for ln in sys.stdin:
    p = ln.strip().split()
    if p:
        disks.append({'name':p[0],'size':p[1] if len(p)>1 else '?',
                      'model':' '.join(p[2:]) if len(p)>2 else ''})
with open('/tmp/ankavm-disks.json','w') as f:
    json.dump({'blockdevices': disks}, f, indent=2)
print(f'Disk sayÄ±sÄ± (fallback): {len(disks)}')
" 2>/dev/null || echo '{"blockdevices":[]}' > /tmp/ankavm-disks.json

echo "Disk listesi hazÄ±r: $(cat /tmp/ankavm-disks.json | python3 -c 'import sys,json;d=json.load(sys.stdin);print(len(d[\"blockdevices\"]),\"disk\")'  2>/dev/null)"

# â”€â”€ Calamares fullscreen kurulum â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo "Calamares baÅŸlÄ±yor..."
/usr/bin/calamares -D 6 > /tmp/calamares.log 2>&1
_EXIT=$?
echo "Calamares Ã§Ä±ktÄ±: $_EXIT"

# install.py baÅŸarÄ±yla bitti mi? Marker dosyasÄ±na bak (Calamares exit=0 gÃ¼venilmez)
if [ -f /tmp/ankavm-install-success ]; then
    # â”€â”€ Kurulum baÅŸarÄ±lÄ± â€” AÄŸ YapÄ±landÄ±rmasÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    echo "AÄŸ yapÄ±landÄ±rmasÄ± baÅŸlÄ±yor..."
    xsetroot -solid '#0d2340' 2>/dev/null || true
    timeout 180 python3 /opt/ankavm-installer/netcfg-gui.py \
        2>/tmp/netcfg-gui.log || true

    # netcfg-gui Ã§Ä±ktÄ±ktan sonra kurulu sisteme aÄŸ config yaz
    if [ -f /tmp/oxnetwork.json ] || [ -f /tmp/ankavm-netcfg.json ]; then
        _CFGFILE=/tmp/oxnetwork.json
        [ -f /tmp/ankavm-netcfg.json ] && _CFGFILE=/tmp/ankavm-netcfg.json
        echo "AÄŸ config kurulu sisteme uygulanÄ±yor: $_CFGFILE"
        python3 /opt/ankavm-installer/apply-netcfg.py "$_CFGFILE" \
            2>/tmp/apply-netcfg.log || true
    fi

    # Reboot
    echo "Sistem yeniden baÅŸlatÄ±lÄ±yor..."
    sleep 3
    reboot
else
    # â”€â”€ Kurulum baÅŸarÄ±sÄ±z â€” debug ekranÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    xterm -bg '#0d2340' -fg '#c5d8f0' -fs 12 \
        -title 'ankavm â€” Hata AyÄ±klama' \
        -e "bash -c \"echo '=== Calamares Log (son 60 satÄ±r) ==='; \
            tail -60 /tmp/calamares.log 2>/dev/null || echo 'log yok'; \
            echo; echo '=== Install Log ==='; \
            tail -100 /tmp/install.log 2>/dev/null || echo 'install log yok'; \
            echo; echo '=== BaÅŸlatma Log ==='; cat $LOG 2>/dev/null; \
            echo; echo 'Ã‡Ä±kmak iÃ§in Enter'; read\"" \
        2>/dev/null || true
fi
STARTSH
chmod +x "$SQUASHFS_ROOT/opt/ankavm-installer/ankavm-start.sh"

# 4. sudoers (Calamares bazÄ± Ã§aÄŸrÄ±lar iÃ§in)
echo "root ALL=(ALL) NOPASSWD: ALL" \
    > "$SQUASHFS_ROOT/etc/sudoers.d/ankavm-root"
chmod 440 "$SQUASHFS_ROOT/etc/sudoers.d/ankavm-root"

# 5. systemd default target: multi-user (graphical deÄŸil â€” DM yok)
ln -sf /lib/systemd/system/multi-user.target \
    "$SQUASHFS_ROOT/etc/systemd/system/default.target" 2>/dev/null || true

log "getty autologin root â†’ Calamares OK"

# â”€â”€ Squashfs Yeniden Paketle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "Squashfs Paketleniyor (~10-15 dk)"
rm -f "$SQUASHFS_FILE"
mksquashfs "$SQUASHFS_ROOT" "$SQUASHFS_FILE" \
    -comp xz -noappend -b 1M -no-progress
printf '%s' "$(du -sx --block-size=1 "$SQUASHFS_ROOT" | cut -f1)" \
    > "$(dirname "$SQUASHFS_FILE")/filesystem.size"
log "Squashfs: $(du -sh "$SQUASHFS_FILE" | cut -f1)"

# â”€â”€ GRUB Boot MenÃ¼sÃ¼ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "GRUB Boot MenÃ¼sÃ¼"

# Kernel ve initrd yollarÄ±nÄ± bul
VMLINUZ_PATH=""
INITRD_PATH=""
for vp in "${LIVE_DIR}/vmlinuz" "${LIVE_DIR}/vmlinuz.efi" "/casper/vmlinuz"; do
    [ -f "$WORK_DIR/iso$vp" ] && VMLINUZ_PATH="$vp" && break
done
for ip in "${LIVE_DIR}/initrd" "${LIVE_DIR}/initrd.img" "${LIVE_DIR}/initrd.gz" "/casper/initrd"; do
    [ -f "$WORK_DIR/iso$ip" ] && INITRD_PATH="$ip" && break
done
[ -z "$VMLINUZ_PATH" ] && VMLINUZ_PATH="${LIVE_DIR}/vmlinuz"
[ -z "$INITRD_PATH"  ] && INITRD_PATH="${LIVE_DIR}/initrd"

log "vmlinuz: $VMLINUZ_PATH"
log "initrd:  $INITRD_PATH"

mkdir -p "$WORK_DIR/iso/boot/grub"
cat > "$WORK_DIR/iso/boot/grub/grub.cfg" << GRUBEOF
set default=0
set timeout=5

insmod all_video
insmod gfxterm
terminal_output gfxterm

# ankavm boot ekranÄ±
background_color 10,23,40

menuentry "ankavm Hypervisor ${ankavm_VERSION} â€” Install" --class ankavm {
    linux   ${VMLINUZ_PATH} boot=live components loglevel=3 live-config.noautologin ---
    initrd  ${INITRD_PATH}
}

menuentry "ankavm Hypervisor ${ankavm_VERSION} â€” Install (nomodeset)" --class ankavm {
    linux   ${VMLINUZ_PATH} boot=live components nomodeset vga=normal loglevel=3 live-config.noautologin ---
    initrd  ${INITRD_PATH}
}

menuentry "ankavm Installer â€” Debug (verbose)" --class ankavm {
    linux   ${VMLINUZ_PATH} boot=live components loglevel=7 live-config.noautologin ---
    initrd  ${INITRD_PATH}
}
GRUBEOF

log "GRUB OK"

# â”€â”€ md5sum â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
cd "$WORK_DIR/iso"
find . -type f ! -name 'md5sum.txt' | sort | xargs md5sum > md5sum.txt 2>/dev/null || true
cd - > /dev/null

# â”€â”€ ISO OluÅŸtur â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "ISO OluÅŸturma"

_FREE_KB2=$(df -k "$PWD" | awk 'NR==2{print $4}')
[ "$_FREE_KB2" -lt 3145728 ] && err "ISO iÃ§in yer yok"

_VOLID="ankavm_$(echo "$ankavm_VERSION" | tr '.' '_')"
_TMP_ISO="$WORK_DIR/output.iso"

_make_iso() {
    local OUT="$1"

    # grub-mkrescue â€” en gÃ¼venilir
    if command -v grub-mkrescue &>/dev/null; then
        log "grub-mkrescue ile ISO oluÅŸturuluyor..."
        grub-mkrescue -o "$OUT" "$WORK_DIR/iso" \
            -- -volid "$_VOLID" 2>&1 | tail -5
        [ -s "$OUT" ] && return 0
        rm -f "$OUT"
    fi

    # xorriso fallback
    if command -v xorriso &>/dev/null; then
        log "xorriso ile ISO oluÅŸturuluyor..."
        local MBR=""
        for f in \
            /usr/lib/grub/i386-pc/boot_hybrid.img \
            /usr/share/grub/boot_hybrid.img; do
            [ -f "$f" ] && MBR="$f" && break
        done
        local XARGS=(-as mkisofs -r -V "$_VOLID" -o "$OUT" -J -l -iso-level 3)
        [ -n "$MBR" ] && XARGS+=(--grub2-mbr "$MBR")
        [ -f "$WORK_DIR/iso/isolinux/isolinux.bin" ] && \
            XARGS+=(-b isolinux/isolinux.bin -c isolinux/boot.cat \
                    -no-emul-boot -boot-load-size 4 -boot-info-table)
        [ -f "$WORK_DIR/iso/boot/grub/efi.img" ] && \
            XARGS+=(-eltorito-alt-boot -e boot/grub/efi.img -no-emul-boot)
        XARGS+=("$WORK_DIR/iso")
        xorriso "${XARGS[@]}" 2>&1 | tail -5
        [ -s "$OUT" ] && return 0
        rm -f "$OUT"
    fi

    # genisoimage son Ã§are
    if command -v genisoimage &>/dev/null; then
        log "genisoimage ile ISO oluÅŸturuluyor..."
        genisoimage -r -V "$_VOLID" -cache-inodes -J -l \
            -o "$OUT" "$WORK_DIR/iso" 2>&1 | tail -3
        [ -s "$OUT" ] && return 0
        rm -f "$OUT"
    fi

    return 1
}

_make_iso "$_TMP_ISO" || err "ISO oluÅŸturma baÅŸarÄ±sÄ±z!"

# Eski ISO'larÄ± temizle
find "$REPO_ROOT" -maxdepth 1 \
    -name "ankavm-Hypervisor-*.iso" \
    ! -name "$(basename "$OUTPUT_ISO")" \
    -delete 2>/dev/null || true

mv "$_TMP_ISO" "$OUTPUT_ISO"

# isohybrid: USB'den boot iÃ§in
if command -v isohybrid &>/dev/null && [ -s "$OUTPUT_ISO" ]; then
    isohybrid --uefi "$OUTPUT_ISO" 2>/dev/null || \
    isohybrid "$OUTPUT_ISO" 2>/dev/null || true
    log "isohybrid uygulandÄ± (USB bootable)"
fi

[ ! -s "$OUTPUT_ISO" ] && err "ISO boÅŸ (0 byte)!"

sha256sum "$OUTPUT_ISO" > "${OUTPUT_ISO}.sha256"

ISO_SIZE=$(du -sh "$OUTPUT_ISO" | cut -f1)
echo ""
echo -e "${CYAN}â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—${NC}"
echo -e "${CYAN}â•‘${NC}           ${WHITE}ankavm Hypervisor ISO HazÄ±r!${NC}                       ${CYAN}â•‘${NC}"
echo -e "${CYAN}â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£${NC}"
echo -e "${CYAN}â•‘${NC}  Dosya   : ${WHITE}$(basename "$OUTPUT_ISO")${NC}"
echo -e "${CYAN}â•‘${NC}  Boyut   : ${WHITE}${ISO_SIZE}${NC}"
echo -e "${CYAN}â•‘${NC}  SHA256  : ${WHITE}$(head -c 32 "${OUTPUT_ISO}.sha256")...${NC}"
echo -e "${CYAN}â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£${NC}"
echo -e "${CYAN}â•‘${NC}  Boot akÄ±ÅŸÄ±:                                               ${CYAN}â•‘${NC}"
echo -e "${CYAN}â•‘${NC}  GRUB â†’ live-boot â†’ getty autologin root â†’ startx         ${CYAN}â•‘${NC}"
echo -e "${CYAN}â•‘${NC}  â†’ Calamares fullscreen (ankavm branding, TÃ¼rkÃ§e)          ${CYAN}â•‘${NC}"
echo -e "${CYAN}â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£${NC}"
echo -e "${CYAN}â•‘${NC}  USB: sudo dd if=$(basename "$OUTPUT_ISO") of=/dev/sdX bs=4M${NC}"
echo -e "${CYAN}â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•${NC}"

# ankavm ISO kÃ¼tÃ¼phanesine kopyala (her zaman oluÅŸtur)
ankavm_ISO_DIR="/var/lib/ankavm/isos"
mkdir -p "$ankavm_ISO_DIR"
cp -f "$OUTPUT_ISO" "$ankavm_ISO_DIR/"
cp -f "${OUTPUT_ISO}.sha256" "$ankavm_ISO_DIR/" 2>/dev/null || true
log "ISO kÃ¼tÃ¼phanesine kopyalandÄ±: $ankavm_ISO_DIR"

# â”€â”€ GitHub Release â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
step "GitHub Release"
_GH_TAG="v${ankavm_VERSION}"
_GH_TITLE="ankavm Hypervisor ${_GH_TAG}"
_GH_NOTES="## ankavm Hypervisor ${_GH_TAG}

**YayÄ±n tarihi:** $(date '+%d %B %Y')

### Kurulum
\`\`\`bash
# USB'ye yaz
sudo dd if=ankavm-Hypervisor-${ankavm_VERSION}-amd64.iso of=/dev/sdX bs=4M status=progress && sync
\`\`\`

### Boot akÄ±ÅŸÄ±
GRUB â†’ live-boot â†’ getty autologin root â†’ startx â†’ Calamares (ankavm branding, TÃ¼rkÃ§e)

### SHA256
\`\`\`
$(cat "${OUTPUT_ISO}.sha256")
\`\`\`"

if ! command -v gh &>/dev/null; then
    warn "gh CLI yok â€” GitHub release atlandÄ±"
elif ! gh auth status &>/dev/null 2>&1; then
    warn "gh auth yapÄ±lmamÄ±ÅŸ â€” GitHub release atlandÄ±"
    warn "Yetkilendirmek iÃ§in: gh auth login"
else
    # AynÄ± tag varsa sil (rebuild senaryosu)
    if gh release view "$_GH_TAG" &>/dev/null 2>&1; then
        warn "Mevcut release siliniyor: $_GH_TAG"
        gh release delete "$_GH_TAG" --yes 2>/dev/null || true
        git tag -d "$_GH_TAG" 2>/dev/null || true
        git push origin ":refs/tags/$_GH_TAG" 2>/dev/null || true
    fi

    log "GitHub release oluÅŸturuluyor: $_GH_TAG"
    _RELEASE_URL=$(gh release create "$_GH_TAG" \
        --title "$_GH_TITLE" \
        --notes "$_GH_NOTES" \
        "$OUTPUT_ISO" \
        "${OUTPUT_ISO}.sha256" \
        2>&1 | tail -1) || { warn "GitHub release baÅŸarÄ±sÄ±z â€” ISO lokal olarak mevcut"; _RELEASE_URL=""; }

    if [ -n "$_RELEASE_URL" ]; then
        echo ""
        echo -e "${CYAN}â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—${NC}"
        echo -e "${CYAN}â•‘${NC}  ${GREEN}âœ“ GitHub Release YayÄ±nlandÄ±!${NC}                              ${CYAN}â•‘${NC}"
        echo -e "${CYAN}â•‘${NC}  ${WHITE}${_RELEASE_URL}${NC}"
        echo -e "${CYAN}â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•${NC}"
    fi
fi






