<?php
/**
 * AnkaVM Hypervisor - WHMCS Server Module v2.0.0
 *
 * Kurulum: modules/servers/ankavm/ dizinine kopyalayin.
 * WHMCS Admin -> Kurulum -> Sunucular -> Yeni Sunucu -> Tip: AnkaVM
 *
 * Sunucu ayarlari:
 *   Hostname    : AnkaVM API URL (ornek: https://ankavm.example.com)
 *   Access Hash : AnkaVM API anahtari (oxw_... ile baslar)
 *
 * Ozellikler: VM olustur/sil/askiya al, OS degistir, IP ata, console URL, kimlik bilgileri
 */

if (!defined("WHMCS")) {
    die("Bu dosya doÄŸrudan Ã§alÄ±ÅŸtÄ±rÄ±lamaz.");
}

// â”€â”€ Metadata â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_MetaData()
{
    return [
        'DisplayName'    => 'AnkaVM Hypervisor',
        'APIVersion'     => '1.1',
        'RequiresServer' => true,
        'Description'    => 'AnkaVM KVM Hypervisor otomasyonu - OS degistir, IP ata, console erisimi',
    ];
}

// â”€â”€ ÃœrÃ¼n yapÄ±landÄ±rma seÃ§enekleri â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_ConfigOptions()
{
    return [
        'vCPU' => [
            'Type'        => 'text',
            'Size'        => 5,
            'Default'     => '2',
            'Description' => 'Sanal CPU sayisi (1-256)',
        ],
        'RAM (MB)' => [
            'Type'        => 'text',
            'Size'        => 8,
            'Default'     => '2048',
            'Description' => 'Bellek MB cinsinden (2048 = 2 GB)',
        ],
        'Disk (GB)' => [
            'Type'        => 'text',
            'Size'        => 8,
            'Default'     => '50',
            'Description' => 'Disk alani GB cinsinden',
        ],
        'OS Template' => [
            'Type'        => 'text',
            'Size'        => 30,
            'Default'     => 'ubuntu-22.04',
            'Description' => 'AnkaVM template ID (ornek: ubuntu-22.04, debian-12)',
        ],
        'Network' => [
            'Type'        => 'text',
            'Size'        => 20,
            'Default'     => 'default',
            'Description' => 'Libvirt ag adi',
        ],
        'IP Pool' => [
            'Type'        => 'text',
            'Size'        => 30,
            'Default'     => '',
            'Description' => 'Otomatik IP atama icin havuz adi (bos birakilirsa IP atanmaz)',
        ],
        'SSL' => [
            'Type'        => 'text',
            'Size'        => 20,
            'Default'     => '',
            'Description' => 'SSL: bos=sistem CA (guvenli), "skip"=self-signed cert icin dogrulama kapat, ya da /path/to/ca.crt',
        ],
    ];
}

// â”€â”€ Yardimci: rastgele sifre uret â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function _ankavm_random_password($len = 20)
{
    $chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    $pwd   = '';
    for ($i = 0; $i < $len; $i++) {
        $pwd .= $chars[random_int(0, strlen($chars) - 1)];
    }
    return $pwd;
}

function _ankavm_random_vm_name()
{
    // Rastgele, insan okunabilir VM ismi: ornek -> nova-wolf-a3f7b2
    $adj  = ['fast','blue','dark','iron','nova','star','bold','pure','cool','free',
             'red','gold','soft','keen','peak','wise','true','firm','vast','epic'];
    $noun = ['wolf','hawk','lion','bear','fox','owl','ray','ore','arc','bay',
             'ash','elm','ivy','jet','oak','rye','sky','vim','web','zen'];
    $hex  = bin2hex(random_bytes(3)); // 6 karakter hex suffix
    return $adj[random_int(0, 19)] . '-' . $noun[random_int(0, 19)] . '-' . $hex;
}

// â”€â”€ Admin buton listesi â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_AdminCustomButtonArray()
{
    return [
        'OS Degistir'       => 'ChangeOS',
        'IP Ata'            => 'AssignIP',
        'Console URL Al'    => 'GetConsoleURL',
        'VM Baslat'         => 'StartVM',
        'VM Durdur'         => 'StopVM',
        'VM Yeniden Baslat' => 'RebootVM',
    ];
}

