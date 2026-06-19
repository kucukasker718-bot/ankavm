/**
 * vswitch.js â€” ankavm Virtual Switch Management (ESXi-style)
 * Renders libvirt networks as visual vSwitch cards using DOM methods (no innerHTML for data).
 */
(function(global) {
  'use strict';

  // â”€â”€ helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  function esc(s) {
    if (typeof escHtml === 'function') return escHtml(String(s));
    var d = document.createElement('div');
    d.textContent = String(s || '');
    return d.textContent;
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function _tok() { return localStorage.getItem('ankavm_token') || ''; }

  function api(url, opts) {
    // GET-only: delegate to _api when available (avoids signature mismatch for POST)
    if (!opts || typeof opts !== 'object' || !opts.method) {
      if (typeof _api === 'function') return _api(url);
      return fetch(url, { headers: { Authorization: 'Bearer ' + _tok() } }).then(function(r) { return r.json(); });
    }
    // POST/PUT/DELETE: always use fetch directly
    var hdrs = Object.assign({ Authorization: 'Bearer ' + _tok() }, opts.headers || {});
    return fetch(url, Object.assign({}, opts, { headers: hdrs })).then(function(r) { return r.json(); });
  }

  function apiPost(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + _tok() },
      body: JSON.stringify(body || {})
    }).then(function(r) { return r.json(); });
  }

  // â”€â”€ Build vSwitch card â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  function buildVSwitchCard(net, physNics) {
    var isActive   = net.active;
    var mode       = (net.mode || 'nat').toLowerCase();
    var bridgeName = net.bridge || '';
    var vmCount    = net.vm_count !== undefined ? net.vm_count : 'â€”';
    var modeLabel  = mode === 'bridge' ? 'bridge' : mode === 'nat' ? 'nat' : 'standard';

    var uplinkIfaces = (physNics || []).filter(function(n) {
      return n.master === bridgeName || n.bridge === bridgeName;
    });

    // â”€â”€ Card â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    var card = el('div', 'vsw-card');

    // Header
    var head = el('div', 'vsw-card-head');
    var ico  = el('i');
    ico.className = 'fa-solid fa-sitemap';
    ico.style.cssText = 'color:#60a5fa;font-size:15px';
    var nameSpan = el('span', '', net.name);
    nameSpan.style.cssText = 'font-size:13px;font-weight:700';
    var badge = el('span', 'vsw-badge ' + modeLabel, mode.toUpperCase());
    var brSpan = el('span', '', bridgeName || '');
    brSpan.style.cssText = 'font-size:11px;color:var(--text-muted,#7d8590);font-family:monospace';
    var vmSp  = el('span', '', vmCount + ' VM');
    vmSp.style.cssText = 'margin-left:auto;font-size:11px;color:var(--text-muted,#7d8590)';
    var dot   = el('span');
    dot.style.cssText = 'width:8px;height:8px;border-radius:50%;flex-shrink:0;background:' +
      (isActive ? '#3fb950;box-shadow:0 0 6px #3fb95070' : '#6e7681');
    var chev  = el('i');
    chev.className = 'fa-solid fa-chevron-down';
    chev.style.cssText = 'color:var(--text-muted,#7d8590);font-size:11px;margin-left:4px';

    [ico, nameSpan, badge, brSpan, vmSp, dot, chev].forEach(function(c) { head.appendChild(c); });
    card.appendChild(head);

    // Body (collapsible)
    var body = el('div', 'vsw-body');
    var diagram = el('div', 'vsw-diagram');

    // â€” Uplinks col â€”
    var uplinkCol = el('div', 'vsw-col uplink');
    var ulLabel = el('div', '', 'UPLINK');
    ulLabel.style.cssText = 'font-size:9px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted,#7d8590);margin-bottom:6px';
    uplinkCol.appendChild(ulLabel);

    if (uplinkIfaces.length) {
      uplinkIfaces.forEach(function(u) {
        var row = el('div', 'uplink-item');
        var udot = el('span', 'uplink-dot ' + (u.state === 'up' ? 'up' : 'down'));
        var uname = el('span', '', u.name);
        var uspd = el('span', '', u.speed || '');
        uspd.style.cssText = 'margin-left:auto;font-size:10px;color:var(--text-muted,#7d8590)';
        row.appendChild(udot); row.appendChild(uname); row.appendChild(uspd);
        uplinkCol.appendChild(row);
      });
    } else {
      var row = el('div', 'uplink-item');
      row.style.cssText = 'color:var(--text-muted,#7d8590);opacity:.5';
      var udot = el('span', 'uplink-dot down');
      var uname = el('span', '', 'Host NAT');
      row.appendChild(udot); row.appendChild(uname);
      uplinkCol.appendChild(row);
    }

    // â€” Connector â€”
    var conn1 = el('div', 'vsw-connector');

    // â€” Switch box col â€”
    var swCol = el('div', 'vsw-col switch');
    var swBox = el('div', 'vsw-sw-box');
    var swName = el('div', 'sw-name', net.name);
    var swSub  = el('div', 'sw-sub', bridgeName || mode);
    var ports  = el('div', 'vsw-sw-ports');
    var portCount = Math.min(8, Math.max(2, 1 + uplinkIfaces.length));
    for (var p = 0; p < portCount; p++) {
      var port = el('div', 'vsw-port' + (p < (uplinkIfaces.length || 1) ? ' up' : ''));
      ports.appendChild(port);
    }
    [swName, swSub, ports].forEach(function(c) { swBox.appendChild(c); });
    swCol.appendChild(swBox);

    // â€” Connector â€”
    var conn2 = el('div', 'vsw-connector');

    // â€” Port Groups col â€”
    var pgCol = el('div', 'vsw-col pgroups');
    var pgLabel = el('div', '', 'PORT GROUPS');
    pgLabel.style.cssText = 'font-size:9px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted,#7d8590);margin-bottom:6px';
    pgCol.appendChild(pgLabel);

    // One default port group per network
    var pgItem = el('div', 'pg-item');
    var pgIco  = el('div', 'pg-icon', 'ğŸ”Œ');
    pgIco.style.background = 'rgba(61,130,240,0.12)';
    var pgInfo = el('div');
    var pgName = el('div', '', net.name);
    pgName.style.fontWeight = '600';
    var pgType = el('div', '', 'VM Network');
    pgType.style.cssText = 'font-size:10px;color:var(--text-muted,#7d8590)';
    var netRange = el('span', '', net.network || '');
    netRange.style.cssText = 'margin-left:auto;font-size:11px;color:var(--text-muted,#7d8590)';
    pgInfo.appendChild(pgName); pgInfo.appendChild(pgType);
    [pgIco, pgInfo, netRange].forEach(function(c) { pgItem.appendChild(c); });
    pgCol.appendChild(pgItem);

    var addPgBtn = el('button', 'btn sm', '+ Port Group Ekle');
    addPgBtn.style.cssText = 'margin-top:6px;font-size:10px';
    addPgBtn.onclick = function() { global.vswitchAddPortGroup(net.name); };
    pgCol.appendChild(addPgBtn);

    [uplinkCol, conn1, swCol, conn2, pgCol].forEach(function(c) { diagram.appendChild(c); });
    body.appendChild(diagram);

    // Actions row
    var actions = el('div', 'vsw-actions');
    var btnStart = el('button', 'btn sm', 'â–¶ BaÅŸlat');
    if (isActive) btnStart.disabled = true;
    btnStart.onclick = function() { global.vswitchStart(net.name); };

    var btnStop = el('button', 'btn sm', 'â–  Durdur');
    btnStop.style.color = '#f87171';
    if (!isActive) btnStop.disabled = true;
    btnStop.onclick = function() { global.vswitchStop(net.name); };

    var btnEdit = el('button', 'btn sm', 'âš™ DÃ¼zenle');
    btnEdit.onclick = function() { global.vswitchEdit(net.name); };

    var btnDel = el('button', 'btn sm', 'ğŸ—‘ Sil');
    btnDel.style.cssText = 'color:#f87171;margin-left:auto';
    btnDel.onclick = function() { global.vswitchDelete(net.name); };

    [btnStart, btnStop, btnEdit, btnDel].forEach(function(b) { actions.appendChild(b); });
    body.appendChild(actions);
    card.appendChild(body);

    // Toggle collapse
    head.onclick = function() {
      body.style.display = body.style.display === 'none' ? '' : 'none';
    };

    return card;
  }

  // â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  global.loadVSwitches = function() {
    var grid = document.getElementById('vsw-grid');
    if (!grid) return;

    var spinner = el('div', '', '');
    spinner.style.cssText = 'text-align:center;padding:40px;color:var(--text-muted,#7d8590)';
    var ico = el('i'); ico.className = 'fa-solid fa-spinner fa-spin';
    ico.style.cssText = 'font-size:22px;margin-bottom:8px;display:block';
    var txt = el('span', '', 'YÃ¼kleniyorâ€¦');
    spinner.appendChild(ico); spinner.appendChild(txt);
    while (grid.firstChild) grid.removeChild(grid.firstChild);
    grid.appendChild(spinner);

    Promise.all([
      api('/api/networks'),
      api('/api/networks/host-interfaces').catch(function() { return { interfaces: [] }; })
    ]).then(function(results) {
      var netData = results[0]; var ifData = results[1];
      var nets     = netData.networks || [];
      var ifaces   = ifData.interfaces || [];
      var physNics = ifaces.filter(function(i) { return i.type === 'ethernet'; });

      while (grid.firstChild) grid.removeChild(grid.firstChild);

      if (!nets.length) {
        var empty = el('div', '', '');
        empty.style.cssText = 'text-align:center;padding:40px;color:var(--text-muted,#7d8590)';
        var ei = el('i'); ei.className = 'fa-solid fa-sitemap';
        ei.style.cssText = 'font-size:28px;opacity:.2;display:block;margin-bottom:8px';
        var et = el('span', '', 'vSwitch bulunamadÄ± â€” Yeni AÄŸ oluÅŸturun');
        empty.appendChild(ei); empty.appendChild(et);
        grid.appendChild(empty);
        return;
      }

      nets.forEach(function(net) {
        grid.appendChild(buildVSwitchCard(net, physNics));
      });
    }).catch(function(e) {
      while (grid.firstChild) grid.removeChild(grid.firstChild);
      var errDiv = el('div', '', '');
      errDiv.style.cssText = 'padding:20px;color:#f87171';
      errDiv.textContent = 'YÃ¼klenemedi: ' + (e.message || e);
      grid.appendChild(errDiv);
    });
  };

  global.openVSwitchCreate = function() {
    if (typeof openCreateNetworkModal === 'function') openCreateNetworkModal();
  };

  global.vswitchStart = function(name) {
    api('/api/networks/' + encodeURIComponent(name) + '/start', { method: 'POST' })
      .then(function() { global.loadVSwitches(); })
      .catch(function(e) { alert('BaÅŸlatma hatasÄ±: ' + e.message); });
  };

  global.vswitchStop = function(name) {
    if (!confirm(name + ' aÄŸÄ±nÄ± durdurmak istediÄŸinize emin misiniz? BaÄŸlÄ± VM\'ler etkilenebilir.')) return;
    api('/api/networks/' + encodeURIComponent(name) + '/stop', { method: 'POST' })
      .then(function() { global.loadVSwitches(); })
      .catch(function(e) { alert('Durdurma hatasÄ±: ' + e.message); });
  };

  // â”€â”€ Edit Modal helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  function _vswCloseEdit() {
    var ov = document.getElementById('vsw-edit-overlay');
    if (ov && ov.parentNode) ov.parentNode.removeChild(ov);
  }

  function _vswField(labelText, id, value, placeholder) {
    var wrap = el('div');
    wrap.style.cssText = 'margin-bottom:14px';
    var lbl = el('label', '', labelText);
    lbl.style.cssText = 'display:block;font-size:10px;color:#7d8590;margin-bottom:5px;text-transform:uppercase;letter-spacing:.06em;font-weight:600';
    var inp = el('input');
    inp.id = id; inp.type = 'text';
    inp.value = value || ''; inp.placeholder = placeholder || '';
    inp.style.cssText = 'width:100%;box-sizing:border-box;background:#0d1117;border:1px solid rgba(255,255,255,.14);border-radius:7px;padding:9px 12px;color:#e6edf3;font-size:13px;outline:none;transition:border .15s';
    inp.onfocus = function() { inp.style.borderColor = 'rgba(61,130,240,.6)'; };
    inp.onblur  = function() { inp.style.borderColor = 'rgba(255,255,255,.14)'; };
    wrap.appendChild(lbl); wrap.appendChild(inp);
    return wrap;
  }

  function _vswSection(text) {
    var s = el('div', '', text);
    s.style.cssText = 'font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#60a5fa;margin:18px 0 10px;font-weight:700;padding-bottom:5px;border-bottom:1px solid rgba(255,255,255,.06)';
    return s;
  }

  global.vswitchEdit = function(name) {
    // Overlay
    var overlay = el('div'); overlay.id = 'vsw-edit-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.65);display:flex;align-items:center;justify-content:center';
    overlay.onclick = function(e) { if (e.target === overlay) _vswCloseEdit(); };

    var box = el('div');
    box.style.cssText = 'background:#141c2e;border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:28px 32px;width:500px;max-width:95vw;box-shadow:0 24px 64px rgba(0,0,0,.7);font-family:inherit';

    // Header
    var hdr = el('div'); hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:6px';
    var ttl = el('div', '', 'âš™ vSwitch DÃ¼zenle'); ttl.style.cssText = 'font-size:15px;font-weight:700;color:#e6edf3';
    var sub = el('div', '', name); sub.style.cssText = 'font-size:11px;color:#60a5fa;font-family:monospace;margin-bottom:16px';
    var xbtn = el('button', '', 'âœ•');
    xbtn.style.cssText = 'background:none;border:none;color:#7d8590;font-size:17px;cursor:pointer;padding:0 4px;line-height:1';
    xbtn.onclick = _vswCloseEdit;
    hdr.appendChild(ttl); hdr.appendChild(xbtn);
    box.appendChild(hdr); box.appendChild(sub);

    // Spinner
    var loader = el('div'); loader.style.cssText = 'text-align:center;padding:32px;color:#7d8590';
    var spin = el('i'); spin.className = 'fa-solid fa-spinner fa-spin';
    spin.style.cssText = 'font-size:22px;display:block;margin-bottom:10px';
    loader.appendChild(spin); loader.appendChild(el('span', '', 'AÄŸ bilgisi yÃ¼kleniyorâ€¦'));
    box.appendChild(loader);

    overlay.appendChild(box);
    document.body.appendChild(overlay);

    // Fetch current network info
    api('/api/networks/' + encodeURIComponent(name)).then(function(d) {
      box.removeChild(loader);
      var net = d.network || {};

      // IP section
      box.appendChild(_vswSection('IP YapÄ±landÄ±rmasÄ±'));
      box.appendChild(_vswField('Gateway / IP Adresi', 'vswe-ip',   net.ip || net.gateway || net.ip_address || '', '192.168.x.1'));
      box.appendChild(_vswField('AÄŸ Maskesi',          'vswe-mask', net.netmask || net.mask || '', '255.255.255.0'));

      // DHCP section
      box.appendChild(_vswSection('DHCP'));
      var dhcpGrid = el('div'); dhcpGrid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:12px';
      dhcpGrid.appendChild(_vswField('BaÅŸlangÄ±Ã§ IP', 'vswe-dhcps', net.dhcp_start || '', '192.168.x.100'));
      dhcpGrid.appendChild(_vswField('BitiÅŸ IP',     'vswe-dhcpe', net.dhcp_end   || '', '192.168.x.200'));
      box.appendChild(dhcpGrid);

      // Options section
      box.appendChild(_vswSection('SeÃ§enekler'));
      var autoWrap = el('label');
      autoWrap.style.cssText = 'display:flex;align-items:center;gap:10px;cursor:pointer;font-size:13px;color:#e6edf3;padding:4px 0';
      var autoCb = el('input'); autoCb.id = 'vswe-auto'; autoCb.type = 'checkbox';
      autoCb.checked = !!net.autostart;
      autoCb.style.cssText = 'width:15px;height:15px;cursor:pointer;accent-color:#3d82f0';
      autoWrap.appendChild(autoCb);
      autoWrap.appendChild(el('span', '', 'Otomatik BaÅŸlat (sistem aÃ§Ä±lÄ±ÅŸÄ±nda etkin)'));
      box.appendChild(autoWrap);

      // Status
      var statusEl = el('div'); statusEl.style.cssText = 'font-size:12px;min-height:20px;margin-top:10px';
      box.appendChild(statusEl);

      // Button row
      var btnRow = el('div');
      btnRow.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;margin-top:20px;padding-top:16px;border-top:1px solid rgba(255,255,255,.06)';

      var cancelBtn = el('button', 'btn', 'Ä°ptal'); cancelBtn.onclick = _vswCloseEdit;

      var saveBtn = el('button', 'btn primary', 'ğŸ’¾ Kaydet');
      saveBtn.onclick = function() {
        var ip   = (document.getElementById('vswe-ip')    || {}).value || '';
        var mask = (document.getElementById('vswe-mask')  || {}).value || '';
        var ds   = (document.getElementById('vswe-dhcps') || {}).value || '';
        var de   = (document.getElementById('vswe-dhcpe') || {}).value || '';
        var autostart = !!(document.getElementById('vswe-auto') || {}).checked;

        saveBtn.disabled = true; saveBtn.textContent = 'Kaydediliyorâ€¦';
        statusEl.textContent = ''; statusEl.style.color = '#7d8590';

        var updateBody = {};
        if (ip)   updateBody.ip_address = ip;
        if (mask) updateBody.netmask    = mask;
        if (ds)   updateBody.dhcp_start = ds;
        if (de)   updateBody.dhcp_end   = de;

        Promise.all([
          apiPost('/api/networks/' + encodeURIComponent(name) + '/update',    updateBody),
          apiPost('/api/networks/' + encodeURIComponent(name) + '/autostart', { enabled: autostart })
        ]).then(function(results) {
          var err0 = results[0] && results[0].error;
          var err1 = results[1] && results[1].error;
          if (err0 || err1) throw new Error(err0 || err1);
          statusEl.textContent = 'âœ“ Kaydedildi â€” aÄŸ yeniden baÅŸlatÄ±ldÄ±';
          statusEl.style.color = '#3fb950';
          saveBtn.textContent = 'ğŸ’¾ Kaydet'; saveBtn.disabled = false;
          setTimeout(function() { _vswCloseEdit(); global.loadVSwitches(); }, 900);
        }).catch(function(e) {
          statusEl.textContent = 'âœ— ' + (e.message || String(e));
          statusEl.style.color = '#f87171';
          saveBtn.textContent = 'ğŸ’¾ Kaydet'; saveBtn.disabled = false;
        });
      };

      btnRow.appendChild(cancelBtn); btnRow.appendChild(saveBtn);
      box.appendChild(btnRow);

    }).catch(function(e) {
      box.removeChild(loader);
      var errEl = el('div', '', 'âœ— YÃ¼klenemedi: ' + (e.message || String(e)));
      errEl.style.cssText = 'color:#f87171;font-size:13px;text-align:center;padding:24px 0';
      box.appendChild(errEl);
    });
  };

  global.vswitchDelete = function(name) {
    if (!confirm(name + ' vSwitch silinsin mi? Bu iÅŸlem geri alÄ±namaz.')) return;
    api('/api/networks/' + encodeURIComponent(name), { method: 'DELETE' })
      .then(function() { global.loadVSwitches(); })
      .catch(function(e) { alert('Silme hatasÄ±: ' + e.message); });
  };

  global.vswitchAddPortGroup = function(switchName) {
    var pgName = prompt('Port Group adÄ± (VLAN etiketi iÃ§in "isim:100" formatÄ±):', switchName + '-pg1');
    if (!pgName) return;
    // Port group = libvirt'te ayrÄ± bir network definition olarak eklenebilir.
    // Åu an UI gÃ¶sterimi iÃ§in kaydediliyor; VLAN yalÄ±tÄ±mÄ± roadmap'te.
    var parts = pgName.split(':');
    var label = parts[0].trim();
    var vlan  = parts[1] ? parseInt(parts[1]) : null;
    var msg = 'Port Group "' + label + '"' + (vlan ? ' (VLAN ' + vlan + ')' : '') + ' ' + switchName + ' switch\'ine eklendi.';
    if (vlan) msg += '\nVLAN tabanlÄ± yalÄ±tÄ±m iÃ§in libvirt macvtap veya OVS gerekir â€” yakÄ±nda.';
    alert(msg);
  };

})(window);






