/**
 * Admin Dashboard Module v2.0
 *
 * Features: sessions table, phrase management (CRUD), audit log,
 * Chart.js visualizations, CSV export, and detail modal.
 */

(() => {
    'use strict';

    const API_BASE = "https://q2t19vyp9a.execute-api.ap-southeast-2.amazonaws.com/prod";

    // ── Auth Guard ────────────────────────────────────────────
    const token = sessionStorage.getItem('keystroke_admin_token');
    const adminUser = sessionStorage.getItem('keystroke_admin_user');
    if (!token) { window.location.href = 'admin.html'; return; }
    document.getElementById('admin-user').textContent = adminUser || 'Admin';

    // ── API Helper ────────────────────────────────────────────
    async function apiFetch(path, options = {}) {
        const { method = 'GET', body, params = {} } = options;
        const url = new URL(`${API_BASE}${path}`);
        Object.entries(params).forEach(([k, v]) => { if (v) url.searchParams.set(k, v); });

        const fetchOpts = {
            method,
            headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        };
        if (body) fetchOpts.body = JSON.stringify(body);

        const res = await fetch(url.toString(), fetchOpts);
        if (res.status === 401) {
            sessionStorage.removeItem('keystroke_admin_token');
            window.location.href = 'admin.html';
            return null;
        }
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `API error: ${res.status}`);
        }
        return res.json();
    }

    // ── State ─────────────────────────────────────────────────
    let allSessions = [];
    let allPhrases = [];
    let showInactive = false;
    let charts = {};

    // ── DOM refs ──────────────────────────────────────────────
    const tbody = document.getElementById('sessions-tbody');
    const tableCount = document.getElementById('table-count');
    const modal = document.getElementById('detail-modal');
    const modalBody = document.getElementById('modal-body');
    const modalTitle = document.getElementById('modal-title');
    const editModal = document.getElementById('edit-phrase-modal');

    // ══════════════════════════════════════════════════════════
    // TABS
    // ══════════════════════════════════════════════════════════
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(btn.dataset.tab).classList.add('active');
        });
    });

    // ══════════════════════════════════════════════════════════
    // LOGOUT
    // ══════════════════════════════════════════════════════════
    document.getElementById('logout-btn').addEventListener('click', () => {
        sessionStorage.removeItem('keystroke_admin_token');
        sessionStorage.removeItem('keystroke_admin_user');
        window.location.href = 'admin.html';
    });

    // ══════════════════════════════════════════════════════════
    // DASHBOARD STATS
    // ══════════════════════════════════════════════════════════
    function timeAgo(dateStr) {
        const now = new Date();
        const past = new Date(dateStr);
        const diffMs = now - past;
        const diffSec = Math.floor(diffMs / 1000);
        if (diffSec < 60) return 'Just now';
        const diffMin = Math.floor(diffSec / 60);
        if (diffMin < 60) return `${diffMin} min ago`;
        const diffHr = Math.floor(diffMin / 60);
        if (diffHr < 24) return `${diffHr} hr ago`;
        const diffDay = Math.floor(diffHr / 24);
        if (diffDay < 7) return `${diffDay}d ago`;
        return past.toLocaleDateString();
    }

    async function loadDashboard() {
        try {
            const stats = await apiFetch('/api/admin/dashboard');
            if (!stats) return;
            document.getElementById('stat-users').textContent = stats.total_users;
            document.getElementById('stat-sessions').textContent = stats.total_sessions;
            document.getElementById('stat-attempts').textContent = stats.total_attempts;
            if (stats.latest_submissions?.length > 0) {
                document.getElementById('stat-latest').textContent = timeAgo(stats.latest_submissions[0].timestamp);
                document.getElementById('stat-latest').title = new Date(stats.latest_submissions[0].timestamp).toLocaleString();
            } else {
                document.getElementById('stat-latest').textContent = 'N/A';
            }
        } catch (e) { console.error('Dashboard load error:', e); }
    }

    // ══════════════════════════════════════════════════════════
    // SESSIONS
    // ══════════════════════════════════════════════════════════
    async function loadSessions(filters = {}) {
        try {
            tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted" style="padding:2rem;">Loading…</td></tr>';
            const data = await apiFetch('/api/admin/sessions', { params: filters });
            if (!data) return;
            allSessions = data.sessions || [];
            // Ensure newest-first sort (client-side fallback)
            allSessions.sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));
            renderTable(allSessions);
            renderCharts(allSessions);
        } catch (e) {
            console.error('Sessions load error:', e);
            tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted" style="padding:2rem;">Error loading data.</td></tr>';
        }
    }

    function renderTable(sessions) {
        tableCount.textContent = sessions.length;
        if (sessions.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted" style="padding:2rem;">No sessions found.</td></tr>';
            return;
        }
        tbody.innerHTML = sessions.map(s => {
            const f = s.features || {};
            const core = f.core_features || {};
            const wpm = core.typing_speed_wpm;
            const dur = core.total_typing_duration_ms;
            const ts = s.timestamp ? timeAgo(s.timestamp) : '—';
            const tsTitle = s.timestamp ? new Date(s.timestamp).toLocaleString() : '';
            const sortKey = `${s.session_id}#${s.attempt_number}#${s.phrase_id}`;
            return `<tr>
                <td><strong>${esc(s.username)}</strong></td>
                <td style="font-family:'JetBrains Mono',monospace;font-size:0.75rem;">${esc((s.session_id || '').substring(0, 8))}…</td>
                <td>${s.attempt_number || '—'}</td>
                <td><span class="badge badge--success">${esc(s.phrase_id || '—')}</span></td>
                <td>${s.phrase_version || 1}</td>
                <td>${typeof wpm === 'number' ? wpm.toFixed(1) : '—'}</td>
                <td>${typeof dur === 'number' ? dur.toFixed(0) : '—'}</td>
                <td>${s.backspace_count || 0}</td>
                <td style="font-size:0.78rem;" title="${tsTitle}">${ts}</td>
                <td><button class="btn btn--secondary btn--sm detail-btn" data-username="${escA(s.username)}" data-sortkey="${escA(sortKey)}">View</button></td>
            </tr>`;
        }).join('');

        document.querySelectorAll('.detail-btn').forEach(btn => {
            btn.addEventListener('click', () => openDetail(btn.dataset.username, btn.dataset.sortkey));
        });
    }

    // Detail modal
    async function openDetail(username, sortKey) {
        modal.classList.add('active');
        modalTitle.textContent = `${username} — ${sortKey.split('#')[2] || ''}`;
        modalBody.innerHTML = '<p class="text-muted">Loading…</p>';
        try {
            const record = await apiFetch(`/api/admin/session/${encodeURIComponent(username)}/${encodeURIComponent(sortKey)}`);
            if (!record) return;
            modalBody.innerHTML = renderFeatureGrid(record.features || {});
        } catch (e) { modalBody.innerHTML = `<p class="status status--error">Error: ${e.message}</p>`; }
    }

    function renderFeatureGrid(features) {
        const sections = [
            { title: 'Core', data: features.core_features },
            { title: 'Variability', data: features.variability_features },
            { title: 'Distribution', data: features.distribution_features },
            { title: 'Digraph', data: features.digraph_features },
            { title: 'Pause', data: features.pause_features },
            { title: 'Error', data: features.error_features },
            { title: 'Sequence', data: features.sequence_features },
        ];
        return '<div class="feature-grid">' + sections.map(s => {
            if (!s.data) return '';
            const items = Object.entries(s.data).map(([k, v]) => {
                let d = v;
                if (Array.isArray(v)) d = v.length > 5 ? `[${v.slice(0, 5).map(x => typeof x === 'number' ? x.toFixed(2) : x).join(', ')}… +${v.length - 5}]` : `[${v.map(x => typeof x === 'number' ? x.toFixed(2) : x).join(', ')}]`;
                else if (typeof v === 'object' && v !== null) { const e = Object.entries(v); d = e.length > 3 ? `{${e.slice(0, 3).map(([a, b]) => `${a}:${typeof b === 'number' ? b.toFixed(2) : b}`).join(', ')}… +${e.length - 3}}` : `{${e.map(([a, b]) => `${a}:${typeof b === 'number' ? b.toFixed(2) : b}`).join(', ')}}`; }
                else if (typeof v === 'number') d = v.toFixed(4);
                return `<div class="feature-item"><span class="feature-item__label">${fmtLabel(k)}</span><span class="feature-item__value">${esc(String(d))}</span></div>`;
            }).join('');
            return `<div class="feature-section"><div class="feature-section__title">${s.title}</div>${items}</div>`;
        }).join('') + '</div>';
    }

    document.getElementById('modal-close').addEventListener('click', () => modal.classList.remove('active'));
    modal.addEventListener('click', e => { if (e.target === modal) modal.classList.remove('active'); });

    // Filters
    document.getElementById('apply-filter-btn').addEventListener('click', () => {
        loadSessions({
            username: document.getElementById('filter-username').value.trim() || undefined,
            session_id: document.getElementById('filter-session').value.trim() || undefined,
            phrase_id: document.getElementById('filter-phrase').value || undefined,
            date_from: document.getElementById('filter-date-from').value || undefined,
            date_to: document.getElementById('filter-date-to').value || undefined,
        });
    });
    document.getElementById('clear-filter-btn').addEventListener('click', () => {
        ['filter-username', 'filter-session', 'filter-date-from', 'filter-date-to'].forEach(id => document.getElementById(id).value = '');
        document.getElementById('filter-phrase').value = '';
        loadSessions();
    });

    // CSV Export
    document.getElementById('export-all-btn').addEventListener('click', () => exportCSV());
    document.getElementById('export-filtered-btn').addEventListener('click', () => exportCSV(true));

    async function exportCSV(useFilters = false) {
        try {
            const params = {};
            if (useFilters) {
                params.username = document.getElementById('filter-username').value.trim() || undefined;
                params.session_id = document.getElementById('filter-session').value.trim() || undefined;
                params.phrase_id = document.getElementById('filter-phrase').value || undefined;
                params.date_from = document.getElementById('filter-date-from').value || undefined;
                params.date_to = document.getElementById('filter-date-to').value || undefined;
            }
            const url = new URL(`${API_BASE}/api/admin/export`);
            Object.entries(params).forEach(([k, v]) => { if (v) url.searchParams.set(k, v); });
            const res = await fetch(url.toString(), { headers: { 'Authorization': `Bearer ${token}` } });
            if (!res.ok) throw new Error(`Export failed: ${res.status}`);
            const blob = await res.blob();
            const a = document.createElement('a');
            a.href = window.URL.createObjectURL(blob);
            a.target = '_blank';
            a.download = `keystroke_export_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.csv`;
            a.style.display = 'none';
            document.body.appendChild(a);
            a.click();

            setTimeout(() => {
                document.body.removeChild(a);
                window.URL.revokeObjectURL(a.href);
            }, 100);
        } catch (e) { console.error('Export error:', e); alert('Export failed: ' + e.message); }
    }

    // ══════════════════════════════════════════════════════════
    // PHRASE MANAGEMENT
    // ══════════════════════════════════════════════════════════

    async function loadPhrases() {
        try {
            const data = await apiFetch('/api/admin/phrases', { params: { include_inactive: showInactive } });
            if (!data) return;
            allPhrases = data.phrases || [];
            renderPhraseList(allPhrases);
            populatePhraseFilter(allPhrases);
        } catch (e) {
            console.error('Phrase load error:', e);
            document.getElementById('phrase-list').innerHTML = '<p class="status status--error">Failed to load phrases.</p>';
        }
    }

    function renderPhraseList(phrases) {
        const container = document.getElementById('phrase-list');
        if (phrases.length === 0) {
            container.innerHTML = '<p class="text-muted text-center" style="padding:2rem;">No phrases found. Click "Seed Defaults" to add initial phrases.</p>';
            return;
        }
        container.innerHTML = phrases.map(p => `
            <div class="phrase-card ${p.active === false ? 'inactive' : ''}" data-id="${escA(p.phrase_id)}">
                <div class="phrase-card__order">#${p.order || '?'}</div>
                <div class="phrase-card__text">${esc(p.text)}</div>
                <div class="phrase-card__meta">
                    <span class="badge ${p.active !== false ? 'badge--success' : 'badge--error'}">${p.active !== false ? 'Active' : 'Inactive'}</span>
                    <span>v${p.version || 1}</span>
                    <span>${esc(p.category || '')}</span>
                    <span>×${p.max_attempts || 1} attempts</span>
                </div>
                <div class="phrase-card__actions">
                    <button class="btn btn--secondary btn--sm edit-phrase-btn" data-id="${escA(p.phrase_id)}">✏️</button>
                    <button class="btn btn--secondary btn--sm toggle-phrase-btn" data-id="${escA(p.phrase_id)}" data-active="${p.active !== false}">${p.active !== false ? '⏸' : '▶'}</button>
                    <button class="btn btn--secondary btn--sm delete-phrase-btn" data-id="${escA(p.phrase_id)}">🗑</button>
                </div>
            </div>
        `).join('');

        // Wire up buttons
        container.querySelectorAll('.edit-phrase-btn').forEach(btn => btn.addEventListener('click', () => openEditModal(btn.dataset.id)));
        container.querySelectorAll('.toggle-phrase-btn').forEach(btn => btn.addEventListener('click', () => togglePhrase(btn.dataset.id, btn.dataset.active === 'true')));
        container.querySelectorAll('.delete-phrase-btn').forEach(btn => btn.addEventListener('click', () => deletePhrase(btn.dataset.id)));
    }

    function populatePhraseFilter(phrases) {
        const sel = document.getElementById('filter-phrase');
        const current = sel.value;
        sel.innerHTML = '<option value="">All Phrases</option>' +
            phrases.map(p => `<option value="${escA(p.phrase_id)}">${esc(p.phrase_id)} (${esc(p.text)})</option>`).join('');
        sel.value = current;
    }

    // Add phrase
    document.getElementById('add-phrase-btn').addEventListener('click', async () => {
        const text = document.getElementById('new-phrase-text').value.trim();
        if (!text) return alert('Please enter phrase text.');
        try {
            await apiFetch('/api/admin/phrases', {
                method: 'POST',
                body: {
                    text,
                    category: document.getElementById('new-phrase-category').value,
                    order: parseInt(document.getElementById('new-phrase-order').value) || 10,
                    max_attempts: parseInt(document.getElementById('new-phrase-attempts').value) || 1,
                },
            });
            document.getElementById('new-phrase-text').value = '';
            loadPhrases();
            loadAuditLog();
        } catch (e) { alert('Error: ' + e.message); }
    });

    // Toggle active/inactive
    async function togglePhrase(phraseId, isActive) {
        try {
            await apiFetch(`/api/admin/phrases/${encodeURIComponent(phraseId)}`, {
                method: 'PUT',
                body: { active: !isActive },
            });
            loadPhrases();
            loadAuditLog();
        } catch (e) { alert('Error: ' + e.message); }
    }

    // Delete phrase
    async function deletePhrase(phraseId) {
        if (!confirm(`Delete phrase "${phraseId}"? Existing data will be preserved.`)) return;
        try {
            await apiFetch(`/api/admin/phrases/${encodeURIComponent(phraseId)}`, { method: 'DELETE' });
            loadPhrases();
            loadAuditLog();
        } catch (e) { alert('Error: ' + e.message); }
    }

    // Seed defaults
    document.getElementById('seed-phrases-btn').addEventListener('click', async () => {
        try {
            const result = await apiFetch('/api/admin/phrases/seed', { method: 'POST' });
            alert(result.count > 0 ? `Seeded ${result.count} default phrases.` : 'Table already has phrases — no seeding needed.');
            loadPhrases();
        } catch (e) { alert('Error: ' + e.message); }
    });

    // Show/hide inactive
    document.getElementById('toggle-inactive-btn').addEventListener('click', () => {
        showInactive = !showInactive;
        document.getElementById('toggle-inactive-btn').textContent = showInactive ? 'Hide Inactive' : 'Show Inactive';
        loadPhrases();
    });

    // ── Edit Modal ────────────────────────────────────────────
    function openEditModal(phraseId) {
        const p = allPhrases.find(x => x.phrase_id === phraseId);
        if (!p) return;
        document.getElementById('edit-phrase-id').value = p.phrase_id;
        document.getElementById('edit-phrase-text').value = p.text || '';
        document.getElementById('edit-phrase-category').value = p.category || 'password-style';
        document.getElementById('edit-phrase-order').value = p.order || 1;
        document.getElementById('edit-phrase-attempts').value = p.max_attempts || 1;
        document.getElementById('edit-phrase-active').checked = p.active !== false;
        document.getElementById('edit-status').innerHTML = '';
        editModal.classList.add('active');
    }

    document.getElementById('save-phrase-btn').addEventListener('click', async () => {
        const phraseId = document.getElementById('edit-phrase-id').value;
        const statusEl = document.getElementById('edit-status');
        try {
            await apiFetch(`/api/admin/phrases/${encodeURIComponent(phraseId)}`, {
                method: 'PUT',
                body: {
                    text: document.getElementById('edit-phrase-text').value.trim() || undefined,
                    category: document.getElementById('edit-phrase-category').value,
                    order: parseInt(document.getElementById('edit-phrase-order').value),
                    max_attempts: parseInt(document.getElementById('edit-phrase-attempts').value),
                    active: document.getElementById('edit-phrase-active').checked,
                },
            });
            statusEl.innerHTML = '<div class="status status--success">✓ Saved. Version bumped if text changed.</div>';
            loadPhrases();
            loadAuditLog();
            setTimeout(() => editModal.classList.remove('active'), 800);
        } catch (e) {
            statusEl.innerHTML = `<div class="status status--error">Error: ${e.message}</div>`;
        }
    });

    document.getElementById('edit-modal-close').addEventListener('click', () => editModal.classList.remove('active'));
    editModal.addEventListener('click', e => { if (e.target === editModal) editModal.classList.remove('active'); });

    // ══════════════════════════════════════════════════════════
    // AUDIT LOG
    // ══════════════════════════════════════════════════════════

    async function loadAuditLog() {
        try {
            const data = await apiFetch('/api/admin/audit-log', { params: { limit: '30' } });
            if (!data) return;
            const logs = data.logs || [];
            const container = document.getElementById('audit-log-list');
            if (logs.length === 0) {
                container.innerHTML = '<p class="text-muted text-center" style="padding:1rem;">No audit entries yet.</p>';
                return;
            }
            container.innerHTML = logs.map(l => `
                <div class="audit-entry">
                    <span class="audit-entry__action audit-entry__action--${esc(l.action)}">${esc(l.action)}</span>
                    <strong>${esc(l.phrase_id)}</strong>
                    by <em>${esc(l.admin_user || '—')}</em>
                    <span class="text-muted" style="float:right;font-size:0.75rem;">${l.timestamp ? new Date(l.timestamp).toLocaleString() : ''}</span>
                </div>
            `).join('');
        } catch (e) {
            console.error('Audit log error:', e);
        }
    }

    // ══════════════════════════════════════════════════════════
    // CHARTS
    // ══════════════════════════════════════════════════════════

    function renderCharts(sessions) {
        const userData = {};
        sessions.forEach(s => {
            const u = s.username;
            if (!userData[u]) userData[u] = { dwells: [], flights: [], durations: [], cvs: [] };
            const f = s.features || {};
            const c = f.core_features || {};
            const v = f.variability_features || {};
            if (v.mean_dwell_time) userData[u].dwells.push(v.mean_dwell_time);
            if (v.mean_flight_time) userData[u].flights.push(v.mean_flight_time);
            if (c.total_typing_duration_ms) userData[u].durations.push(c.total_typing_duration_ms);
            if (v.coefficient_of_variation) userData[u].cvs.push(v.coefficient_of_variation);
        });
        const users = Object.keys(userData);
        const clrs = genColors(users.length);

        updateChart('chart-dwell', 'bar', { labels: users, datasets: [{ label: 'Avg Dwell Time (ms)', data: users.map(u => avg(userData[u].dwells)), backgroundColor: clrs.map(c => c + '99'), borderColor: clrs, borderWidth: 1 }] });
        updateChart('chart-flight', 'bar', { labels: users, datasets: [{ label: 'Avg Flight Time (ms)', data: users.map(u => avg(userData[u].flights)), backgroundColor: clrs.map(c => c + '77'), borderColor: clrs, borderWidth: 1 }] });
        updateChart('chart-duration', 'bar', { labels: users, datasets: [{ label: 'Avg Duration (ms)', data: users.map(u => avg(userData[u].durations)), backgroundColor: clrs.map(c => c + '88'), borderColor: clrs, borderWidth: 1 }] });
        updateChart('chart-variability', 'bar', { labels: users, datasets: [{ label: 'Avg CV (Dwell)', data: users.map(u => avg(userData[u].cvs)), backgroundColor: clrs.map(c => c + 'aa'), borderColor: clrs, borderWidth: 1 }] });
    }

    function updateChart(id, type, data) {
        if (charts[id]) charts[id].destroy();
        charts[id] = new Chart(document.getElementById(id).getContext('2d'), {
            type, data,
            options: {
                responsive: true,
                plugins: { legend: { labels: { color: '#94a3b8', font: { family: 'Inter' } } } },
                scales: {
                    x: { ticks: { color: '#64748b', font: { family: 'Inter' } }, grid: { color: 'rgba(255,255,255,0.04)' } },
                    y: { ticks: { color: '#64748b', font: { family: 'Inter' } }, grid: { color: 'rgba(255,255,255,0.04)' } },
                },
            },
        });
    }

    // ══════════════════════════════════════════════════════════
    // UTILITIES
    // ══════════════════════════════════════════════════════════
    function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
    function escA(s) { return String(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
    function fmtLabel(k) { return k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()); }
    function avg(a) { return a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0; }
    function genColors(n) {
        const b = ['#6366f1', '#8b5cf6', '#a78bfa', '#3b82f6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#14b8a6'];
        return Array.from({ length: n }, (_, i) => b[i % b.length]);
    }

    // ══════════════════════════════════════════════════════════
    // INIT
    // ══════════════════════════════════════════════════════════
    loadDashboard();
    loadSessions();
    loadPhrases();
    loadAuditLog();

})();
