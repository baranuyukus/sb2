/**
 * SneakerBaker Bot Dashboard - Frontend v3
 * ==========================================
 * Auto-refresh via data_version, image proxy, enhanced UX
 */

// ─── STATE ──────────────────────────────────────────────────────
let products = [];
let currentFilter = 'all';
let searchTerm = '';
let currentPage = 1;
const PAGE_SIZE = 50;
let logCount = 0;
let editingProductId = null;
let pollingTimer = null;
let searchTimer = null;
let dataVersion = -1;       // Track server data version for auto-refresh
let isRefreshing = false;    // Prevent double refresh

// ─── INIT ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadSettings();
    startPolling();

    // View switching
    document.querySelectorAll('.nav-item[data-view]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.nav-item[data-view]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const view = btn.dataset.view;
            el('view-dashboard').style.display = view === 'dashboard' ? '' : 'none';
            el('view-settings').style.display = view === 'settings' ? '' : 'none';
            el('page-title').textContent = view === 'dashboard' ? 'Dashboard' : 'Ayarlar';
            
            if (window.innerWidth <= 768 && el('sidebar').classList.contains('open')) {
                toggleSidebar();
            }
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { closeModal(); closeLoginModal(); }
        if (e.key === 'Enter' && el('price-modal').classList.contains('active')) {
            confirmPriceUpdate();
        }
    });
});

// ─── MOBILE SIDEBAR ─────────────────────────────────────────────
function toggleSidebar() {
    const sidebar = el('sidebar');
    const backdrop = el('sidebar-backdrop');
    const isOpen = sidebar.classList.contains('open');
    if (isOpen) {
        sidebar.classList.remove('open');
        backdrop.classList.remove('active');
    } else {
        sidebar.classList.add('open');
        backdrop.classList.add('active');
    }
}

// ─── API ────────────────────────────────────────────────────────
async function api(url, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    try {
        const r = await fetch(url, opts);
        return await r.json();
    } catch (e) {
        console.error('API:', e);
        return { success: false, error: e.message };
    }
}

// ─── POLLING WITH AUTO-REFRESH ──────────────────────────────────
function startPolling() {
    pollingTimer = setInterval(async () => {
        const status = await api('/api/status');
        if (!status) return;
        updateStatusUI(status);
        loadLogs();

        // Auto-refresh products when data_version changes
        if (status.data_version !== undefined && status.data_version !== dataVersion) {
            if (dataVersion !== -1 && !isRefreshing) {
                // Data changed on server, silently refresh products
                console.log(`Data version changed: ${dataVersion} → ${status.data_version}`);
                await silentRefreshProducts();
            }
            dataVersion = status.data_version;
        }
    }, 4000);
}

// ─── STATUS UI ──────────────────────────────────────────────────
function updateStatusUI(d) {
    animateNumber('stat-total', d.total_products || 0);
    animateNumber('stat-auto', d.auto_enabled_count || 0);
    animateNumber('stat-undercut', d.needs_undercut_count || 0);
    
    // Tunnel & Profile mapping
    if (d.profile) { el('profile-badge').textContent = d.profile.toUpperCase(); }
    updateTunnelUI(d);

    el('stat-lastcheck').textContent = d.last_check || '—';

    // Bot status
    const dot = el('bot-dot'), txt = el('bot-status-text');
    if (d.bot_running) {
        dot.classList.add('running');
        txt.textContent = `Bot Çalışıyor (${d.bot_interval}s)`;
        txt.style.color = 'var(--success)';
        el('btn-start-bot').style.display = 'none';
        el('btn-stop-bot').style.display = '';
    } else {
        dot.classList.remove('running');
        txt.textContent = 'Bot Durmuş';
        txt.style.color = 'var(--text-muted)';
        el('btn-start-bot').style.display = '';
        el('btn-stop-bot').style.display = 'none';
    }

    // Login
    const lb = el('btn-login');
    if (d.logged_in) {
        lb.innerHTML = '✅ Bağlı';
        lb.className = 'btn btn-success'; lb.style.width = '100%';
    } else {
        lb.innerHTML = '🌐 Giriş Yap';
        lb.className = 'btn btn-primary'; lb.style.width = '100%';
    }

    if (d.total_products > 0 && products.length === 0) loadProducts();
}

