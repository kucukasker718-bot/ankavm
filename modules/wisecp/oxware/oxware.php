<?php
/**
 * OXware Hypervisor - WiseCP Server Module v2.0.0
 *
 * Kurulum: modules/server/oxware/ dizinine kopyalayin.
 * WiseCP Admin -> Sunucular -> Yeni Sunucu -> Tip: OXware
 *
 * Sunucu ayarlari:
 *   ip_address / hostname : OXware API URL (ornek: https://oxware.example.com)
 *   password / api_key    : OXware API anahtari (oxw_... ile baslar)
 *
 * Ozellikler: VM olustur/sil/askiya al, OS degistir, IP ata, console URL, kimlik bilgileri
 */

class Server_oxware
{
    // ── Metadata ──────────────────────────────────────────────────────────────

    public static function getConfig()
    {
        return [
            'name'     => 'OXware Hypervisor',
            'version'  => '2.0.0',
            'settings' => [
                'vcpus' => [
                    'type'        => 'text',
                    'label'       => 'vCPU',
                    'value'       => '2',
                    'description' => 'Sanal CPU sayisi (1-256)',
                ],
                'memory_mb' => [
                    'type'        => 'text',
                    'label'       => 'RAM (MB)',
                    'value'       => '2048',
                    'description' => 'Bellek MB cinsinden (2048 = 2 GB)',
                ],
                'disk_gb' => [
                    'type'        => 'text',
                    'label'       => 'Disk (GB)',
                    'value'       => '50',
                    'description' => 'Disk alani GB cinsinden',
                ],
                'os_template' => [
                    'type'        => 'text',
                    'label'       => 'OS Template',
                    'value'       => 'ubuntu-22.04',
                    'description' => 'OXware template ID (ornek: ubuntu-22.04, debian-12)',
                ],
                'network' => [
                    'type'        => 'text',
                    'label'       => 'Network',
                    'value'       => 'default',
                    'description' => 'Libvirt ag adi',
                ],
                'ip_pool' => [
                    'type'        => 'text',
                    'label'       => 'IP Pool',
                    'value'       => '',
                    'description' => 'Otomatik IP atama icin havuz adi (bos = IP atanmaz)',
                ],
            ],
        ];
    }

    // ── Yardimci: rastgele sifre ──────────────────────────────────────────────

    private static function randomPassword($len = 20)
    {
        $chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
        $pwd   = '';
        for ($i = 0; $i < $len; $i++) {
            $pwd .= $chars[random_int(0, strlen($chars) - 1)];
        }
        return $pwd;
    }

    private static function randomVmName()
    {
        // Rastgele insan okunabilir VM ismi: ornek -> nova-wolf-a3f7b2
        $adj  = ['fast','blue','dark','iron','nova','star','bold','pure','cool','free',
                 'red','gold','soft','keen','peak','wise','true','firm','vast','epic'];
        $noun = ['wolf','hawk','lion','bear','fox','owl','ray','ore','arc','bay',
                 'ash','elm','ivy','jet','oak','rye','sky','vim','web','zen'];
        $hex  = bin2hex(random_bytes(3));
        return $adj[random_int(0,19)] . '-' . $noun[random_int(0,19)] . '-' . $hex;
    }

    // ── Yardımcı: OXware REST API ─────────────────────────────────────────────

