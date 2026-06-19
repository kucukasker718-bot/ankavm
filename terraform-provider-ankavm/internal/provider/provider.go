package provider

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/hashicorp/terraform-plugin-sdk/v2/diag"
	"github.com/hashicorp/terraform-plugin-sdk/v2/helper/schema"
)

// AnkaVMClient holds connection details for API calls.
type AnkaVMClient struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

func (c *AnkaVMClient) do(method, path string, body interface{}) (map[string]interface{}, error) {
	var reqBody io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		reqBody = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.BaseURL+"/api"+path, reqBody)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.Token)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("API error %d: %s", resp.StatusCode, string(raw))
	}

	var result map[string]interface{}
	if err := json.Unmarshal(raw, &result); err != nil {
		return nil, fmt.Errorf("JSON parse hatasÄ±: %w", err)
	}
	return result, nil
}

// New returns the AnkaVM Terraform provider.
func New() *schema.Provider {
	return &schema.Provider{
		Schema: map[string]*schema.Schema{
			"url": {
				Type:        schema.TypeString,
				Required:    true,
				DefaultFunc: schema.EnvDefaultFunc("OXWARE_URL", nil),
				Description: "AnkaVM Hypervisor URL (Ã¶rn. https://ankavm.example.com)",
			},
			"token": {
				Type:        schema.TypeString,
				Required:    true,
				Sensitive:   true,
				DefaultFunc: schema.EnvDefaultFunc("OXWARE_TOKEN", nil),
				Description: "AnkaVM JWT eriÅŸim token'Ä±",
			},
		},
		ResourcesMap: map[string]*schema.Resource{
			"ankavm_vm":           resourceVM(),
			"ankavm_network":      resourceNetwork(),
			"ankavm_storage_pool": resourceStoragePool(),
		},
		DataSourcesMap: map[string]*schema.Resource{
			"ankavm_vms":      dataSourceVMs(),
			"ankavm_networks": dataSourceNetworks(),
		},
		ConfigureContextFunc: providerConfigure,
	}
}

func providerConfigure(_ context.Context, d *schema.ResourceData) (interface{}, diag.Diagnostics) {
	client := &AnkaVMClient{
		BaseURL: d.Get("url").(string),
		Token:   d.Get("token").(string),
		HTTP:    &http.Client{Timeout: 30 * time.Second},
	}
	return client, nil
}