function updateTunnelUI(d) {
    const localUrl = d.local_url || 'http://127.0.0.1:5050';
    const tunnelUrl = d.tunnel_url || '';
    const tunnelStatus = d.tunnel_status || 'idle';
    const tunnelError = d.tunnel_error || '';

    const localLink = el('local-url');
    localLink.href = localUrl;
    localLink.textContent = localUrl;

    const tunnelLink = el('tunnel-url');
    tunnelLink.href = tunnelUrl || '#';
    tunnelLink.textContent = tunnelUrl || 'Hazırlanıyor...';

    const statePill = el('tunnel-state-pill');
    statePill.className = `tunnel-state-pill ${tunnelStatus}`;

    if (tunnelStatus === 'running' && tunnelUrl) {
        statePill.textContent = 'Tunnel aktif';
    } else if (tunnelStatus === 'starting') {
        statePill.textContent = 'Tunnel başlatılıyor';
    } else if (tunnelStatus === 'error') {
        statePill.textContent = 'Tunnel hatası';
    } else if (tunnelStatus === 'stopped') {
        statePill.textContent = 'Tunnel kapalı';
    } else {
        statePill.textContent = 'Tunnel bekleniyor';
    }

    const errorBox = el('tunnel-error');
    if (tunnelStatus === 'error' && tunnelError) {
        errorBox.textContent = tunnelError;
    } else {
        errorBox.textContent = '';
    }

    const copyBtn = el('btn-copy-tunnel');
    copyBtn.disabled = !tunnelUrl;

    const startBtn = el('btn-start-tunnel');
    const stopBtn = el('btn-stop-tunnel');

    if (tunnelStatus === 'running' || tunnelStatus === 'starting') {
        startBtn.style.display = 'none';
        stopBtn.style.display = '';
    } else {
        startBtn.style.display = '';
        startBtn.textContent = tunnelStatus === 'error' ? 'Tekrar Dene' : 'Başlat';
        stopBtn.style.display = 'none';
    }
}

async function startTunnel() {
    const btn = el('btn-start-tunnel');
    btn.disabled = true;
    const response = await api('/api/tunnel/start', 'POST', { force: true });
    btn.disabled = false;
    if (response.success) {
        toast('🌐 Tunnel başlatılıyor...', 'info');
    } else {
        toast('❌ Tunnel başlatılamadı', 'error');
    }
    loadStatus();
}

async function stopTunnel() {
    const btn = el('btn-stop-tunnel');
    btn.disabled = true;
    const response = await api('/api/tunnel/stop', 'POST');
    btn.disabled = false;
    if (response.success) {
        toast('⛔ Tunnel durduruldu', 'info');
    } else {
        toast('❌ Tunnel durdurulamadı', 'error');
    }
    loadStatus();
}

function copyTunnelUrl() {
    const tunnelUrl = el('tunnel-url').href;
    if (!tunnelUrl || tunnelUrl.endsWith('#')) {
        toast('⚠️ Henüz kopyalanacak tunnel linki yok', 'error');
        return;
    }
    navigator.clipboard.writeText(tunnelUrl);
    toast('✅ Link kopyalandı!', 'success');
}

async function loadStatus() {
    const d = await api('/api/status');
    if (d) {
        updateStatusUI(d);
        if (d.data_version !== undefined) dataVersion = d.data_version;
    }
}

// Smooth number animation
function animateNumber(elementId, target) {
    const el_ = el(elementId);
    const current = parseInt(el_.textContent) || 0;
    if (current === target) return;
    el_.textContent = target;
    // Flash effect
    el_.style.transition = 'transform 0.2s, color 0.3s';
    el_.style.transform = 'scale(1.15)';
    setTimeout(() => { el_.style.transform = 'scale(1)'; }, 200);
}

// ─── PRODUCTS ───────────────────────────────────────────────────
async function loadProducts() {
    const d = await api('/api/products');
    if (d && d.products) {
        products = d.products;
        if (d.data_version !== undefined) dataVersion = d.data_version;
        currentPage = 1;
        renderAll();
    }
}

