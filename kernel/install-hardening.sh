#!/usr/bin/env bash
# ============================================================================
# ankavm Hypervisor â€” Kernel Security Hardening Installer
# Installs: AppArmor profile, seccomp filter, systemd drop-in,
#           eBPF/XDP loader, kernel modules (ankavm_audit + ankavm_guard)
# Usage:
#   sudo bash kernel/install-hardening.sh [--dry-run] [--no-modules] [--complain]
#   sudo bash kernel/install-hardening.sh --no-systemd   # skip systemd drop-in (safe)
#
# WARNING: systemd drop-in (ProtectSystem etc.) may cause service failure on
# some systems. Use --no-systemd to skip it. If service fails after install,
# run: sudo bash repair.sh --remove-hardening
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=0
NO_MODULES=0
NO_SYSTEMD=0   # set 1 to skip systemd drop-in (safe on systems where it causes issues)
APPARMOR_MODE="enforce"  # or "complain"
LOG=/var/log/ankavm/hardening-install.log

# â”€â”€ Parse args â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
for arg in "$@"; do
  case "$arg" in
    --dry-run)    DRY_RUN=1 ;;
    --no-modules) NO_MODULES=1 ;;
    --no-systemd) NO_SYSTEMD=1 ;;
    --complain)   APPARMOR_MODE="complain" ;;
    --help|-h)
      echo "Usage: sudo bash install-hardening.sh [--dry-run] [--no-modules] [--complain]"
      echo "  --dry-run    Show what would be done without making changes"
      echo "  --no-modules Skip kernel module compilation/install"
      echo "  --complain   Install AppArmor in complain mode (log only, no block)"
      exit 0 ;;
  esac
done

# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*" | tee -a "$LOG"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*" | tee -a "$LOG"; }
error() { echo -e "${RED}[ERROR]${NC} $*" | tee -a "$LOG"; }
run()   {
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "[DRY-RUN] $*"
  else
    eval "$@" 2>&1 | tee -a "$LOG" || true
  fi
}

# Safe cp: skip if source == destination
safe_cp() {
  local src="$1" dst="$2"
  if [[ "$(realpath "$src" 2>/dev/null)" == "$(realpath "$dst" 2>/dev/null)" ]]; then
    info "  (skip copy â€” source == destination: $dst)"
    return 0
  fi
  run "cp '$src' '$dst'"
}

# â”€â”€ Root check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if [[ $EUID -ne 0 ]]; then
  error "Root required. Run: sudo bash $0"
  exit 1
fi

mkdir -p /var/log/ankavm
info "ankavm Kernel Hardening Installer â€” $(date)"
info "Mode: DRY_RUN=$DRY_RUN NO_MODULES=$NO_MODULES APPARMOR=$APPARMOR_MODE"

# â”€â”€ 1. AppArmor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
info "--- [1/5] AppArmor Profile ---"

# Ensure apparmor + apparmor-utils are installed
if ! command -v apparmor_parser &>/dev/null; then
  info "Installing apparmor..."
  run "apt-get install -y apparmor apparmor-utils apparmor-profiles"
elif ! command -v aa-enforce &>/dev/null; then
  info "Installing apparmor-utils (aa-enforce/aa-complain)..."
  run "apt-get install -y apparmor-utils"
fi

APPARMOR_PROFILE="/etc/apparmor.d/opt.ankavm.backend.app"
safe_cp "$SCRIPT_DIR/apparmor/ankavm" "$APPARMOR_PROFILE"

# Load profile first (always needed)
run "apparmor_parser -r '$APPARMOR_PROFILE' || apparmor_parser -a '$APPARMOR_PROFILE'"

if [[ $APPARMOR_MODE == "complain" ]]; then
  if command -v aa-complain &>/dev/null; then
    run "aa-complain '$APPARMOR_PROFILE'"
  else
    # fallback: write flags=complain into profile and reload
    run "sed -i 's/flags=(attach_disconnected,mediate_deleted)/flags=(attach_disconnected,mediate_deleted,complain)/' '$APPARMOR_PROFILE'"
    run "apparmor_parser -r '$APPARMOR_PROFILE'"
  fi
  info "AppArmor installed in COMPLAIN mode (logging only, no blocking)"
  info "Monitor: sudo journalctl -f | grep apparmor"
