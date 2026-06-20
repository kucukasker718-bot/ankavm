#!/usr/bin/env bash
# ============================================================================
# ankavm OS Rebrander
# Converts Ubuntu/Debian identity into "ankavm Hypervisor" identity.
# Idempotent — safe to re-run. Backs up originals to /etc/ankavm/.os-backup/
# Usage: sudo bash scripts/rebrand-os.sh [--restore]
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colors / logging (mirrors install.sh style)
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
    C_RESET="\033[0m"
    C_RED="\033[1;31m"
    C_GREEN="\033[1;32m"
    C_YELLOW="\033[1;33m"
    C_BLUE="\033[1;34m"
    C_CYAN="\033[1;36m"
    C_BOLD="\033[1m"
else
    C_RESET=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_CYAN=""; C_BOLD=""
fi

log()  { echo -e "${C_GREEN}[ OK ]${C_RESET} $*"; }
info() { echo -e "${C_CYAN}[INFO]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[WARN]${C_RESET} $*"; }
err()  { echo -e "${C_RED}[ERR ]${C_RESET} $*" >&2; }
step() { echo -e "\n${C_BOLD}${C_BLUE}==>${C_RESET} ${C_BOLD}$*${C_RESET}"; }

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    err "Must be run as root (use sudo)."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BACKUP_DIR="/etc/ankavm/.os-backup"
BRAND_NAME="ankavm Hypervisor"
BRAND_ID="ankavm"
BRAND_ID_LIKE="debian"
BRAND_HOME_URL="https://github.com/ShinnAsukha/ankavm-hypervisor"
BRAND_SUPPORT_URL="https://github.com/ShinnAsukha/ankavm-hypervisor/issues"
BRAND_BUG_URL="https://github.com/ShinnAsukha/ankavm-hypervisor/issues"

# ---------------------------------------------------------------------------
# Detect ankavm version
# ---------------------------------------------------------------------------
detect_version() {
    local v=""
    if [ -f "/opt/ankavm/ankavm/backend/app.py" ]; then
        v="$(grep -m1 -oE 'v[0-9]+\.[0-9]+\.[0-9]+' /opt/ankavm/ankavm/backend/app.py 2>/dev/null | head -n1 | sed 's/^v//')"
    fi
    if [ -z "$v" ] && [ -f "$REPO_ROOT/install.sh" ]; then
        v="$(grep -m1 -oE 'ankavm_VERSION=["\x27]?[0-9]+\.[0-9]+\.[0-9]+' "$REPO_ROOT/install.sh" 2>/dev/null | head -n1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"
    fi
    if [ -z "$v" ]; then
        v="2.7.0"
    fi
    echo "$v"
}

ankavm_VERSION="$(detect_version)"
info "ankavm version detected: ${C_BOLD}${ankavm_VERSION}${C_RESET}"

# ---------------------------------------------------------------------------
# Backup helpers
# ---------------------------------------------------------------------------
ensure_backup_dir() {
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
}

backup_file() {
    local src="$1"
    [ -e "$src" ] || return 0
    ensure_backup_dir
    local base
    base="$(basename "$src")"
    local dst="$BACKUP_DIR/${base}.orig"
    if [ ! -e "$dst" ]; then
        cp -a "$src" "$dst"
        info "Backed up $src -> $dst"
    fi
}

restore_file() {
    local target="$1"
    local base
    base="$(basename "$target")"
    local src="$BACKUP_DIR/${base}.orig"
    if [ -e "$src" ]; then
        cp -a "$src" "$target"
        log "Restored $target"
    else
        warn "No backup for $target, skipping."
    fi
}

# ---------------------------------------------------------------------------
# Already-rebranded check
# ---------------------------------------------------------------------------
is_rebranded() {
    [ -f /etc/os-release ] && grep -q "ankavm" /etc/os-release
}

# ---------------------------------------------------------------------------
# Step 1: /etc/os-release
# ---------------------------------------------------------------------------
rebrand_os_release() {
    step "Rewriting /etc/os-release"
    backup_file /etc/os-release

    # If /etc/os-release is a symlink to /usr/lib/os-release, replace symlink
    if [ -L /etc/os-release ]; then
        info "/etc/os-release is a symlink — removing and writing real file."
        rm -f /etc/os-release
    fi

    cat > /etc/os-release <<EOF
NAME="${BRAND_NAME}"
VERSION="${ankavm_VERSION} (ankavm)"
ID=${BRAND_ID}
ID_LIKE=${BRAND_ID_LIKE}
PRETTY_NAME="${BRAND_NAME} ${ankavm_VERSION}"
VERSION_ID="${ankavm_VERSION}"
HOME_URL="${BRAND_HOME_URL}"
SUPPORT_URL="${BRAND_SUPPORT_URL}"
BUG_REPORT_URL="${BRAND_BUG_URL}"
ankavm_BUILD="${ankavm_VERSION}"
EOF
    chmod 644 /etc/os-release
    log "/etc/os-release rewritten."

    # Mirror to /usr/lib/os-release if it exists and isn't already ours
    if [ -f /usr/lib/os-release ] && ! grep -q "ankavm" /usr/lib/os-release; then
        backup_file /usr/lib/os-release
        cp -a /etc/os-release /usr/lib/os-release
        log "/usr/lib/os-release synced."
    fi
}

