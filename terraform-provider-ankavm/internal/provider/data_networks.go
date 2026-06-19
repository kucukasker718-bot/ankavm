package provider

import (
	"context"

	"github.com/hashicorp/terraform-plugin-sdk/v2/diag"
	"github.com/hashicorp/terraform-plugin-sdk/v2/helper/schema"
)

func dataSourceNetworks() *schema.Resource {
	return &schema.Resource{
		ReadContext: dataSourceNetworksRead,
		Schema: map[string]*schema.Schema{
			"networks": {
				Type:     schema.TypeList,
				Computed: true,
				Elem: &schema.Resource{
					Schema: map[string]*schema.Schema{
						"name":         {Type: schema.TypeString, Computed: true},
						"uuid":         {Type: schema.TypeString, Computed: true},
						"forward_mode": {Type: schema.TypeString, Computed: true},
						"subnet":       {Type: schema.TypeString, Computed: true},
						"active":       {Type: schema.TypeBool, Computed: true},
					},
				},
			},
		},
	}
}

func dataSourceNetworksRead(_ context.Context, d *schema.ResourceData, meta interface{}) diag.Diagnostics {
	c := meta.(*AnkaVMClient)

	resp, err := c.do("GET", "/networks", nil)
	if err != nil {
		return diag.FromErr(err)
	}

	rawNets, _ := resp["networks"].([]interface{})
	nets := make([]map[string]interface{}, 0, len(rawNets))
	for _, v := range rawNets {
		n, ok := v.(map[string]interface{})
		if !ok {
			continue
		}
		entry := map[string]interface{}{
			"name":         n["name"],
			"uuid":         n["uuid"],
			"forward_mode": n["forward_mode"],
			"subnet":       n["subnet"],
		}
		if active, ok := n["active"].(bool); ok {
			entry["active"] = active
		}
		nets = append(nets, entry)
	}

	_ = d.Set("networks", nets)
	d.SetId("ankavm-networks")
	return nil
}
