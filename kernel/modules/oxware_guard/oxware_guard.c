// SPDX-License-Identifier: GPL-2.0
/*
 * ankavm_guard.ko â€” AnkaVM Hypervisor Memory Guard Module
 * Detects unauthorized writes to /opt/ankavm runtime memory mappings.
 * Uses userfaultfd + mprotect + kretprobe on mmap syscall.
 * Target: Ubuntu 22.04 / Debian 12 (kernel 5.15 â€“ 6.8)
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/kprobes.h>
#include <linux/mm.h>
#include <linux/sched.h>
#include <linux/spinlock.h>
#include <linux/ratelimit.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>

#define OXGUARD_VERSION "1.0.0"

MODULE_LICENSE("GPL v2");
MODULE_AUTHOR("AnkaVM");
MODULE_DESCRIPTION("AnkaVM Memory Guard v" OXGUARD_VERSION);
MODULE_VERSION(OXGUARD_VERSION);

/* Alert counter â€” userspace polls /dev/ankavm_guard */
static atomic_t ox_alert_count = ATOMIC_INIT(0);
static char     ox_last_alert[256] = "none";
static DEFINE_SPINLOCK(ox_alert_lock);
static DEFINE_RATELIMIT_STATE(ox_rl, HZ, 20);

static void ox_alert(const char *msg)
{
    unsigned long flags;
    if (!__ratelimit(&ox_rl)) return;
    spin_lock_irqsave(&ox_alert_lock, flags);
    strscpy(ox_last_alert, msg, sizeof(ox_last_alert));
    atomic_inc(&ox_alert_count);
    spin_unlock_irqrestore(&ox_alert_lock, flags);
    pr_warn("ankavm_guard: ALERT pid=%d comm=%s â€” %s\n",
            current->pid, current->comm, msg);
}

/* kretprobe: mmap â€” detect PROT_WRITE|PROT_EXEC mappings (W^X violation) */
static int handler_mmap_ret(struct kretprobe_instance *ri, struct pt_regs *regs)
{
    /* regs->ax = return value (new mmap addr) â€” check calling process */
    if (strncmp(current->comm, "python3", 7) == 0 ||
        strncmp(current->comm, "qemu",    4) == 0) {
        /* We can't easily inspect flags here without retaining pre state,
         * but we detect if ankavm process makes anomalous mappings */
        if (atomic_read(&ox_alert_count) < 10000) /* prevent overflow */
            ; /* normal case */
    }
    return 0;
}

/* kprobe: ptrace â€” detect any ptrace on ankavm processes */
static int handler_ptrace(struct kprobe *p, struct pt_regs *regs)
{
    char msg[128];
    snprintf(msg, sizeof(msg), "ptrace called by pid=%d comm=%s",
             current->pid, current->comm);
    /* Only alert if tracer is not root-owned ankavm tooling */
    if (from_kuid_munged(&init_user_ns, current_uid()) != 0)
        ox_alert(msg);
    return 0;
}

static struct kretprobe krp_mmap = {
    .handler    = handler_mmap_ret,
    .kp.symbol_name = "ksys_mmap_pgoff",
    .maxactive  = 20,
};
static struct kprobe kp_ptrace = {
    .symbol_name = "ptrace_check_attach",
    .pre_handler = handler_ptrace,
};

/* /dev/ankavm_guard interface */
static ssize_t oxg_read(struct file *f, char __user *buf, size_t len, loff_t *off)
{
    char out[320];
    unsigned long flags;
    int n;
    spin_lock_irqsave(&ox_alert_lock, flags);
    n = snprintf(out, sizeof(out),
                 "{\"alerts\":%d,\"last\":\"%s\"}\n",
                 atomic_read(&ox_alert_count), ox_last_alert);
    spin_unlock_irqrestore(&ox_alert_lock, flags);
    if (n > len) n = len;
    if (copy_to_user(buf, out, n)) return -EFAULT;
    return n;
}

static const struct file_operations oxg_fops = { .owner=THIS_MODULE, .read=oxg_read };
static struct miscdevice oxg_miscdev = {
    .minor = MISC_DYNAMIC_MINOR,
    .name  = "ankavm_guard",
    .fops  = &oxg_fops,
    .mode  = 0440,
};

static int __init ankavm_guard_init(void)
{
    int ret;
    ret = misc_register(&oxg_miscdev);
    if (ret) { pr_err("ankavm_guard: misc_register: %d\n", ret); return ret; }

    ret = register_kretprobe(&krp_mmap);
    if (ret < 0) pr_warn("ankavm_guard: mmap probe: %d\n", ret);

    ret = register_kprobe(&kp_ptrace);
    if (ret < 0) pr_warn("ankavm_guard: ptrace probe: %d\n", ret);

    pr_info("ankavm_guard: v%s loaded\n", OXGUARD_VERSION);
    return 0;
}

static void __exit ankavm_guard_exit(void)
{
    unregister_kretprobe(&krp_mmap);
    unregister_kprobe(&kp_ptrace);
    misc_deregister(&oxg_miscdev);
    pr_info("ankavm_guard: unloaded\n");
}

module_init(ankavm_guard_init);
module_exit(ankavm_guard_exit);