# ---------------------------------------------------------------------------
# Step 2: /etc/lsb-release
# ---------------------------------------------------------------------------
rebrand_lsb_release() {
    step "Rewriting /etc/lsb-release"
    backup_file /etc/lsb-release
    cat > /etc/lsb-release <<EOF
DISTRIB_ID=ankavm
DISTRIB_RELEASE=${ankavm_VERSION}
DISTRIB_CODENAME=hypervisor
DISTRIB_DESCRIPTION="${BRAND_NAME} ${ankavm_VERSION}"
EOF
    chmod 644 /etc/lsb-release
    log "/etc/lsb-release rewritten."
}

# ---------------------------------------------------------------------------
# Step 3: /etc/issue + /etc/issue.net
# ---------------------------------------------------------------------------
rebrand_issue() {
    step "Installing ankavm login banner (/etc/issue, /etc/issue.net)"
    backup_file /etc/issue
    backup_file /etc/issue.net

    local src="$SCRIPT_DIR/ankavm-issue"
    if [ ! -f "$src" ]; then
        warn "Template $src not found — writing minimal banner."
        cat > /etc/issue <<EOF
${BRAND_NAME} ${ankavm_VERSION}
Kernel \\r on an \\m

EOF
    else
        # Substitute version placeholder if needed, then install
        sed "s/2\.6\.1/${ankavm_VERSION}/g" "$src" > /etc/issue
    fi
    chmod 644 /etc/issue
    cp -a /etc/issue /etc/issue.net
    log "Login banners installed."
}

# ---------------------------------------------------------------------------
# Step 4: /etc/motd
# ---------------------------------------------------------------------------
clear_motd() {
    step "Clearing /etc/motd (managed by install.sh dynamic MOTD)"
    backup_file /etc/motd
    : > /etc/motd
    chmod 644 /etc/motd
    log "/etc/motd cleared."
}

# ---------------------------------------------------------------------------
# Step 5: hostname (only if default + opt-in)
# ---------------------------------------------------------------------------
rebrand_hostname() {
    step "Hostname check"
    if [ "${ankavm_REBRAND_HOSTNAME:-0}" != "1" ]; then
        info "ankavm_REBRAND_HOSTNAME!=1, skipping hostname change."
        return 0
    fi
    local current
    current="$(cat /etc/hostname 2>/dev/null | tr -d '[:space:]')"
    case "$current" in
        localhost|ubuntu|debian|"")
            backup_file /etc/hostname
            echo "ankavm" > /etc/hostname
            hostnamectl set-hostname "ankavm" 2>/dev/null || true
            log "Hostname set to 'ankavm' (was '$current')."
            ;;
        *)
            info "Hostname '$current' is custom — leaving untouched."
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Step 7: GRUB
# ---------------------------------------------------------------------------
rebrand_grub() {
    step "Updating GRUB distributor"
    if [ ! -f /etc/default/grub ]; then
        warn "/etc/default/grub not present, skipping GRUB rebrand."
        return 0
    fi
    backup_file /etc/default/grub

    if grep -q '^GRUB_DISTRIBUTOR=' /etc/default/grub; then
        sed -i 's|^GRUB_DISTRIBUTOR=.*|GRUB_DISTRIBUTOR="ankavm"|' /etc/default/grub
    else
        echo 'GRUB_DISTRIBUTOR="ankavm"' >> /etc/default/grub
    fi
    log "GRUB_DISTRIBUTOR=ankavm set."

    if command -v update-grub >/dev/null 2>&1; then
        info "Running update-grub..."
        update-grub >/dev/null 2>&1 && log "GRUB regenerated." || warn "update-grub failed (non-fatal)."
    elif command -v grub-mkconfig >/dev/null 2>&1; then
        info "Running grub-mkconfig..."
        grub-mkconfig -o /boot/grub/grub.cfg >/dev/null 2>&1 \
            && log "GRUB regenerated." || warn "grub-mkconfig failed (non-fatal)."
    else
        warn "No GRUB tooling found — skipping regeneration."
    fi
}

# ---------------------------------------------------------------------------
# Step 9: Plymouth theme (if assets present)
# ---------------------------------------------------------------------------
install_plymouth_theme() {
    step "Plymouth boot splash"
    local src="/opt/ankavm/assets/plymouth"
    if [ ! -d "$src" ]; then
        info "No Plymouth assets at $src, skipping."
        return 0
    fi
    if ! command -v plymouth-set-default-theme >/dev/null 2>&1; then
        warn "plymouth not installed, skipping theme install."
        return 0
    fi
    local dst="/usr/share/plymouth/themes/ankavm"
    mkdir -p "$dst"
    cp -a "$src/." "$dst/"
    plymouth-set-default-theme -R ankavm >/dev/null 2>&1 \
        && log "Plymouth theme 'ankavm' set." \
        || warn "Could not set Plymouth theme."
}

