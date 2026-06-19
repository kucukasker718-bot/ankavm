package provider

import (
	"context"
	"fmt"

	"github.com/hashicorp/terraform-plugin-sdk/v2/diag"
	"github.com/hashicorp/terraform-plugin-sdk/v2/helper/schema"
	"github.com/hashicorp/terraform-plugin-sdk/v2/helper/validation"
)

func resourceStoragePool() *schema.Resource {
	return &schema.Resource{
		CreateContext: resourceStoragePoolCreate,
		ReadContext:   resourceStoragePoolRead,
		DeleteContext: resourceStoragePoolDelete,
		Importer: &schema.ResourceImporter{
			StateContext: schema.ImportStatePassthroughContext,
		},
		Schema: map[string]*schema.Schema{
			"name": {
				Type:         schema.TypeString,
				Required:     true,
				ForceNew:     true,
				ValidateFunc: validation.StringLenBetween(1, 64),
				Description:  "Depolama havuzu adÄ± (benzersiz)",
			},
			"pool_type": {
				Type:         schema.TypeString,
				Optional:     true,
				Default:      "dir",
				ForceNew:     true,
				ValidateFunc: validation.StringInSlice([]string{"dir", "lvm", "nfs"}, false),
				Description:  "Havuz tipi: dir, lvm veya nfs",
			},
			"path": {
				Type:        schema.TypeString,
				Optional:    true,
				ForceNew:    true,
				Description: "Hedef yol (dir/lvm iÃ§in)",
			},
			"source_host": {
				Type:        schema.TypeString,
				Optional:    true,
				ForceNew:    true,
				Description: "NFS kaynak host (nfs iÃ§in)",
			},
			"uuid": {
				Type:        schema.TypeString,
				Computed:    true,
				Description: "Havuz UUID",
			},
		},
	}
}

func resourceStoragePoolCreate(ctx context.Context, d *schema.ResourceData, meta interface{}) diag.Diagnostics {
	c := meta.(*AnkaVMClient)

	body := map[string]interface{}{
		"name":        d.Get("name").(string),
		"pool_type":   d.Get("pool_type").(string),
		"path":        d.Get("path").(string),
		"source_host": d.Get("source_host").(string),
	}

	resp, err := c.do("POST", "/storage/pools", body)
	if err != nil {
		return diag.FromErr(fmt.Errorf("depolama havuzu oluÅŸturulamadÄ±: %w", err))
	}

	id := ""
	if v, ok := resp["uuid"].(string); ok && v != "" {
		id = v
	} else if pool, ok := resp["pool"].(map[string]interface{}); ok {
		if v, ok := pool["uuid"].(string); ok {
			id = v
		}
	}
	if id == "" {
		id = d.Get("name").(string)
	}
	d.SetId(id)

	return resourceStoragePoolRead(ctx, d, meta)
}

func resourceStoragePoolRead(_ context.Context, d *schema.ResourceData, meta interface{}) diag.Diagnostics {
	c := meta.(*AnkaVMClient)

	resp, err := c.do("GET", "/storage/pools/"+d.Id(), nil)
	if err != nil {
		d.SetId("")
		return diag.FromErr(fmt.Errorf("havuz okunamadÄ±: %w", err))
	}

	pool, _ := resp["pool"].(map[string]interface{})
	if pool == nil {
		pool = resp
	}

	_ = d.Set("name", pool["name"])
	if v, ok := pool["type"]; ok {
		_ = d.Set("pool_type", v)
	}
	_ = d.Set("path", pool["path"])
	_ = d.Set("uuid", pool["uuid"])

	return nil
}

func resourceStoragePoolDelete(_ context.Context, d *schema.ResourceData, meta interface{}) diag.Diagnostics {
	c := meta.(*AnkaVMClient)

	_, err := c.do("DELETE", "/storage/pools/"+d.Id(), nil)
	if err != nil {
		return diag.FromErr(fmt.Errorf("havuz silinemedi: %w", err))
	}
	d.SetId("")
	return nil
}