// â”€â”€ YardÄ±mcÄ±: AnkaVM REST API Ã§aÄŸrÄ±sÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function _ankavm_validate_vm_id($vm_id)
{
    if (!preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i', $vm_id)) {
        throw new Exception('GeÃ§ersiz VM ID formatÄ±');
    }
}

function _ankavm_api($params, $method, $endpoint, $body = null)
{
    $base = rtrim($params['serverhostname'], '/');
    $key  = trim($params['serveraccesshash']);

    // SSL: configoptions['SSL'] boÅŸ=sistem CA (gÃ¼venli), 'skip'=self-signed iÃ§in kapat
    $ssl_opt  = strtolower(trim($params['configoptions']['SSL'] ?? ''));
    $skip_ssl = in_array($ssl_opt, ['skip', '0', 'false', 'no'], true);
    $ca_path  = '';
    if (!$skip_ssl) {
        if ($ssl_opt && file_exists($ssl_opt)) {
            $ca_path = $ssl_opt;  // Ã¶zel CA bundle yolu
        } else {
            foreach (['/etc/ssl/certs/ca-certificates.crt', '/etc/pki/tls/certs/ca-bundle.crt'] as $f) {
                if (file_exists($f)) { $ca_path = $f; break; }
            }
        }
    }

    $ch = curl_init($base . '/api' . $endpoint);
    $headers = [
        'Content-Type: application/json',
        'X-API-Key: ' . $key,
    ];

    $curl_opts = [
        CURLOPT_RETURNTRANSFER  => true,
        CURLOPT_TIMEOUT         => 30,
        CURLOPT_CONNECTTIMEOUT  => 10,
        CURLOPT_CUSTOMREQUEST   => strtoupper($method),
        CURLOPT_HTTPHEADER      => $headers,
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
        return ['error' => 'cURL hatasÄ±: ' . $curl_err];
    }

    $data = json_decode($raw, true);

    if ($http_code >= 400) {
        return ['error' => ($data['error'] ?? "HTTP $http_code")];
    }

    return $data ?? [];
}

function _ankavm_vm_id($params)
{
    // VM ID, CreateAccount sÄ±rasÄ±nda username alanÄ±na kaydedilir
    return $params['username'] ?? '';
}

// â”€â”€ CreateAccount â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_CreateAccount($params)
{
    $cfg    = $params['configoptions'];
    $svcid  = $params['serviceid'];
    $name   = _ankavm_random_vm_name();

    // Musteri icin rastgele VM sifresi olustur
    $vm_password = _ankavm_random_password();

    $body = [
        'name'        => $name,
        'vcpus'       => (int)($cfg['vCPU']      ?? 2),
        'memory_mb'   => (int)($cfg['RAM (MB)']  ?? 2048),
        'disk_gb'     => (int)($cfg['Disk (GB)'] ?? 50),
        'os_template' => $cfg['OS Template']     ?? 'ubuntu-22.04',
        'network'     => $cfg['Network']         ?? 'default',
        'auto_start'  => true,
        'username'    => 'root',
        'password'    => $vm_password,
    ];

    // IP havuzu belirtilmisse otomatik IP ata
    $ip_pool = trim($cfg['IP Pool'] ?? '');
    if ($ip_pool) {
        $body['ip_pool'] = $ip_pool;
    }

    $result = _ankavm_api($params, 'POST', '/provision/create', $body);

    if (!empty($result['error'])) {
        return 'error: ' . $result['error'];
    }

    $vm    = $result['vm'] ?? [];
    $vm_id = $vm['id'] ?? $result['vm_id'] ?? '';
    $ip    = $vm['ip'] ?? ($vm['networks'][0]['ip'] ?? '');

    if (!$vm_id) {
        return 'error: VM ID alinamadi';
    }

    // VM ID ve sifreyi WHMCS servis alanina kaydet
    localAPI('UpdateClientProduct', [
        'serviceid' => $svcid,
        'username'  => $vm_id,
        'password'  => $vm_password,
    ]);

    if ($ip) {
        localAPI('UpdateClientProduct', [
            'serviceid'   => $svcid,
            'dedicatedip' => $ip,
        ]);
    }

    return 'success';
}

// â”€â”€ SuspendAccount â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_SuspendAccount($params)
{
    $vm_id = _ankavm_vm_id($params);
    if (!$vm_id) return 'error: VM ID bulunamadÄ±';
    try { _ankavm_validate_vm_id($vm_id); } catch (Exception $e) { return 'error: ' . $e->getMessage(); }

    $result = _ankavm_api($params, 'POST', "/provision/$vm_id/suspend");
    return !empty($result['error']) ? 'error: ' . $result['error'] : 'success';
}

