obj-m += oxware_guard.o
KDIR ?= /lib/modules/$(shell uname -r)/build
PWD  := $(shell pwd)
all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules
clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
install: all
	install -m 644 oxware_guard.ko /lib/modules/$(shell uname -r)/extra/
	depmod -a
	modprobe oxware_guard
	echo "oxware_guard" >> /etc/modules-load.d/oxware.conf
uninstall:
	modprobe -r oxware_guard || true
	rm -f /lib/modules/$(shell uname -r)/extra/oxware_guard.ko
	depmod -a
