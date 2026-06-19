<?php
/**
 * AnkaVM WiseCP Musteri Paneli Gorunumu
 * WiseCP bu dosyayi Server_ankavm::clientarea() veya info() metoduyla tetikler.
 * Degiskenler: $data (info() metodundan), $account, $package, $server
 */

$status      = $data['status']      ?? 'unknown';
$ip          = $data['ip']          ?? '';
$public_ip   = $data['public_ip']   ?? '';
$internal_ip = $data['internal_ip'] ?? '';
$cpu         = $data['cpu_usage']   ?? 0;
$ram         = $data['ram_usage']   ?? 0;
$ram_total   = $data['ram_total']   ?? 0;
$disk        = $data['disk_used']   ?? 0;
$ssh_user    = $data['ssh_user']    ?? 'root';
$ssh_pass    = $data['ssh_pass']    ?? '';
$console_url = $data['console_url'] ?? '';

$status_color = $status === 'running' ? '#10b981' : ($status === 'stopped' ? '#ef4444' : '#f59e0b');
$status_label = $status === 'running' ? 'Calisiyor' : ($status === 'stopped' ? 'Durduruldu' : $status);
?>
<style>
.oxw-panel { background:#0f1117; border:1px solid #2a2d3e; border-radius:10px; padding:20px; color:#e0e0e0; font-family:'Inter',sans-serif; max-width:800px; }
.oxw-title { font-size:18px; font-weight:700; color:#fff; margin-bottom:16px; display:flex; align-items:center; gap:8px; }
.oxw-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:16px; }
.oxw-card { background:#1a1d2e; border:1px solid #2a2d3e; border-radius:8px; padding:14px; }
.oxw-card-label { font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:#6b7280; margin-bottom:4px; }
.oxw-card-value { font-size:15px; font-weight:600; color:#fff; word-break:break-all; }
.oxw-cred { background:#1a1d2e; border:1px solid #2a2d3e; border-radius:8px; padding:14px; margin-bottom:12px; }
.oxw-cred-row { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
.oxw-cred-row:last-child { margin-bottom:0; }
.oxw-copy { background:#2a2d3e; border:none; border-radius:4px; color:#9ca3af; font-size:11px; padding:3px 8px; cursor:pointer; }
.oxw-copy:hover { background:#3a3d4e; color:#fff; }
.oxw-blur { filter:blur(4px); transition:filter .2s; cursor:pointer; }
.oxw-blur:hover { filter:none; }
.oxw-bar { background:#2a2d3e; border-radius:4px; height:6px; overflow:hidden; margin-top:6px; }
.oxw-bar-fill { height:100%; border-radius:4px; }
.oxw-console-btn { display:inline-flex; align-items:center; gap:6px; background:#6366f1; color:#fff; border:none; border-radius:6px; padding:10px 18px; font-size:13px; font-weight:600; cursor:pointer; text-decoration:none; margin-top:4px; }
.oxw-console-btn:hover { background:#4f46e5; color:#fff; text-decoration:none; }
.oxw-section-title { font-size:13px; font-weight:600; color:#9ca3af; text-transform:uppercase; letter-spacing:.05em; margin:16px 0 8px; }
.oxw-dot { width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:4px; }
</style>

<div class="oxw-panel">
  <div class="oxw-title">
    <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="#6366f1" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4" stroke-linecap="round"/></svg>
    Sunucu Yonetimi
    <span class="oxw-dot" style="background:<?= htmlspecialchars($status_color) ?>"></span>
    <span style="font-size:13px;color:<?= htmlspecialchars($status_color) ?>"><?= htmlspecialchars($status_label) ?></span>
  </div>

  <!-- IP Bilgisi -->
  <div class="oxw-section-title">Ag Bilgisi</div>
  <div class="oxw-grid">
    <div class="oxw-card">
      <div class="oxw-card-label">IP Adresi</div>
      <div class="oxw-card-value"><?= htmlspecialchars($ip ?: '---') ?></div>
    </div>
    <?php if ($public_ip && $public_ip !== $ip): ?>
    <div class="oxw-card">
      <div class="oxw-card-label">Public IP</div>
      <div class="oxw-card-value" style="color:#10b981"><?= htmlspecialchars($public_ip) ?></div>
    </div>
    <?php endif; ?>
    <?php if ($internal_ip): ?>
    <div class="oxw-card">
      <div class="oxw-card-label">Dahili IP</div>
      <div class="oxw-card-value"><?= htmlspecialchars($internal_ip) ?></div>
    </div>
    <?php endif; ?>
  </div>

  <!-- Kullanici Bilgileri -->
  <div class="oxw-section-title">Erisim Bilgileri (SSH)</div>
  <div class="oxw-cred">
    <div class="oxw-cred-row">
      <div>
        <div class="oxw-card-label">Kullanici Adi</div>
        <div class="oxw-card-value" id="oxw-user"><?= htmlspecialchars($ssh_user) ?></div>
      </div>
      <button class="oxw-copy" onclick="navigator.clipboard.writeText('<?= htmlspecialchars($ssh_user, ENT_QUOTES) ?>');this.textContent='Kopyalandi!';setTimeout(()=>this.textContent='Kopyala',2000)">Kopyala</button>
    </div>
    <div class="oxw-cred-row">
      <div>
        <div class="oxw-card-label">Sifre <span style="font-size:10px;color:#6b7280">(gormek icin tikla)</span></div>
        <div class="oxw-card-value oxw-blur" onclick="this.classList.toggle('oxw-blur')" id="oxw-pass"><?= htmlspecialchars($ssh_pass) ?></div>
      </div>
      <button class="oxw-copy" onclick="navigator.clipboard.writeText('<?= htmlspecialchars($ssh_pass, ENT_QUOTES) ?>');this.textContent='Kopyalandi!';setTimeout(()=>this.textContent='Kopyala',2000)">Kopyala</button>
    </div>
    <div class="oxw-cred-row">
      <div>
        <div class="oxw-card-label">IP / Host</div>
        <div class="oxw-card-value"><?= htmlspecialchars($ip) ?></div>
      </div>
      <button class="oxw-copy" onclick="navigator.clipboard.writeText('<?= htmlspecialchars($ip, ENT_QUOTES) ?>');this.textContent='Kopyalandi!';setTimeout(()=>this.textContent='Kopyala',2000)">Kopyala</button>
    </div>
  </div>

  <!-- Kaynak Kullanimi -->
  <div class="oxw-section-title">Kaynak Kullanimi</div>
  <div class="oxw-grid">
    <div class="oxw-card">
      <div class="oxw-card-label">CPU Kullanimi</div>
      <div class="oxw-card-value"><?= (int)$cpu ?>%</div>
      <div class="oxw-bar">
        <div class="oxw-bar-fill" style="width:<?= min(100,(int)$cpu) ?>%;background:<?= $cpu>90?'#ef4444':($cpu>70?'#f59e0b':'#6366f1') ?>"></div>
      </div>
    </div>
    <div class="oxw-card">
      <div class="oxw-card-label">RAM Kullanimi</div>
      <div class="oxw-card-value"><?= (int)$ram ?>%</div>
      <div class="oxw-bar">
        <div class="oxw-bar-fill" style="width:<?= min(100,(int)$ram) ?>%;background:<?= $ram>90?'#ef4444':($ram>70?'#f59e0b':'#10b981') ?>"></div>
      </div>
    </div>
    <div class="oxw-card">
      <div class="oxw-card-label">Disk Kullanimi</div>
      <div class="oxw-card-value"><?= (int)$disk ?> GB</div>
    </div>
    <?php if ($ram_total): ?>
    <div class="oxw-card">
      <div class="oxw-card-label">Toplam RAM</div>
      <div class="oxw-card-value"><?= (int)$ram_total ?> MB</div>
    </div>
    <?php endif; ?>
  </div>

  <!-- Console -->
  <?php if ($console_url): ?>
  <div class="oxw-section-title">Konsol</div>
  <a href="<?= htmlspecialchars($console_url) ?>" target="_blank" class="oxw-console-btn">
    &#x276F; Web Konsolu Ac (noVNC)
  </a>
  <p style="font-size:11px;color:#6b7280;margin-top:6px;">Link 5 dakika gecerlidir.</p>
  <?php endif; ?>
</div>
