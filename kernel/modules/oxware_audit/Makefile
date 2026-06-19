# AnkaVM Audit Kernel Module Makefile
obj-m += ankavm_audit.o

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD  := $(shell pwd)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean

install: all
	install -m 644 ankavm_audit.ko /lib/modules/$(shell uname -r)/extra/
	depmod -a
	modprobe ankavm_audit
	echo "ankavm_audit" >> /etc/modules-load.d/ankavm.conf

uninstall:
	modprobe -r ankavm_audit || true
	rm -f /lib/modules/$(shell uname -r)/extra/ankavm_audit.ko
	depmod -a
	sed -i '/ankavm_audit/d' /etc/modules-load.d/ankavm.conf || true