// â”€â”€ UnsuspendAccount â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_UnsuspendAccount($params)
{
    $vm_id = _ankavm_vm_id($params);
    if (!$vm_id) return 'error: VM ID bulunamadÄ±';
    try { _ankavm_validate_vm_id($vm_id); } catch (Exception $e) { return 'error: ' . $e->getMessage(); }

    $result = _ankavm_api($params, 'POST', "/provision/$vm_id/unsuspend");
    return !empty($result['error']) ? 'error: ' . $result['error'] : 'success';
}

// â”€â”€ TerminateAccount â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_TerminateAccount($params)
{
    $vm_id = _ankavm_vm_id($params);
    if (!$vm_id) return 'success'; // Zaten silinmiÅŸ
    try { _ankavm_validate_vm_id($vm_id); } catch (Exception $e) { return 'error: ' . $e->getMessage(); }

    $result = _ankavm_api($params, 'DELETE', "/provision/$vm_id");
    return !empty($result['error']) ? 'error: ' . $result['error'] : 'success';
}

// â”€â”€ ChangePackage â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_ChangePackage($params)
{
    $vm_id = _ankavm_vm_id($params);
    if (!$vm_id) return 'error: VM ID bulunamadÄ±';
    try { _ankavm_validate_vm_id($vm_id); } catch (Exception $e) { return 'error: ' . $e->getMessage(); }

    $cfg  = $params['configoptions'];
    $body = [
        'vcpus'     => (int)($cfg['vCPU']      ?? 2),
        'memory_mb' => (int)($cfg['RAM (MB)']  ?? 2048),
        'disk_gb'   => (int)($cfg['Disk (GB)'] ?? 50),
    ];

    $result = _ankavm_api($params, 'PUT', "/provision/$vm_id/resize", $body);
    return !empty($result['error']) ? 'error: ' . $result['error'] : 'success';
}

// â”€â”€ OS Degistir â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_ChangeOS($params)
{
    $vm_id = _ankavm_vm_id($params);
    if (!$vm_id) return 'error: VM ID bulunamadi';
    try { _ankavm_validate_vm_id($vm_id); } catch (Exception $e) { return 'error: ' . $e->getMessage(); }
    $os = trim($params['configoptions']['OS Template'] ?? '');
    if (!$os) return 'error: OS Template yapilandirma seceneginde tanimli degil';
    $r = _ankavm_api($params, 'POST', "/provision/$vm_id/reinstall", ['os_template' => $os]);
    return !empty($r['error']) ? 'error: ' . $r['error'] : 'success';
}

// â”€â”€ Otomatik IP Atama â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_AssignIP($params)
{
    $vm_id = _ankavm_vm_id($params);
    if (!$vm_id) return 'error: VM ID bulunamadi';
    try { _ankavm_validate_vm_id($vm_id); } catch (Exception $e) { return 'error: ' . $e->getMessage(); }
    $pool = trim($params['configoptions']['IP Pool'] ?? '');
    $body = $pool ? ['pool' => $pool] : [];
    $r    = _ankavm_api($params, 'POST', "/provision/$vm_id/assign-ip", $body);
    if (!empty($r['error'])) return 'error: ' . $r['error'];
    if (!empty($r['ip'])) {
        localAPI('UpdateClientProduct', ['serviceid' => $params['serviceid'], 'dedicatedip' => $r['ip']]);
    }
    return 'success';
}

// â”€â”€ Console URL Al â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_GetConsoleURL($params)
{
    $vm_id = _ankavm_vm_id($params);
    if (!$vm_id) return 'error: VM ID bulunamadi';
    try { _ankavm_validate_vm_id($vm_id); } catch (Exception $e) { return 'error: ' . $e->getMessage(); }
    $r = _ankavm_api($params, 'POST', "/provision/$vm_id/console-token", []);
    if (!empty($r['error'])) return 'error: ' . $r['error'];
    $url = $r['console_url'] ?? '';
    return $url ? "success: $url" : 'error: Console URL alinamadi';
}