else
  if command -v aa-enforce &>/dev/null; then
    run "aa-enforce '$APPARMOR_PROFILE'"
  fi
  info "AppArmor profile loaded + enforced: $APPARMOR_PROFILE"
fi

# â”€â”€ 2. seccomp filter â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
info "--- [2/5] seccomp Filter ---"
SECCOMP_DEST="/etc/ankavm/seccomp.json"
safe_cp "$SCRIPT_DIR/seccomp/ankavm-seccomp.json" "$SECCOMP_DEST"
run "chmod 640 '$SECCOMP_DEST'"
info "seccomp profile installed: $SECCOMP_DEST"
info "Applied via systemd SystemCallFilter= in drop-in"

# â”€â”€ 3. systemd drop-in (cgroups + capabilities + seccomp) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
info "--- [3/5] systemd Hardening Drop-in ---"
if [[ $NO_SYSTEMD -eq 1 ]]; then
  warn "systemd drop-in atlandÄ± (--no-systemd). Servis dokunulmadÄ±."
  info "drop-in manuel eklemek: cp '$SCRIPT_DIR/systemd/ankavm-hardening.conf' /etc/systemd/system/ankavm.service.d/"
else
DROPIN_DIR="/etc/systemd/system/ankavm.service.d"
DROPIN_FILE="$DROPIN_DIR/hardening.conf"
DROPIN_BACKUP="$DROPIN_DIR/hardening.conf.bak"

run "mkdir -p '$DROPIN_DIR'"

# Backup existing drop-in for rollback
[[ -f "$DROPIN_FILE" ]] && run "cp '$DROPIN_FILE' '$DROPIN_BACKUP'"

safe_cp "$SCRIPT_DIR/systemd/ankavm-hardening.conf" "$DROPIN_FILE"
run "systemctl daemon-reload"
info "systemd drop-in installed: $DROPIN_FILE"

# â”€â”€ Auto-test: restart service and verify it stays up â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if [[ $DRY_RUN -eq 0 ]]; then
  info "Testing ankavm.service with new hardening (wait 8s)..."
  systemctl restart ankavm 2>&1 | tee -a "$LOG" || true
  sleep 8   # give ExecStartPre time to complete

  if systemctl is-active --quiet ankavm; then
    info "ankavm.service started successfully with hardening âœ“"
  else
    # Capture exact failure reason
    FAIL_CODE=$(systemctl show ankavm --property=Result --value 2>/dev/null)
    FAIL_LOG=$(journalctl -u ankavm -n 15 --no-pager 2>/dev/null || true)
    error "ankavm.service FAILED (Result: $FAIL_CODE)"
    error "$FAIL_LOG"

    # Specific diagnosis
    if echo "$FAIL_LOG" | grep -qE "NAMESPACE|226"; then
      error "Cause: 226/NAMESPACE â€” mount namespacing failed"
    elif echo "$FAIL_LOG" | grep -qE "status=1/FAILURE|ExecStartPre.*failed|control process exited"; then
      error "Cause: ExecStartPre command failed (likely ProtectSystem blocking /etc write)"
    elif echo "$FAIL_LOG" | grep -qE "Permission denied"; then
      error "Cause: Permission denied â€” filesystem protection too strict"
    fi

    warn "Rolling back hardening drop-in..."
    if [[ -f "$DROPIN_BACKUP" ]]; then
      cp "$DROPIN_BACKUP" "$DROPIN_FILE"
      info "Restored previous drop-in from backup"
    else
      rm -f "$DROPIN_FILE"
      info "Drop-in removed (was first install â€” no backup)"
    fi
    systemctl daemon-reload
    systemctl restart ankavm
    sleep 5
    if systemctl is-active --quiet ankavm; then
      info "Service restored after rollback âœ“"
      warn "Hardening NOT applied â€” fix kernel/systemd/ankavm-hardening.conf and re-run"
    else
      error "Service STILL failing after rollback!"
      error "Run: sudo bash repair.sh"
      error "Or:  sudo bash repair.sh --remove-hardening"
    fi
    # Don't abort â€” continue with AppArmor, eBPF steps
  fi
