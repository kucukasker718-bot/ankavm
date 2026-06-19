# ANKAVM Hypervisor environment
export ANKAVM_HYPERVISOR=1
export ANKAVM_VERSION="2.7.0"

# Only modify PS1 for interactive shells
if [ -n "$PS1" ] && [ "$TERM" != "dumb" ]; then
    # Subtle ANKAVM prefix on root shell prompt
    if [ "$EUID" -eq 0 ]; then
        export PS1='\[\033[1;31m\][AV]\[\033[0m\] \u@\h:\w# '
    fi
fi

# Aliases
alias av='ankavm-version'
alias ankavm-status='systemctl status ankavm --no-pager'
alias ankavm-logs='journalctl -u ankavm -f'
alias ankavm-repair='sudo bash /opt/ankavm/repair.sh'