// â”€â”€ VM Kontrol Butonlari â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_StartVM($params)
{
    $vm_id = _ankavm_vm_id($params);
    if (!$vm_id) return 'error: VM ID bulunamadi';
    try { _ankavm_validate_vm_id($vm_id); } catch (Exception $e) { return 'error: ' . $e->getMessage(); }
    $r = _ankavm_api($params, 'POST', "/provision/$vm_id/start");
    return !empty($r['error']) ? 'error: ' . $r['error'] : 'success';
}

function ankavm_StopVM($params)
{
    $vm_id = _ankavm_vm_id($params);
    if (!$vm_id) return 'error: VM ID bulunamadi';
    try { _ankavm_validate_vm_id($vm_id); } catch (Exception $e) { return 'error: ' . $e->getMessage(); }
    $r = _ankavm_api($params, 'POST', "/provision/$vm_id/stop");
    return !empty($r['error']) ? 'error: ' . $r['error'] : 'success';
}

function ankavm_RebootVM($params)
{
    $vm_id = _ankavm_vm_id($params);
    if (!$vm_id) return 'error: VM ID bulunamadi';
    try { _ankavm_validate_vm_id($vm_id); } catch (Exception $e) { return 'error: ' . $e->getMessage(); }
    $r = _ankavm_api($params, 'POST', "/provision/$vm_id/reboot");
    return !empty($r['error']) ? 'error: ' . $r['error'] : 'success';
}

// â”€â”€ TestConnection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_TestConnection($params)
{
    // /provision/ping: API key dogrular + AnkaVM event log'a WHMCS baglantisi kaydeder
    $result = _ankavm_api($params, 'GET', '/provision/ping');

    if (!empty($result['error'])) {
        return [
            'success' => false,
            'error'   => $result['error'],
        ];
    }

    return ['success' => true, 'error' => ''];
}

// â”€â”€ ClientArea â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_ClientArea($params)
{
    $vm_id = _ankavm_vm_id($params);

    if (!$vm_id) {
        return [
            'templatefile' => 'clientarea',
            'vars'         => ['error' => 'VM henuz olusturulmadi.'],
        ];
    }

    $status = _ankavm_api($params, 'GET', "/provision/$vm_id/status");
    $creds  = _ankavm_api($params, 'GET', "/provision/$vm_id/credentials");

    // 5 dakika gecerli console token
    $console_url = '';
    $ct = _ankavm_api($params, 'POST', "/provision/$vm_id/console-token", []);
    if (empty($ct['error'])) { $console_url = $ct['console_url'] ?? ''; }

    // SSH kimlik bilgisi
    $ssh_user = 'root';
    $ssh_pass = $params['password'] ?? '';
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
        'templatefile' => 'clientarea',
        'vars'         => [
            'vm_id'         => $vm_id,
            'vm_name'       => $status['name']          ?? '---',
            'vm_status'     => $status['status']        ?? 'unknown',
            'vm_ip'         => $status['ip']            ?? '---',
            'vm_public_ip'  => $status['public_ip']     ?? '',
            'vm_int_ip'     => $status['internal_ip']   ?? '',
            'vm_cpu'        => $status['cpu_percent']   ?? 0,
            'vm_ram'        => $status['mem_percent']   ?? 0,
            'vm_ram_total'  => $status['mem_total_mb']  ?? 0,
            'vm_disk'       => $status['disk_used_gb']  ?? 0,
            'vm_disk_total' => $status['disk_total_gb'] ?? (int)($params['configoptions']['Disk (GB)'] ?? 0),
            'vm_vcpus'      => $status['vcpus']         ?? (int)($params['configoptions']['vCPU']      ?? 0),
            'vm_os_type'    => $status['os_type']       ?? '',
            'vm_hostname'   => $status['hostname']      ?? '',
            'ssh_user'      => $ssh_user,
            'ssh_pass'      => $ssh_pass,
            'console_url'   => $console_url,
            'base_url'      => rtrim($params['serverhostname'], '/'),
            'error'         => $status['error']         ?? '',
        ],
    ];
}

// â”€â”€ GetUsage â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ankavm_GetUsage($params)
{
    $vm_id = _ankavm_vm_id($params);
    if (!$vm_id) return [];

    $s = _ankavm_api($params, 'GET', "/provision/$vm_id/status");
    if (!empty($s['error'])) return [];
    return [
        'cpu'    => $s['cpu_percent']  ?? 0,
        'memory' => $s['mem_percent']  ?? 0,
        'hdd'    => $s['disk_used_gb'] ?? 0,
    ];
}