# ---------------------------------------------------------------------------
# Step 10: /etc/update-motd.d/00-header
# ---------------------------------------------------------------------------
ensure_motd_header() {
    step "Ensuring /etc/update-motd.d/00-header is ankavm-branded"
    local dir="/etc/update-motd.d"
    [ -d "$dir" ] || { info "$dir not present, skipping."; return 0; }
    local hdr="$dir/00-header"

    if [ -f "$hdr" ] && grep -q "ankavm" "$hdr"; then
        info "00-header already ankavm-branded."
        return 0
    fi
    backup_file "$hdr"
    cat > "$hdr" <<EOF
#!/bin/sh
printf "\n"
printf "  ankavm Hypervisor ${ankavm_VERSION}  |  \$(uname -r)\n"
printf "  Web UI:  https://\$(hostname -I | awk '{print \$1}'):8006\n"
printf "\n"
EOF
    chmod 755 "$hdr"
    log "00-header installed."
}

# ---------------------------------------------------------------------------
# Step 11: /usr/local/bin/ankavm-version
# ---------------------------------------------------------------------------
install_version_helper() {
    step "Installing /usr/local/bin/ankavm-version"
    cat > /usr/local/bin/ankavm-version <<EOF
#!/bin/sh
# ankavm version helper — prints full identity string.
. /etc/os-release 2>/dev/null || true
KERNEL="\$(uname -r)"
ARCH="\$(uname -m)"
HOST="\$(hostname)"
cat <<INFO
ankavm Hypervisor ${ankavm_VERSION}
  Kernel:    \$KERNEL (\$ARCH)
  Hostname:  \$HOST
  Build ID:  \${ankavm_BUILD:-${ankavm_VERSION}}
  Web UI:    https://\$(hostname -I 2>/dev/null | awk '{print \$1}'):8006
INFO
EOF
    chmod 755 /usr/local/bin/ankavm-version
    log "/usr/local/bin/ankavm-version installed."
}

# ---------------------------------------------------------------------------
# Step 12: /etc/profile.d/ankavm.sh
# ---------------------------------------------------------------------------
install_profile_d() {
    step "Installing /etc/profile.d/ankavm.sh"
    local src="$SCRIPT_DIR/ankavm.sh"
    local dst="/etc/profile.d/ankavm.sh"
    if [ -f "$src" ]; then
        install -m 0644 "$src" "$dst"
        log "Installed profile.d snippet from $src."
    else
        warn "Template $src not found — writing inline minimal."
        cat > "$dst" <<'EOF'
export ankavm_HYPERVISOR=1
EOF
        chmod 644 "$dst"
    fi
}

# ---------------------------------------------------------------------------
# Step 13: /usr/local/bin/uname-wrapper (opt-in)
# ---------------------------------------------------------------------------
install_uname_wrapper() {
    step "Optional uname wrapper"
    if [ "${ankavm_BRAND_UNAME:-0}" != "1" ]; then
        info "ankavm_BRAND_UNAME!=1, skipping uname wrapper."
        return 0
    fi
    cat > /usr/local/bin/uname-wrapper <<EOF
#!/bin/sh
# ankavm-branded uname wrapper.
REAL="\$(/bin/uname "\$@")"
case " \$* " in
    *" -a "*|*" --all "*)
        echo "\${REAL} ankavm-Hypervisor/${ankavm_VERSION}"
        ;;
    *)
        echo "\$REAL"
        ;;
esac
EOF
    chmod 755 /usr/local/bin/uname-wrapper
    log "/usr/local/bin/uname-wrapper installed (opt-in; not aliased globally)."
}

# ---------------------------------------------------------------------------
# Restore mode
# ---------------------------------------------------------------------------
do_restore() {
    step "Restoring original OS identity from $BACKUP_DIR"
    if [ ! -d "$BACKUP_DIR" ]; then
        err "No backup directory at $BACKUP_DIR — cannot restore."
        exit 1
    fi
    restore_file /etc/os-release
    restore_file /usr/lib/os-release
    restore_file /etc/lsb-release
    restore_file /etc/issue
    restore_file /etc/issue.net
    restore_file /etc/motd
    restore_file /etc/hostname
    restore_file /etc/default/grub
    restore_file /etc/update-motd.d/00-header

    rm -f /etc/profile.d/ankavm.sh
    rm -f /usr/local/bin/ankavm-version
    rm -f /usr/local/bin/uname-wrapper

    if command -v update-grub >/dev/null 2>&1; then
        update-grub >/dev/null 2>&1 || true
    fi
    log "Restore complete."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    if [ "${1:-}" = "--restore" ]; then
        do_restore
        exit 0
    fi

    ensure_backup_dir

    if is_rebranded; then
        info "System already shows ankavm identity — re-running idempotently."
    fi

    rebrand_os_release
    rebrand_lsb_release
    rebrand_issue
    clear_motd
    rebrand_hostname
    rebrand_grub
    install_plymouth_theme
    ensure_motd_header
    install_version_helper
    install_profile_d
    install_uname_wrapper

    echo
    log "${C_BOLD}ankavm OS rebrand complete.${C_RESET}"
    info "Run 'ankavm-version' to verify."
    info "To revert: sudo bash $0 --restore"
}

main "$@"






