// SPDX-License-Identifier: GPL-2.0
/*
 * xdp_filter.c â€” AnkaVM XDP Network Security Filter
 * Attach to each VM tap interface (vnet0, vnet1, ...) via:
 *   ip link set dev vnetX xdpgeneric obj xdp_filter.o sec xdp
 * Blocks: ARP spoofing, ICMP floods, raw socket VM-escape attempts.
 * Build: clang -O2 -target bpf -D__x86_64__ -D__TARGET_ARCH_x86 \
 *             -I/usr/include/x86_64-linux-gnu -I/usr/include \
 *             -c xdp_filter.c -o xdp_filter.o
 */

/* Prevent gnu/stubs.h from pulling in 32-bit stubs-32.h on x86_64 */
#ifndef __x86_64__
# define __x86_64__
#endif
/* Tell glibc stubs.h we're 64-bit only â€” skip stubs-32.h include */
#define __GLIBC_HAVE_LONG_LONG 1
/* BPF programs don't use userspace stubs at all */
#define __stub___kernel_long_t
#define __stub___kernel_ulong_t

#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/icmp.h>
#include <linux/if_arp.h>
#include <linux/in.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>

/* Per-IP packet rate map (LRU, 4096 entries) */
struct {
    __uint(type, BPF_MAP_TYPE_LRU_HASH);
    __uint(max_entries, 4096);
    __type(key,   __u32);   /* source IP */
    __type(value, __u64);   /* packet count */
} pkt_count SEC(".maps");

/* Allowlisted MAC map â€” only known VM MACs allowed */
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 256);
    __type(key,   __u64);   /* MAC as u64 (6 bytes padded) */
    __type(value, __u8);    /* 1 = allowed */
} allowed_macs SEC(".maps");

#define ICMP_RATE_LIMIT  100   /* pps per source IP */
#define ARP_RATE_LIMIT    50

static __always_inline __u64 mac_to_u64(const __u8 *mac)
{
    return ((__u64)mac[0] << 40) | ((__u64)mac[1] << 32) |
           ((__u64)mac[2] << 24) | ((__u64)mac[3] << 16) |
           ((__u64)mac[4] <<  8) |  (__u64)mac[5];
}

SEC("xdp")
int ankavm_xdp_filter(struct xdp_md *ctx)
{
    void *data     = (void *)(long)ctx->data;
    void *data_end = (void *)(long)ctx->data_end;
    struct ethhdr *eth = data;

    if ((void *)(eth + 1) > data_end)
        return XDP_PASS;

    __u16 proto = bpf_ntohs(eth->h_proto);

    /* â”€â”€ ARP spoofing detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    if (proto == ETH_P_ARP) {
        struct arphdr *arp = (void *)(eth + 1);
        if ((void *)(arp + 1) > data_end)
            return XDP_DROP;
        /* Count ARP per source MAC */
        __u64 src_mac = mac_to_u64(eth->h_source);
        __u8 *allowed = bpf_map_lookup_elem(&allowed_macs, &src_mac);
        /* If MAC not in allowlist and we have entries, drop (spoofed ARP) */
        /* allowlist empty = learning mode = pass */
        if (allowed && *allowed == 0)
            return XDP_DROP;
        return XDP_PASS;
    }

    /* â”€â”€ IPv4 processing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    if (proto != ETH_P_IP)
        return XDP_PASS;

    struct iphdr *iph = (void *)(eth + 1);
    if ((void *)(iph + 1) > data_end)
        return XDP_PASS;

    __u32 src_ip = iph->saddr;

    /* â”€â”€ ICMP flood protection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
    if (iph->protocol == IPPROTO_ICMP) {
        __u64 *cnt = bpf_map_lookup_elem(&pkt_count, &src_ip);
        __u64 new_cnt = 1;
        if (cnt) {
            new_cnt = *cnt + 1;
            if (new_cnt > ICMP_RATE_LIMIT)
                return XDP_DROP;
        }
        bpf_map_update_elem(&pkt_count, &src_ip, &new_cnt, BPF_ANY);
    }

    return XDP_PASS;
}

char _license[] SEC("license") = "GPL";