fi  # end DRY_RUN check
fi  # end NO_SYSTEMD check

# â”€â”€ 4. eBPF/XDP network filter â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
info "--- [4/5] eBPF/XDP Network Filter ---"
EBPF_DIR="/opt/ankavm/kernel/ebpf"
run "mkdir -p '$EBPF_DIR'"
safe_cp "$SCRIPT_DIR/ebpf/xdp_filter.c"  "$EBPF_DIR/xdp_filter.c"
safe_cp "$SCRIPT_DIR/ebpf/xdp_loader.py" "$EBPF_DIR/xdp_loader.py"
run "chmod +x '$EBPF_DIR/xdp_loader.py'"

# Install clang + BPF deps (gcc-multilib provides gnu/stubs-32.h needed by clang BPF)
if ! command -v clang &>/dev/null; then
  info "clang not found â€” installing..."
  run "apt-get install -y clang llvm linux-headers-$(uname -r) libbpf-dev gcc-multilib"
else
  # clang present but stubs-32.h may be missing
  if ! find /usr/include -name "stubs-32.h" 2>/dev/null | grep -q .; then
    info "gnu/stubs-32.h missing â€” installing gcc-multilib..."
    run "apt-get install -y gcc-multilib libbpf-dev"
  fi
fi

# Compile XDP object
if command -v clang &>/dev/null; then
  info "Compiling XDP filter..."
  ARCH="$(uname -m)"
  ARCH_INCLUDE="/usr/include/${ARCH}-linux-gnu"
  [[ -d "$ARCH_INCLUDE" ]] || ARCH_INCLUDE="/usr/include"

  # BPF compile flags: suppress userspace compat warnings, no 32-bit stubs
  BPF_CFLAGS="-O2 -target bpf -D__TARGET_ARCH_x86 -D__x86_64__"
  BPF_CFLAGS="$BPF_CFLAGS -I$ARCH_INCLUDE -I/usr/include"
  BPF_CFLAGS="$BPF_CFLAGS -Wno-unused-value -Wno-pointer-sign -Wno-compare-distinct-pointer-types"
  # Suppress gnu/stubs-32.h pull-in from stubs.h
  BPF_CFLAGS="$BPF_CFLAGS -D__GLIBC_HAVE_LONG_LONG=1"

  if clang $BPF_CFLAGS \
      -c "$EBPF_DIR/xdp_filter.c" \
      -o "$EBPF_DIR/xdp_filter.o" 2>&1 | tee -a "$LOG"; then
    info "XDP filter compiled: $EBPF_DIR/xdp_filter.o"
    info "Attach to VM taps: sudo python3 $EBPF_DIR/xdp_loader.py attach-all"
  else
    warn "XDP compile failed â€” trying fallback (install gcc-multilib)..."
    apt-get install -y -qq gcc-multilib 2>/dev/null || true
    clang $BPF_CFLAGS \
        -c "$EBPF_DIR/xdp_filter.c" \
        -o "$EBPF_DIR/xdp_filter.o" 2>&1 | tee -a "$LOG" && \
      info "XDP filter compiled (fallback) âœ“" || \
      warn "XDP compile still failed â€” eBPF filter not active (non-fatal)"
  fi
fi

# systemd service for auto-attach
if [[ $DRY_RUN -eq 0 ]]; then
  cat > /etc/systemd/system/ankavm-xdp.service << 'SVCEOF'
[Unit]
Description=ankavm XDP Network Filter
After=ankavm.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 /opt/ankavm/kernel/ebpf/xdp_loader.py attach-all
ExecStop=/usr/bin/python3 /opt/ankavm/kernel/ebpf/xdp_loader.py detach-all
Restart=no

[Install]
WantedBy=multi-user.target
SVCEOF
fi
run "systemctl daemon-reload"
info "ankavm-xdp.service installed"

