package main

import (
	"github.com/ShinnAsukha/ankavm-hypervisor/terraform-provider-ankavm/internal/provider"
	"github.com/hashicorp/terraform-plugin-sdk/v2/plugin"
)

func main() {
	plugin.Serve(&plugin.ServeOpts{
		ProviderFunc: provider.New,
	})
}
