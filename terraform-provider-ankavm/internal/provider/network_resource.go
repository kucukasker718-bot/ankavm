package provider

import (
	"context"
	"fmt"

	"github.com/hashicorp/terraform-plugin-sdk/v2/diag"
	"github.com/hashicorp/terraform-plugin-sdk/v2/helper/schema"
	"github.com/hashicorp/terraform-plugin-sdk/v2/helper/validation"
)

func resourceNetwork() *schema.Resource {
	return &schema.Resource{
		CreateContext: resourceNetworkCreate,
		ReadContext:   resourceNetworkRead,
		DeleteContext: resourceNetworkDelete,
		Importer: &schema.ResourceImporter{
			StateContext: schema.ImportStatePassthroughContext,
		},
		Schema: map[string]*schema.Schema{
			"name": {
				Type:         schema.TypeString,
				Required:     true,
				ForceNew:     true,
				ValidateFunc: validation.StringLenBetween(1, 64),
				Description:  "Ağ adı (benzersiz olmalı)",
			},
			"forward_mode": {
				Type:         schema.TypeString,
				Optional:     true,
				Default:      "nat",
				ForceNew:     true,
				ValidateFunc: validation.StringInSlice([]string{"nat", "bridge", "isolated"}, false),
				Description:  "İletim modu: nat, bridge veya isolated",
			},
			"subnet": {
				Type:         schema.TypeString,
				Optional:     true,
				ForceNew:     true,
				ValidateFunc: validation.IsCIDR,
				Description:  "Ağ subnet CIDR (örn. 192.168.100.0/24)",
			},
			"bridge": {
				Type:        schema.TypeString,
				Optional:    true,
				ForceNew:    true,
				Description: "Bridge arayüz adı (forward_mode=bridge için)",
			},
			"uuid": {
				Type:        schema.TypeString,
				Computed:    true,
				Description: "Ağın UUID değeri",
			},
			"active": {
				Type:        schema.TypeBool,
				Computed:    true,
				Description: "Ağ aktif mi?",
			},
		},
	}
}

func resourceNetworkCreate(ctx context.Context, d *schema.ResourceData, meta interface{}) diag.Diagnostics {
	c := meta.(*OXwareClient)

	body := map[string]interface{}{
		"name":         d.Get("name").(string),
		"forward_mode": d.Get("forward_mode").(string),
	}
	if v := d.Get("subnet").(string); v != "" {
		body["subnet"] = v
	}
	if v := d.Get("bridge").(string); v != "" {
		body["bridge"] = v
	}

	resp, err := c.do("POST", "/networks", body)
	if err != nil {
		return diag.FromErr(fmt.Errorf("ağ oluşturulamadı: %w", err))
	}

	id, _ := resp["uuid"].(string)
	if id == "" {
		id, _ = resp["id"].(string)
	}
	if id == "" {
		id, _ = resp["name"].(string)
	}
	if id == "" {
		return diag.Errorf("API'den ağ id/uuid alınamadı")
	}
	d.SetId(id)

	return resourceNetworkRead(ctx, d, meta)
}

func resourceNetworkRead(_ context.Context, d *schema.ResourceData, meta interface{}) diag.Diagnostics {
	c := meta.(*OXwareClient)

	resp, err := c.do("GET", "/networks/"+d.Id(), nil)
	if err != nil {
		d.SetId("")
		return diag.FromErr(fmt.Errorf("ağ okunamadı: %w", err))
	}

	net, _ := resp["network"].(map[string]interface{})
	if net == nil {
		net = resp
	}

	_ = d.Set("name", net["name"])
	_ = d.Set("forward_mode", net["forward_mode"])
	_ = d.Set("subnet", net["subnet"])
	_ = d.Set("bridge", net["bridge"])
	_ = d.Set("uuid", net["uuid"])
	if active, ok := net["active"].(bool); ok {
		_ = d.Set("active", active)
	}

	return nil
}

func resourceNetworkDelete(_ context.Context, d *schema.ResourceData, meta interface{}) diag.Diagnostics {
	c := meta.(*OXwareClient)

	_, err := c.do("DELETE", "/networks/"+d.Id(), nil)
	if err != nil {
		return diag.FromErr(fmt.Errorf("ağ silinemedi: %w", err))
	}
	d.SetId("")
	return nil
}