# â”€â”€ 5. Kernel Modules â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
info "--- [5/5] Kernel Modules ---"
if [[ $NO_MODULES -eq 1 ]]; then
  warn "Skipping kernel modules (--no-modules passed)"
else
  KVER="$(uname -r)"
  KDIR="/lib/modules/${KVER}/build"
  EXTRA_DIR="/lib/modules/${KVER}/extra"

  # Ensure kernel headers
  if [[ ! -d "$KDIR" ]]; then
    info "Installing kernel headers..."
    run "apt-get install -y linux-headers-${KVER} build-essential"
  fi

  # Create extra/ dir if missing
  run "mkdir -p '$EXTRA_DIR'"

  _install_module() {
    local name="$1"
    local dir="$SCRIPT_DIR/modules/$name"
    [[ -d "$dir" ]] || { warn "$dir not found, skip"; return; }

    info "Building ${name}.ko..."
    run "make -C '$dir' KDIR='$KDIR' clean 2>/dev/null || true"
    run "make -C '$dir' KDIR='$KDIR'"

    if [[ -f "$dir/${name}.ko" ]]; then
      run "install -m 644 '$dir/${name}.ko' '${EXTRA_DIR}/'"
      run "depmod -a"
      run "modprobe '$name' || true"
      # Persist across reboots
      grep -qx "$name" /etc/modules-load.d/ankavm.conf 2>/dev/null || \
        echo "$name" >> /etc/modules-load.d/ankavm.conf
      if lsmod | grep -q "^${name}"; then
        info "${name}.ko installed and LOADED âœ“"
      else
        warn "${name}.ko installed but modprobe failed â€” check: dmesg | grep ankavm"
      fi
    else
      warn "${name}.ko build failed â€” check: CONFIG_KPROBES=y in kernel config"
    fi
  }

  _install_module "ankavm_audit"
  _install_module "ankavm_guard"
fi

# â”€â”€ Final status check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
info "--- Status Check ---"
if command -v aa-status &>/dev/null; then
  AA_STATUS=$(aa-status 2>/dev/null | grep -E "profiles|enforce|complain" | head -3 || echo "aa-status unavailable")
  info "AppArmor: $AA_STATUS"
fi

LOADED_MODS=""
for m in ankavm_audit ankavm_guard; do
  lsmod | grep -q "^$m" && LOADED_MODS="$LOADED_MODS $m" || true
done
[[ -n "$LOADED_MODS" ]] && info "Kernel modules loaded:$LOADED_MODS" || info "Kernel modules: not loaded"

# â”€â”€ Summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
echo ""
info "â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•"
info "ankavm Kernel Hardening â€” Installation Complete"
info "â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•"
echo ""
echo "  AppArmor:      /etc/apparmor.d/opt.ankavm.backend.app  ($APPARMOR_MODE)"
echo "  seccomp:       /etc/ankavm/seccomp.json"
echo "  systemd:       /etc/systemd/system/ankavm.service.d/hardening.conf"
echo "  eBPF/XDP:      /opt/ankavm/kernel/ebpf/xdp_filter.o"
echo "  ankavm_audit:  $(lsmod | grep -q '^ankavm_audit' && echo 'LOADED' || echo 'not loaded')"
echo "  ankavm_guard:  $(lsmod | grep -q '^ankavm_guard' && echo 'LOADED' || echo 'not loaded')"
echo ""
echo "  Next steps:"
echo "    1. sudo systemctl restart ankavm"
echo "    2. sudo systemctl enable --now ankavm-xdp"
echo "    3. sudo aa-status"
echo "    4. sudo journalctl -u ankavm --since '1 min ago'"
echo "    5. sudo cat /dev/ankavm_audit   (if module loaded)"
echo ""
if [[ $APPARMOR_MODE == "complain" ]]; then
  warn "AppArmor is in COMPLAIN mode. After testing run enforce:"
  warn "  sudo apparmor_parser -r /etc/apparmor.d/opt.ankavm.backend.app"
  warn "  sudo aa-enforce /etc/apparmor.d/opt.ankavm.backend.app  (if aa-utils installed)"
fi






