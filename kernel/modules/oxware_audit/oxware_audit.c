// SPDX-License-Identifier: GPL-2.0
/*
 * ankavm_audit.ko â€” AnkaVM Hypervisor Audit Kernel Module
 * Hooks KVM/libvirt lifecycle events via kprobes and writes to
 * Linux audit subsystem + kernel ring buffer.
 * Target: Ubuntu 22.04 / Debian 12 (kernel 5.15 â€“ 6.8)
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/kprobes.h>
#include <linux/audit.h>
#include <linux/sched.h>
#include <linux/uaccess.h>
#include <linux/fs.h>
#include <linux/miscdevice.h>
#include <linux/mutex.h>
#include <linux/spinlock.h>
#include <linux/ratelimit.h>
#include <linux/version.h>

#define OXWARE_AUDIT_VERSION "1.0.0"
#define OXWARE_AUDIT_MAGIC   0x4F585741  /* OXWA */
#define OXWARE_RING_SIZE     1024
#define OXWARE_MAX_MSG       256

MODULE_LICENSE("GPL v2");
MODULE_AUTHOR("AnkaVM");
MODULE_DESCRIPTION("AnkaVM Hypervisor Audit Module v" OXWARE_AUDIT_VERSION);
MODULE_VERSION(OXWARE_AUDIT_VERSION);

/* â”€â”€ Event ring buffer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
struct ankavm_event {
    u64  timestamp;      /* ktime_get_real_ns() */
    u32  pid;
    u32  uid;
    u32  event_type;     /* OXEVENT_* */
    char comm[TASK_COMM_LEN];
    char msg[OXWARE_MAX_MSG];
};

#define OXEVENT_VM_CREATE   1
#define OXEVENT_VM_DESTROY  2
#define OXEVENT_VM_START    3
#define OXEVENT_VM_STOP     4
#define OXEVENT_MEM_MAP     5
#define OXEVENT_IOCTL       6
#define OXEVENT_PTRACE      7
#define OXEVENT_EXEC        8

static struct ankavm_event  ox_ring[OXWARE_RING_SIZE];
static atomic_t             ox_head = ATOMIC_INIT(0);
static atomic_t             ox_count = ATOMIC_INIT(0);
static DEFINE_SPINLOCK(ox_ring_lock);
static DEFINE_RATELIMIT_STATE(ox_rl, HZ, 100); /* 100 events/sec max */

static void ox_emit(u32 type, const char *msg)
{
    unsigned long flags;
    int idx;
    struct ankavm_event *ev;

    if (!__ratelimit(&ox_rl))
        return;

    spin_lock_irqsave(&ox_ring_lock, flags);
    idx = atomic_fetch_add(1, &ox_head) % OXWARE_RING_SIZE;
    ev = &ox_ring[idx];
    ev->timestamp  = ktime_get_real_ns();
    ev->pid        = current->pid;
    ev->uid        = from_kuid_munged(&init_user_ns, current_uid());
    ev->event_type = type;
    get_task_comm(ev->comm, current);
    strscpy(ev->msg, msg ? msg : "", OXWARE_MAX_MSG);
    atomic_inc(&ox_count);
    spin_unlock_irqrestore(&ox_ring_lock, flags);

    /* Also log to kernel audit trail */
    audit_log(audit_context(), GFP_ATOMIC, AUDIT_KERN_MODULE,
              "ankavm: type=%u pid=%d comm=%s msg=%s",
              type, current->pid, ev->comm, ev->msg);
}