async function silentRefreshProducts() {
    // Refresh without UI loading indicator (background)
    isRefreshing = true;
    const d = await api('/api/products');
    if (d && d.products) {
        // Preserve checkbox states
        const checked = new Set(getSelectedIds());

        products = d.products;
        if (d.data_version !== undefined) dataVersion = d.data_version;
        renderAll();

        // Restore checkboxes
        if (checked.size > 0) {
            document.querySelectorAll('.product-checkbox').forEach(cb => {
                if (checked.has(cb.value)) cb.checked = true;
            });
        }

        // Show subtle indicator
        showRefreshIndicator();
    }
    isRefreshing = false;
}

function showRefreshIndicator() {
    const ind = el('refresh-indicator');
    if (ind) {
        ind.classList.add('visible');
        setTimeout(() => ind.classList.remove('visible'), 2000);
    }
}

async function refreshProducts() {
    const btn = el('btn-refresh');
    btn.classList.add('loading'); btn.disabled = true;

    const d = await api('/api/products/refresh', 'POST');
    if (d.success) {
        toast(`✅ ${d.count} ürün çekildi`, 'success');
        await loadProducts();
    } else {
        toast('❌ Ürünler çekilemedi', 'error');
    }

    btn.classList.remove('loading'); btn.disabled = false;
    btn.innerHTML = '🔄 Yenile';
    loadStatus();
}

// ─── FILTERING & SEARCH ─────────────────────────────────────────
function handleSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        searchTerm = el('search-input').value.toLowerCase().trim();
        currentPage = 1;
        renderAll();
    }, 200);
}

function setFilter(filter, btn) {
    currentFilter = filter;
    currentPage = 1;
    document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    renderAll();
}

function getFilteredProducts() {
    let f = [...products];
    if (searchTerm) {
        f = f.filter(p =>
            p.title.toLowerCase().includes(searchTerm) ||
            p.size.toLowerCase().includes(searchTerm) ||
            p.id.includes(searchTerm)
        );
    }
    if (currentFilter === 'undercut') f = f.filter(p => p.current_price > p.min_price && p.min_price > 0);
    else if (currentFilter === 'cheapest') f = f.filter(p => p.current_price <= p.min_price || p.min_price === 0);
    else if (currentFilter === 'auto') f = f.filter(p => p.auto_enabled);
    return f;
}

function updateFilterCounts() {
    el('fc-all').textContent = products.length;
    el('fc-undercut').textContent = products.filter(p => p.current_price > p.min_price && p.min_price > 0).length;
    el('fc-cheapest').textContent = products.filter(p => p.current_price <= p.min_price || p.min_price === 0).length;
    el('fc-auto').textContent = products.filter(p => p.auto_enabled).length;
}

function renderAll() {
    updateFilterCounts();
    renderProducts();
    renderPagination();
}

function formatPrice(n) {
    if (!n) return '—';
    return '₺' + n.toLocaleString('tr-TR');
}

