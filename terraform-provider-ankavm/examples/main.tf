terraform {
  required_providers {
    ankavm = {
      source  = "ShinnAsukha/ankavm"
      version = "~> 1.0"
    }
  }
}

provider "ankavm" {
  url   = "https://ankavm.example.com"   # veya OXWARE_URL env
  token = var.ankavm_token               # veya OXWARE_TOKEN env
}

variable "ankavm_token" {
  sensitive = true
}

# Mevcut VM'leri listele
data "ankavm_vms" "all" {}

output "vm_names" {
  value = [for v in data.ankavm_vms.all.vms : v.name]
}

# Yeni VM oluÅŸtur
resource "ankavm_vm" "web" {
  name      = "web-server-01"
  vcpus     = 2
  memory_mb = 2048
  disk_gb   = 20
  network   = "default"
  os_variant = "ubuntu22.04"

  # cloud-init ile otomatik yapÄ±landÄ±r
  cloud_init_user     = "ubuntu"
  cloud_init_password = "changeme"
  cloud_init_ssh_key  = file("~/.ssh/id_rsa.pub")
  cloud_init_hostname = "web-server-01"
}

output "web_vm_id"    { value = ankavm_vm.web.id }
output "web_vnc_port" { value = ankavm_vm.web.vnc_port }

# Mevcut aÄŸlarÄ± listele
data "ankavm_networks" "all" {}

output "network_names" {
  value = [for n in data.ankavm_networks.all.networks : n.name]
}

# Yeni NAT aÄŸÄ± oluÅŸtur
resource "ankavm_network" "app" {
  name         = "app-net"
  forward_mode = "nat"
  subnet       = "192.168.50.0/24"
}

# Depolama havuzu oluÅŸtur (dizin tabanlÄ±)
resource "ankavm_storage_pool" "data" {
  name      = "data-pool"
  pool_type = "dir"
  path      = "/var/lib/ankavm/pools/data"
}

output "app_net_uuid" { value = ankavm_network.app.uuid }
output "pool_uuid"    { value = ankavm_storage_pool.data.uuid }
