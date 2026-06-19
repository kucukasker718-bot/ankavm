# OXware Audit Kernel Module Makefile
obj-m += oxware_audit.o

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD  := $(shell pwd)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean

install: all
	install -m 644 oxware_audit.ko /lib/modules/$(shell uname -r)/extra/
	depmod -a
	modprobe oxware_audit
	echo "oxware_audit" >> /etc/modules-load.d/oxware.conf

uninstall:
	modprobe -r oxware_audit || true
	rm -f /lib/modules/$(shell uname -r)/extra/oxware_audit.ko
	depmod -a
	sed -i '/oxware_audit/d' /etc/modules-load.d/oxware.conf || true