function renderProducts() {
    const tbody = el('product-tbody');
    const filtered = getFilteredProducts();
    const totalPages = Math.ceil(filtered.length / PAGE_SIZE) || 1;
    if (currentPage > totalPages) currentPage = totalPages;

    const start = (currentPage - 1) * PAGE_SIZE;
    const pageItems = filtered.slice(start, start + PAGE_SIZE);

    el('toolbar-info').textContent = filtered.length !== products.length
        ? `${filtered.length} / ${products.length} ürün`
        : `${products.length} ürün`;

    if (pageItems.length === 0) {
        tbody.innerHTML = `<tr><td colspan="11">
            <div class="empty-state">
                <div class="empty-icon">${products.length === 0 ? '👟' : '🔍'}</div>
                <h3>${products.length === 0 ? 'Henüz ürün yok' : 'Sonuç bulunamadı'}</h3>
                <p>${products.length === 0 ? 'Giriş yapın ve ürünleri yenileyin.' : 'Filtreyi veya aramayı değiştirin.'}</p>
            </div></td></tr>`;
        return;
    }

    tbody.innerHTML = pageItems.map(p => {
        const isUnder = p.current_price > p.min_price && p.min_price > 0;
        const diff = isUnder ? p.current_price - p.min_price : 0;
        const badge = isUnder
            ? `<span class="badge badge-danger">⬇ KIRMA</span><div class="badge-diff">+₺${diff.toLocaleString('tr-TR')}</div>`
            : '<span class="badge badge-success">✓ EN UCUZ</span>';

        // Image with proxy
        const imgUrl = p.image || '';
        const img = imgUrl
            ? `<img src="${imgUrl}" class="product-thumb" alt="" loading="lazy" onerror="this.onerror=null;this.src='';this.style.display='none';this.nextElementSibling.style.display='flex'"><div class="product-thumb thumb-fallback" style="display:none">👟</div>`
            : '<div class="product-thumb thumb-fallback">👟</div>';

        return `
        <tr data-id="${p.id}" class="${isUnder ? 'row-undercut' : ''}">
            <td data-label="Seç"><input type="checkbox" class="product-checkbox" value="${p.id}"></td>
            <td data-label="Görsel">${img}</td>
            <td data-label="Ürün"><div class="product-name" title="${p.title}">${p.title}</div></td>
            <td data-label="Beden"><span class="product-size">${p.size}</span></td>
            <td data-label="Fiyatın" class="price-cell price-current">
                <span class="price-editable" onclick="openPriceModal('${p.id}')" title="Tıkla → düzenle">${formatPrice(p.current_price)}</span>
            </td>
            <td data-label="Maliyet" class="price-cell price-cost">${formatPrice(p.cost_price)}</td>
            <td data-label="En Ucuz" class="price-cell price-min">${formatPrice(p.min_price)}</td>
            <td data-label="Auto" style="text-align:center">
                <label class="toggle">
                    <input type="checkbox" ${p.auto_enabled ? 'checked' : ''} onchange="toggleAuto('${p.id}', this.checked)">
                    <span class="toggle-slider"></span>
                </label>
            </td>
            <td data-label="Min Fiyat">
                <input type="number" class="inline-input" value="${p.auto_min_price || ''}"
                    placeholder="—" min="0"
                    onchange="setMinPrice('${p.id}', this.value)"
                    onfocus="this.select()">
            </td>
            <td data-label="Düzenle" style="text-align:center">
                <button class="btn btn-sm btn-icon btn-ghost" onclick="openPriceModal('${p.id}')" title="Fiyat Düzenle">✏️</button>
            </td>
            <td data-label="Durum">${badge}</td>
        </tr>`;
    }).join('');
}

// ─── PAGINATION ─────────────────────────────────────────────────
function renderPagination() {
    const filtered = getFilteredProducts();
    const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
    const pg = el('pagination');

    if (totalPages <= 1) { pg.innerHTML = ''; return; }

    let html = `<button class="page-btn" onclick="goPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>‹</button>`;

    const maxV = 7;
    let sP = Math.max(1, currentPage - Math.floor(maxV / 2));
    let eP = Math.min(totalPages, sP + maxV - 1);
    if (eP - sP < maxV - 1) sP = Math.max(1, eP - maxV + 1);

    if (sP > 1) { html += `<button class="page-btn" onclick="goPage(1)">1</button>`; if (sP > 2) html += `<span class="page-info">…</span>`; }
    for (let i = sP; i <= eP; i++) html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" onclick="goPage(${i})">${i}</button>`;
    if (eP < totalPages) { if (eP < totalPages - 1) html += `<span class="page-info">…</span>`; html += `<button class="page-btn" onclick="goPage(${totalPages})">${totalPages}</button>`; }

    html += `<button class="page-btn" onclick="goPage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}>›</button>`;
    html += `<span class="page-info">${(currentPage-1)*PAGE_SIZE+1}–${Math.min(currentPage*PAGE_SIZE, filtered.length)} / ${filtered.length}</span>`;
    pg.innerHTML = html;
}