    private static function api($server, $method, $endpoint, $body = null)
    {
        $base = rtrim(
            $server['ip_address'] ?? $server['hostname'] ?? $server['host'] ?? '',
            '/'
        );
        $key = trim($server['api_key'] ?? $server['password'] ?? '');

        if (!$base) {
            return ['error' => 'Sunucu adresi tanımlı değil'];
        }

        // SSL: $server['ssl_verify']='skip' → self-signed cert için doğrulama kapat
        $ssl_opt  = strtolower(trim($server['ssl_verify'] ?? $server['ssl'] ?? ''));
        $skip_ssl = in_array($ssl_opt, ['skip', '0', 'false', 'no'], true);
        $ca_path  = '';
        if (!$skip_ssl) {
            foreach (['/etc/ssl/certs/ca-certificates.crt', '/etc/pki/tls/certs/ca-bundle.crt'] as $f) {
                if (file_exists($f)) { $ca_path = $f; break; }
            }
        }

        $ch = curl_init($base . '/api' . $endpoint);
        $curl_opts = [
            CURLOPT_RETURNTRANSFER  => true,
            CURLOPT_TIMEOUT         => 30,
            CURLOPT_CONNECTTIMEOUT  => 10,
            CURLOPT_CUSTOMREQUEST   => strtoupper($method),
            CURLOPT_HTTPHEADER      => [
                'Content-Type: application/json',
                'X-API-Key: ' . $key,
            ],
            CURLOPT_SSL_VERIFYPEER  => !$skip_ssl,
            CURLOPT_SSL_VERIFYHOST  => $skip_ssl ? 0 : 2,
        ];
        if ($ca_path) {
            $curl_opts[CURLOPT_CAINFO] = $ca_path;
        }
        curl_setopt_array($ch, $curl_opts);

        if ($body !== null) {
            curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body));
        }

        $raw       = curl_exec($ch);
        $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $curl_err  = curl_error($ch);
        curl_close($ch);

        if ($raw === false) {
            return ['error' => 'cURL hatası: ' . $curl_err];
        }

        $data = json_decode($raw, true);

        if ($http_code >= 400) {
            return ['error' => $data['error'] ?? "HTTP $http_code"];
        }

        return $data ?? [];
    }

    // ── UUID doğrulama ────────────────────────────────────────────────────────

    private static function validateVmId($vm_id)
    {
        if (!preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i', $vm_id)) {
            throw new Exception('Geçersiz VM ID formatı');
        }
    }

    // ── create ────────────────────────────────────────────────────────────────

    public static function create($package, $account, $server)
    {
        $name = self::randomVmName();

        // Musteri icin rastgele VM sifresi olustur
        $vm_password = self::randomPassword();

        $body = [
            'name'        => $name,
            'vcpus'       => (int)($package['vcpus']       ?? 2),
            'memory_mb'   => (int)($package['memory_mb']   ?? 2048),
            'disk_gb'     => (int)($package['disk_gb']     ?? 50),
            'os_template' => $package['os_template']       ?? 'ubuntu-22.04',
            'network'     => $package['network']           ?? 'default',
            'auto_start'  => true,
            'username'    => 'root',
            'password'    => $vm_password,
        ];

        // IP havuzu belirtilmisse otomatik IP ata
        $ip_pool = trim($package['ip_pool'] ?? '');
        if ($ip_pool) { $body['ip_pool'] = $ip_pool; }

        $result = self::api($server, 'POST', '/provision/create', $body);

        if (!empty($result['error'])) {
            throw new Exception($result['error']);
        }

        $vm    = $result['vm'] ?? [];
        $vm_id = $vm['id'] ?? $result['vm_id'] ?? '';
        $ip    = $vm['ip'] ?? ($vm['networks'][0]['ip'] ?? '');

        if (!$vm_id) { throw new Exception('VM ID alinamadi'); }

        // Kimlik bilgilerini vault'a kaydet
        try {
            self::api($server, 'POST', "/provision/$vm_id/credentials", [
                'username'  => 'root',
                'password'  => $vm_password,
                'cred_type' => 'ssh',
                'notes'     => 'WiseCP olusturma sifresi',
            ]);
        } catch (Exception $e) { /* Vault hatasi kritik degil */ }

        return [
            'username' => $vm_id,
            'password' => $vm_password,
            'ip'       => $ip,
            'ns1'      => '',
            'ns2'      => '',
        ];
    }

    // ── OS Degistir ───────────────────────────────────────────────────────────

    public static function changeOs($package, $account, $server)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) throw new Exception('VM ID bulunamadi');
        self::validateVmId($vm_id);
        $os = trim($package['os_template'] ?? '');
        if (!$os) throw new Exception('os_template paket ayarinda tanimli degil');
        $result = self::api($server, 'POST', "/provision/$vm_id/reinstall", ['os_template' => $os]);
        if (!empty($result['error'])) throw new Exception($result['error']);
        return true;
    }

    // ── Otomatik IP Atama ─────────────────────────────────────────────────────

    public static function assignIp($package, $account, $server)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) throw new Exception('VM ID bulunamadi');
        self::validateVmId($vm_id);
        $pool = trim($package['ip_pool'] ?? '');
        $body = $pool ? ['pool' => $pool] : [];
        $result = self::api($server, 'POST', "/provision/$vm_id/assign-ip", $body);
        if (!empty($result['error'])) throw new Exception($result['error']);
        return $result['ip'] ?? '';
    }

    // ── Console URL ───────────────────────────────────────────────────────────

    public static function getConsoleUrl($package, $account, $server)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) throw new Exception('VM ID bulunamadi');
        self::validateVmId($vm_id);
        $result = self::api($server, 'POST', "/provision/$vm_id/console-token", []);
        if (!empty($result['error'])) throw new Exception($result['error']);
        return $result['console_url'] ?? '';
    }

    // ── Kimlik Bilgileri Kaydet ───────────────────────────────────────────────

    public static function setCredentials($package, $account, $server, $username, $password)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) throw new Exception('VM ID bulunamadi');
        self::validateVmId($vm_id);
        $result = self::api($server, 'POST', "/provision/$vm_id/credentials", [
            'username'  => $username ?: 'root',
            'password'  => $password,
            'cred_type' => 'ssh',
        ]);
        if (!empty($result['error'])) throw new Exception($result['error']);
        return true;
    }

    // ── start ─────────────────────────────────────────────────────────────────

    public static function start($package, $account, $server)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) throw new Exception('VM ID bulunamadi');
        self::validateVmId($vm_id);
        $result = self::api($server, 'POST', "/provision/$vm_id/start");
        if (!empty($result['error'])) throw new Exception($result['error']);
        return true;
    }

    // ── stop ──────────────────────────────────────────────────────────────────

    public static function stop($package, $account, $server)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) throw new Exception('VM ID bulunamadi');
        self::validateVmId($vm_id);
        $result = self::api($server, 'POST', "/provision/$vm_id/stop");
        if (!empty($result['error'])) throw new Exception($result['error']);
        return true;
    }

    // ── reboot ────────────────────────────────────────────────────────────────

    public static function reboot($package, $account, $server)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) throw new Exception('VM ID bulunamadi');
        self::validateVmId($vm_id);
        $result = self::api($server, 'POST', "/provision/$vm_id/reboot");
        if (!empty($result['error'])) throw new Exception($result['error']);
        return true;
    }

    // ── suspend ───────────────────────────────────────────────────────────────

    public static function suspend($package, $account, $server)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) throw new Exception('VM ID bulunamadi');
        self::validateVmId($vm_id);

        $result = self::api($server, 'POST', "/provision/$vm_id/suspend");
        if (!empty($result['error'])) throw new Exception($result['error']);
        return true;
    }

    // ── unsuspend ─────────────────────────────────────────────────────────────

    public static function unsuspend($package, $account, $server)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) throw new Exception('VM ID bulunamadi');
        self::validateVmId($vm_id);

        $result = self::api($server, 'POST', "/provision/$vm_id/unsuspend");
        if (!empty($result['error'])) throw new Exception($result['error']);
        return true;
    }

    // ── terminate ─────────────────────────────────────────────────────────────

    public static function terminate($package, $account, $server)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) return true; // Zaten yok
        self::validateVmId($vm_id);

        $result = self::api($server, 'DELETE', "/provision/$vm_id");
        if (!empty($result['error'])) throw new Exception($result['error']);
        return true;
    }

    // ── resize ────────────────────────────────────────────────────────────────

    public static function resize($package, $account, $server)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) throw new Exception('VM ID bulunamadi');
        self::validateVmId($vm_id);

        $body = [
            'vcpus'     => (int)($package['vcpus']     ?? 2),
            'memory_mb' => (int)($package['memory_mb'] ?? 2048),
            'disk_gb'   => (int)($package['disk_gb']   ?? 50),
        ];

        $result = self::api($server, 'PUT', "/provision/$vm_id/resize", $body);
        if (!empty($result['error'])) throw new Exception($result['error']);
        return true;
    }

    // ── info ──────────────────────────────────────────────────────────────────

    public static function info($package, $account, $server)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) return [];

        $s     = self::api($server, 'GET', "/provision/$vm_id/status");
        $creds = self::api($server, 'GET', "/provision/$vm_id/credentials");

        if (!empty($s['error'])) return [];

        // Console URL
        $console_url = '';
        $ct = self::api($server, 'POST', "/provision/$vm_id/console-token", []);
        if (empty($ct['error'])) { $console_url = $ct['console_url'] ?? ''; }

        // SSH kimlik bilgisi
        $ssh_user = 'root';
        $ssh_pass = $account['password'] ?? '';
        if (!empty($creds['credentials'])) {
            foreach ($creds['credentials'] as $c) {
                $t = $c['cred_type'] ?? $c['type'] ?? '';
                if (in_array($t, ['ssh', 'custom', ''])) {
                    $ssh_user = $c['username'] ?? $ssh_user;
                    $ssh_pass = $c['password'] ?? $ssh_pass;
                    break;
                }
            }
        }

        return [
            'status'        => $s['status']         ?? 'unknown',
            'name'          => $s['name']            ?? '',
            'ip'            => $s['ip']              ?? '',
            'public_ip'     => $s['public_ip']       ?? '',
            'internal_ip'   => $s['internal_ip']     ?? '',
            'vcpus'         => $s['vcpus']           ?? 0,
            'mem_total_mb'  => $s['mem_total_mb']    ?? 0,
            'disk_total_gb' => $s['disk_total_gb']   ?? 0,
            'disk_used_gb'  => $s['disk_used_gb']    ?? 0,
            'cpu_usage'     => $s['cpu_percent']     ?? 0,
            'ram_usage'     => $s['mem_percent']     ?? 0,
            'ram_total'     => $s['mem_total_mb']    ?? 0,
            'disk_used'     => $s['disk_used_gb']    ?? 0,
            'os_type'       => $s['os_type']         ?? '',
            'hostname'      => $s['hostname']        ?? '',
            'ssh_user'      => $ssh_user,
            'ssh_pass'      => $ssh_pass,
            'console_url'   => $console_url,
        ];
    }

    // ── testConnection ────────────────────────────────────────────────────────

    public static function testConnection($server)
    {
        // /provision/ping: API key dogrular + OXware event log'a WiseCP baglantisi kaydeder
        $result = self::api($server, 'GET', '/provision/ping');
        if (!empty($result['error'])) {
            throw new Exception($result['error']);
        }
        return true;
    }

    // ── Musteri Paneli HTML Gorunumu ──────────────────────────────────────────

    public static function clientarea($package, $account, $server)
    {
        $vm_id = $account['username'] ?? '';
        if (!$vm_id) {
            return '<div style="color:#ef4444;padding:16px;">VM henuz olusturulmadi.</div>';
        }

        $data = self::info($package, $account, $server);

        $views_path = __DIR__ . '/views/client.php';
        if (file_exists($views_path)) {
            ob_start();
            include $views_path;
            return ob_get_clean();
        }

        // Fallback: views dosyasi yoksa basit HTML
        $ip     = htmlspecialchars($data['ip']       ?? '---');
        $user   = htmlspecialchars($data['ssh_user'] ?? 'root');
        $pass   = htmlspecialchars($data['ssh_pass'] ?? '');
        $status = htmlspecialchars($data['status']   ?? 'unknown');
        $con    = htmlspecialchars($data['console_url'] ?? '');

        $html  = "<div style='background:#0f1117;border:1px solid #2a2d3e;border-radius:8px;padding:16px;color:#e0e0e0;font-family:monospace'>";
        $html .= "<p><strong>Durum:</strong> $status</p>";
        $html .= "<p><strong>IP:</strong> $ip</p>";
        $html .= "<p><strong>Kullanici:</strong> $user</p>";
        $html .= "<p><strong>Sifre:</strong> <span style='filter:blur(4px)' onmouseover=\"this.style.filter=''\" onmouseout=\"this.style.filter='blur(4px)'\">$pass</span></p>";
        if ($con) {
            $html .= "<p><a href='$con' target='_blank' style='color:#6366f1'>Web Konsolu Ac</a></p>";
        }
        $html .= "</div>";
        return $html;
    }
}
