obj-m += ankavm_guard.o
KDIR ?= /lib/modules/$(shell uname -r)/build
PWD  := $(shell pwd)
all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules
clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
install: all
	install -m 644 ankavm_guard.ko /lib/modules/$(shell uname -r)/extra/
	depmod -a
	modprobe ankavm_guard
	echo "ankavm_guard" >> /etc/modules-load.d/ankavm.conf
uninstall:
	modprobe -r ankavm_guard || true
	rm -f /lib/modules/$(shell uname -r)/extra/ankavm_guard.ko
	depmod -a