function goPage(p) {
    const tp = Math.ceil(getFilteredProducts().length / PAGE_SIZE);
    if (p < 1 || p > tp) return;
    currentPage = p;
    renderProducts();
    renderPagination();
    el('product-table').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ─── ROW ANIMATIONS ─────────────────────────────────────────────
function flashRow(id, type) {
    const r = document.querySelector(`tr[data-id="${id}"]`);
    if (!r) return;
    r.classList.remove('updating', 'update-success', 'update-error');
    void r.offsetWidth; // force reflow
    r.classList.add(type);
    setTimeout(() => r.classList.remove(type), 1500);
}

// ─── PRODUCT ACTIONS ────────────────────────────────────────────
async function toggleAuto(productId, enabled) {
    await api(`/api/products/${productId}/auto`, 'POST', { enabled });
    const p = products.find(x => x.id === productId);
    if (p) p.auto_enabled = enabled;
    updateFilterCounts();
    loadStatus();
    flashRow(productId, enabled ? 'update-success' : 'updating');
    toast(`${enabled ? '🟢 Auto açıldı' : '🔴 Auto kapatıldı'}`, 'info');
}

async function setMinPrice(productId, value) {
    const v = parseInt(value) || 0;
    await api(`/api/products/${productId}/min-price`, 'POST', { min_price: v });
    const p = products.find(x => x.id === productId);
    if (p) p.auto_min_price = v;
    flashRow(productId, 'updating');
}

// ─── PRICE MODAL ────────────────────────────────────────────────
function openPriceModal(productId) {
    editingProductId = productId;
    const p = products.find(x => x.id === productId);
    if (!p) return;

    el('modal-product-name').textContent = p.title;
    
    // Populate info table
    el('modal-info-size').textContent = p.size;
    el('modal-info-current').textContent = formatPrice(p.current_price);
    el('modal-info-cost').textContent = formatPrice(p.cost_price);
    el('modal-info-cheapest').textContent = formatPrice(p.min_price);

    // Populate inputs
    el('modal-price-input').value = p.current_price;
    el('modal-min-price-input').value = p.auto_min_price || '';

    // Hint buttons for current price
    const hints = [];
    if (p.min_price > 0 && p.min_price < p.current_price) {
        hints.push({ label: `En ucuz - 1 → ${formatPrice(p.min_price - 1)}`, value: p.min_price - 1 });
        hints.push({ label: `En ucuz - 10 → ${formatPrice(p.min_price - 10)}`, value: p.min_price - 10 });
        hints.push({ label: `En ucuz - 50 → ${formatPrice(p.min_price - 50)}`, value: p.min_price - 50 });
    }
    if (p.min_price > 0) {
        hints.push({ label: `En ucuz → ${formatPrice(p.min_price)}`, value: p.min_price });
    }
    
    el('modal-hints').innerHTML = hints.map(h =>
        `<button class="btn btn-sm btn-ghost" style="font-size:10px; border:1px solid var(--border)" onclick="el('modal-price-input').value=${h.value}">${h.label}</button>`
    ).join('');

    el('price-modal').classList.add('active');
    setTimeout(() => { el('modal-price-input').focus(); el('modal-price-input').select(); }, 200);
}

function closeModal() {
    el('price-modal').classList.remove('active');
    editingProductId = null;
}

async function confirmPriceUpdate() {
    if (!editingProductId) return;
    
    const p = products.find(x => x.id === editingProductId);
    if (!p) return;

    const newPriceStr = el('modal-price-input').value;
    const newMinStr = el('modal-min-price-input').value;
    
    const newPrice = newPriceStr ? parseInt(newPriceStr) : null;
    const newMinPrice = newMinStr ? parseInt(newMinStr) : 0;

    const pid = editingProductId;
    const btn = el('btn-confirm-price');
    btn.classList.add('loading'); btn.disabled = true;
    
    closeModal();
    toast(`⏳ Kaydediliyor...`, 'info');
    flashRow(pid, 'updating');

    let successMessage = "✅ Güncellendi";
    let failed = false;

    // 1. Min Price update
    if (newMinPrice !== (p.auto_min_price || 0)) {
        const res = await api(`/api/products/${pid}/min-price`, 'POST', { min_price: newMinPrice });
        if (res && res.success) {
            p.auto_min_price = newMinPrice;
        } else {
            failed = true;
        }
    }

    // 2. Current Price update
    if (newPrice !== null && newPrice > 0 && newPrice !== p.current_price) {
        const res = await api(`/api/products/${pid}/price`, 'POST', { price: newPrice });
        if (res && res.success) {
            p.current_price = newPrice;
        } else {
            failed = true;
        }
    }

    btn.classList.remove('loading'); btn.disabled = false;
    btn.innerHTML = '✓ Kaydet';

    if (!failed) {
        toast(`✅ Kaydedildi`, 'success');
        renderAll();
        flashRow(pid, 'update-success');
    } else {
        toast(`❌ Hata oluştu`, 'error');
        flashRow(pid, 'update-error');
    }
}

// ─── BULK ACTIONS ───────────────────────────────────────────────
function getSelectedIds() {
    return Array.from(document.querySelectorAll('.product-checkbox:checked')).map(c => c.value);
}

function toggleSelectAll(cb) {
    document.querySelectorAll('.product-checkbox').forEach(c => c.checked = cb.checked);
}

async function bulkAutoEnable() {
    const ids = getSelectedIds();
    if (!ids.length) { toast('⚠️ Önce ürün seçin', 'error'); return; }
    await api('/api/products/bulk-auto', 'POST', { ids, enabled: true });
    ids.forEach(id => { const p = products.find(x => x.id === id); if (p) p.auto_enabled = true; });
    renderAll(); loadStatus();
    toast(`✅ ${ids.length} üründe auto açıldı`, 'success');
}

async function bulkAutoDisable() {
    const ids = getSelectedIds();
    if (!ids.length) { toast('⚠️ Önce ürün seçin', 'error'); return; }
    await api('/api/products/bulk-auto', 'POST', { ids, enabled: false });
    ids.forEach(id => { const p = products.find(x => x.id === id); if (p) p.auto_enabled = false; });
    renderAll(); loadStatus();
    toast(`🔴 ${ids.length} üründe auto kapatıldı`, 'info');
}

// ─── LOGIN ──────────────────────────────────────────────────────
function handleLogin() { el('login-modal').classList.add('active'); }
function closeLoginModal() { el('login-modal').classList.remove('active'); }

async function autoLogin() {
    const email = el('login-email').value.trim();
    const password = el('login-password').value;
    
    if (!email || !password) {
        toast('⚠️ Lütfen email ve şifre girin', 'error');
        return;
    }

    const btn = el('btn-auto-login');
    const txt = el('login-status-text');
    
    btn.classList.add('loading');
    btn.disabled = true;
    txt.textContent = '⏳ Otomatik giriş yapılıyor, lütfen bekleyin. Bu işlem 10-15 saniye sürebilir...';
    txt.style.color = 'var(--warning)';

    const r = await api('/api/bot/auto-login', 'POST', { email, password });
    
    btn.classList.remove('loading');
    btn.disabled = false;
    
    if (r.success) {
        toast('✅ Otomatik giriş başarılı!', 'success');
        closeLoginModal(); 
        loadStatus();
        txt.textContent = 'Botun SneakerBaker\'a giriş yapabilmesi için bilgilerinizi girin.';
        txt.style.color = '';
    } else {
        toast('❌ ' + (r.error || 'Giriş yapılamadı'), 'error');
        txt.textContent = '❌ Giriş hatası: ' + (r.error || 'Bilgileri kontrol edip tekrar deneyin.');
        txt.style.color = 'var(--danger)';
    }
}

async function openChrome() {
    const btn = el('btn-open-chrome');
    btn.classList.add('loading'); btn.disabled = true;
    const r = await api('/api/bot/login', 'POST');
    btn.classList.remove('loading');
    if (r.success) {
        el('login-status-text').textContent = '✅ Chrome açıldı! Giriş yapıp /sat/urunler sayfasına gidin.';
        el('login-status-text').style.color = 'var(--success)';
        btn.style.display = 'none';
        el('btn-auto-login').style.display = 'none';
        el('login-email').style.display = 'none';
        el('login-password').style.display = 'none';
        el('btn-confirm-login').style.display = '';
    } else {
        toast('❌ Chrome açılamadı', 'error');
        btn.disabled = false;
    }
}

async function confirmLogin() {
    const btn = el('btn-confirm-login');
    btn.classList.add('loading'); btn.disabled = true;
    const r = await api('/api/bot/confirm-login', 'POST');
    btn.classList.remove('loading');
    if (r.success) {
        toast('✅ Giriş başarılı!', 'success');
        closeLoginModal(); loadStatus();
        el('btn-open-chrome').style.display = ''; el('btn-open-chrome').disabled = false; el('btn-open-chrome').innerHTML = '🌐 Tarayıcıyı Aç';
        el('btn-confirm-login').style.display = 'none'; el('btn-confirm-login').disabled = false; el('btn-confirm-login').innerHTML = '✓ Giriş Tamamlandı';
        el('login-status-text').textContent = 'Chrome tarayıcı açılacak. SneakerBaker\'a giriş yapın.'; el('login-status-text').style.color = '';
    } else {
        toast('❌ Doğrulanamadı', 'error');
        btn.disabled = false; btn.innerHTML = '✓ Giriş Tamamlandı';
    }
}

// ─── BOT CONTROL ────────────────────────────────────────────────
async function startBot() {
    const interval = parseInt(el('interval-select').value);
    const btn = el('btn-start-bot');
    btn.classList.add('loading'); btn.disabled = true;
    await api('/api/bot/start', 'POST', { interval });
    btn.classList.remove('loading'); btn.disabled = false; btn.innerHTML = '▶ Başlat';
    toast('🚀 Bot başlatıldı!', 'success');
    loadStatus();
}

async function stopBot() {
    const btn = el('btn-stop-bot');
    btn.classList.add('loading'); btn.disabled = true;
    await api('/api/bot/stop', 'POST');
    btn.classList.remove('loading'); btn.disabled = false; btn.innerHTML = '⏹ Durdur';
    toast('⏹ Bot durduruldu', 'info');
    loadStatus();
}

// ─── SETTINGS ───────────────────────────────────────────────────
async function loadSettings() {
    const d = await api('/api/settings');
    if (d) {
        el('setting-undercut').value = d.undercut_amount || 1;
        el('setting-profit').value = d.min_profit_margin || 500;
        el('setting-interval').value = d.bot_interval || 300;
        const sel = el('interval-select');
        for (let o of sel.options) if (o.value === String(d.bot_interval || 300)) { o.selected = true; break; }
    }
}

async function saveSettings() {
    const data = {
        undercut_amount: parseInt(el('setting-undercut').value) || 1,
        min_profit_margin: parseInt(el('setting-profit').value) || 500,
        bot_interval: parseInt(el('setting-interval').value) || 300,
    };
    await api('/api/settings', 'POST', data);
    toast('✅ Ayarlar kaydedildi', 'success');
    const sel = el('interval-select');
    for (let o of sel.options) if (o.value === String(data.bot_interval)) { o.selected = true; break; }
}

// ─── LOGS ───────────────────────────────────────────────────────
function toggleLogs() {
    const p = el('logs-panel');
    p.classList.toggle('open');
    if (p.classList.contains('open')) loadLogs();
}
el('btn-toggle-logs').addEventListener('click', toggleLogs);

async function loadLogs() {
    if (!el('logs-panel').classList.contains('open')) return;
    const d = await api(`/api/logs?since=${logCount}`);
    if (d && d.logs && d.logs.length > 0) {
        const body = el('logs-body');
        d.logs.forEach(l => {
            const div = document.createElement('div');
            div.className = `log-entry ${l.level}`;
            div.innerHTML = `<span class="log-time">${l.time}</span>${l.message}`;
            body.appendChild(div);
        });
        logCount = d.total;
        body.scrollTop = body.scrollHeight;
    }
}

// ─── TOAST ──────────────────────────────────────────────────────
function toast(msg, type = 'info') {
    const c = el('toast-container');
    const d = document.createElement('div');
    d.className = `toast toast-${type}`;
    d.textContent = msg;
    c.appendChild(d);
    setTimeout(() => { if (d.parentNode) d.remove(); }, 4000);
}

// ─── UTIL ───────────────────────────────────────────────────────
function el(id) { return document.getElementById(id); }