/* â”€â”€ kprobe: kvm_vm_ioctl (VM lifecycle) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
static int handler_kvm_vm_ioctl(struct kprobe *p, struct pt_regs *regs)
{
#ifdef CONFIG_X86_64
    unsigned long cmd = regs->si;
#elif defined(CONFIG_ARM64)
    unsigned long cmd = regs->regs[1];
#else
    unsigned long cmd = 0;
#endif
    /* KVM_CREATE_VCPU=0x4141, KVM_RUN=0x0000ae80, KVM_SET_USER_MEMORY_REGION=0x4020ae46 */
    switch (cmd & 0xFFFF) {
    case 0xAE41: ox_emit(OXEVENT_VM_CREATE, "kvm_create_vcpu"); break;
    case 0xAE80: ox_emit(OXEVENT_VM_START,  "kvm_run");         break;
    case 0xAE46: ox_emit(OXEVENT_MEM_MAP,   "kvm_set_user_memory_region"); break;
    default:     ox_emit(OXEVENT_IOCTL,     "kvm_vm_ioctl");    break;
    }
    return 0;
}

/* â”€â”€ kprobe: do_execve (detect libvirt/qemu exec) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
static int handler_do_execve(struct kprobe *p, struct pt_regs *regs)
{
    char comm[TASK_COMM_LEN];
    get_task_comm(comm, current);
    if (strncmp(comm, "qemu", 4) == 0 || strncmp(comm, "libvirt", 7) == 0)
        ox_emit(OXEVENT_EXEC, comm);
    return 0;
}

static struct kprobe kp_kvm_ioctl = {
    .symbol_name = "kvm_vm_ioctl",
    .pre_handler = handler_kvm_vm_ioctl,
};
static struct kprobe kp_execve = {
    .symbol_name = "do_execve",
    .pre_handler = handler_do_execve,
};

/* â”€â”€ /dev/ankavm_audit â€” userspace read interface â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
static ssize_t ox_dev_read(struct file *f, char __user *buf, size_t len, loff_t *off)
{
    /* Return last event as JSON-ish line */
    struct ankavm_event ev;
    unsigned long flags;
    char out[512];
    int n, idx;

    if (atomic_read(&ox_count) == 0)
        return 0;

    spin_lock_irqsave(&ox_ring_lock, flags);
    idx = (atomic_read(&ox_head) - 1 + OXWARE_RING_SIZE) % OXWARE_RING_SIZE;
    ev = ox_ring[idx];
    spin_unlock_irqrestore(&ox_ring_lock, flags);

    n = snprintf(out, sizeof(out),
                 "{\"ts\":%llu,\"pid\":%u,\"uid\":%u,\"type\":%u,\"comm\":\"%s\",\"msg\":\"%s\"}\n",
                 ev.timestamp, ev.pid, ev.uid, ev.event_type, ev.comm, ev.msg);
    if (n > len) n = len;
    if (copy_to_user(buf, out, n))
        return -EFAULT;
    return n;
}

static const struct file_operations ox_fops = {
    .owner = THIS_MODULE,
    .read  = ox_dev_read,
};
static struct miscdevice ox_miscdev = {
    .minor = MISC_DYNAMIC_MINOR,
    .name  = "ankavm_audit",
    .fops  = &ox_fops,
    .mode  = 0440,
};

/* â”€â”€ Module init / exit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
static int __init ankavm_audit_init(void)
{
    int ret;

    ret = misc_register(&ox_miscdev);
    if (ret) {
        pr_err("ankavm_audit: misc_register failed: %d\n", ret);
        return ret;
    }

    ret = register_kprobe(&kp_kvm_ioctl);
    if (ret < 0)
        pr_warn("ankavm_audit: kvm_vm_ioctl probe failed: %d (KVM not loaded?)\n", ret);

    ret = register_kprobe(&kp_execve);
    if (ret < 0)
        pr_warn("ankavm_audit: do_execve probe failed: %d\n", ret);

    pr_info("ankavm_audit: v%s loaded â€” /dev/ankavm_audit ready\n", OXWARE_AUDIT_VERSION);
    ox_emit(OXEVENT_VM_CREATE, "ankavm_audit_init");
    return 0;
}

static void __exit ankavm_audit_exit(void)
{
    unregister_kprobe(&kp_kvm_ioctl);
    unregister_kprobe(&kp_execve);
    misc_deregister(&ox_miscdev);
    pr_info("ankavm_audit: unloaded\n");
}

module_init(ankavm_audit_init);
module_exit(ankavm_audit_exit);
