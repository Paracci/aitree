// ── State ──────────────────────────────────────────────────────────────────────
const S = {
    root: '.',
    treeData: null,       // parsed JSON from /api/tree (json format)
    rawOutput: null,      // raw string from /api/tree (text/markdown format)
    activeTab: 'tree',
    openFile: null,       // {file, content, size}
    collapsed: new Set(),
    pollHash: '',
};

// ── Tabs ───────────────────────────────────────────────────────────────────────
function switchTab(name) {
    S.activeTab = name;
    document.querySelectorAll('.tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === name);
    });
    if (name === 'tree') renderTree();
    if (name === 'stats') renderStats();
    if (name === 'file') renderFile();
}

document.querySelector('.tabbar').addEventListener('click', e => {
    const t = e.target.closest('.tab');
    if (t && t.dataset.tab) switchTab(t.dataset.tab);
});

// ── Init ───────────────────────────────────────────────────────────────────────
async function init() {
    try {
        const d = await apiFetch('/api/poll');
        S.root = d.path || '.';
        S.pollHash = d.hash || '';
        document.getElementById('pathDisp').textContent = S.root;
    } catch (_) { }
    await loadTree();
    startPolling();
}

// ── Polling ────────────────────────────────────────────────────────────────────
function startPolling() {
    setInterval(async () => {
        try {
            const d = await apiFetch('/api/poll');
            if (d.hash && d.hash !== S.pollHash) {
                S.pollHash = d.hash;
                await loadTree(/*silent=*/true);
            }
        } catch (_) { }
    }, 2000);
}

// ── Tree loading ───────────────────────────────────────────────────────────────
function getFilters(fmt) {
    const rawD = parseInt(document.getElementById('fDepth').value);
    const rawI = document.getElementById('fInclude').value.trim();
    const rawE = document.getElementById('fExclude').value.trim();
    return {
        path: S.root,
        depth: isNaN(rawD) ? null : rawD,
        include: rawI ? rawI.split(',').map(s => s.trim()).filter(Boolean) : [],
        exclude: rawE ? rawE.split(',').map(s => s.trim()).filter(Boolean) : [],
        git_changed: document.getElementById('fGitChanged').checked,
        no_gitignore: document.getElementById('fNoGitignore').checked,
        tokens: document.getElementById('fTokens').checked,
        format: fmt,
    };
}

async function loadTree(silent) {
    const fmt = document.getElementById('fFormat').value;
    const useJson = fmt === 'json';

    // Only show the loading indicator when we are actually on the tree tab
    if (!silent && S.activeTab === 'tree') showLoading('Loading tree…');

    try {
        if (useJson) {
            const d = await apiPost('/api/tree', getFilters('json'));
            if (d.error) throw new Error(d.error);
            S.treeData = JSON.parse(d.output);
            S.rawOutput = null;
            const s = S.treeData.stats;
            let infoText = s.total_dirs + ' dirs · ' + s.total_files + ' files · ' + humanSize(s.total_size);
            if (s.total_tokens) infoText += ' · ~' + s.total_tokens.toLocaleString() + ' tokens';
            document.getElementById('infoDisp').textContent = infoText;
        } else {
            const d = await apiPost('/api/tree', getFilters(fmt));
            if (d.error) throw new Error(d.error);
            S.rawOutput = d.output;
            S.treeData = null;
            document.getElementById('infoDisp').textContent = fmt + ' mode';
        }

        // Always re-render whichever tab is currently active
        if (S.activeTab === 'tree') renderTree();
        else if (S.activeTab === 'stats') renderStats();
        // file tab keeps its existing content untouched

    } catch (e) {
        if (!silent) showErr('Tree error: ' + e.message);
    }
}

function applyFilters() { loadTree(); }

function onFormatChange() {
    // When switching format, we must clear treeData/rawOutput to force re-render
    S.treeData = null;
    S.rawOutput = null;
    loadTree();
}

// ── Render: Tree ───────────────────────────────────────────────────────────────
function renderTree() {
    // Raw text / markdown mode — just show the pre-formatted output
    if (S.rawOutput !== null && S.rawOutput !== undefined) {
        const pre = el('pre', '');
        pre.style.cssText =
            'font-family:var(--mono);font-size:12.5px;line-height:1.7;' +
            'white-space:pre-wrap;color:var(--text)';
        pre.textContent = S.rawOutput;
        setContent(pre);
        return;
    }

    if (!S.treeData) { showLoading('Loading…'); return; }

    const root = S.treeData.tree;
    const wrap = el('div', 'tree-wrap');

    // root row
    const rootRow = el('div', 'tn dir');
    rootRow.innerHTML = '<span class="nm" data-dir="">' + esc(root.name) + '/</span>';
    wrap.appendChild(rootRow);

    if (!S.collapsed.has('')) {
        appendChildren(root.children || [], '', wrap, []);
    }

    if (document.getElementById('fTokens').checked) {
        const tok = S.treeData.stats && S.treeData.stats.total_tokens;
        if (tok) {
            const footer = el('div', 'tree-footer');
            footer.innerHTML = '<span>~' + tok.toLocaleString() + ' total tokens</span>';
            wrap.appendChild(footer);
        }
    }

    setContent(wrap);
}

function appendChildren(children, parentPath, container, ancestorsLast) {
    children.forEach((node, i) => {
        const isLast = i === children.length - 1;
        const nodePath = parentPath ? parentPath + '/' + node.name : node.name;

        const prefixStr = ancestorsLast.map(last => last ? '    ' : '│   ').join('')
            + (isLast ? '└── ' : '├── ');

        const row = el('div', 'tn ' + node.type);

        if (node.type === 'directory') {
            const coll = S.collapsed.has(nodePath);
            row.innerHTML =
                '<span class="pre">' + prefixStr + '</span>' +
                '<span class="nm" data-dir="' + attrEsc(nodePath) + '">' +
                (coll ? '▶ ' : '▼ ') + esc(node.name) + '/</span>';
            container.appendChild(row);
            if (!coll && node.children) {
                appendChildren(node.children, nodePath, container, ancestorsLast.concat([isLast]));
            }
        } else {
            const sz = node.size != null
                ? '<span class="sz">[' + humanSize(node.size) + ']</span>'
                : '';
            const tok = (node.tokens != null && document.getElementById('fTokens').checked)
                ? '<span class="tok">' + node.tokens.toLocaleString() + ' t</span>'
                : '';
            row.innerHTML =
                '<span class="pre">' + prefixStr + '</span>' +
                '<span class="nm" data-file="' + attrEsc(nodePath) + '">' + esc(node.name) + '</span>' + sz + tok;
            container.appendChild(row);
        }
    });
}

// Event delegation for tree clicks
document.addEventListener('click', e => {
    const nm = e.target.closest('.nm');
    if (!nm) return;
    if (nm.dataset.dir !== undefined) toggleDir(nm.dataset.dir);
    else if (nm.dataset.file !== undefined) openFileView(nm.dataset.file);
});

function toggleDir(path) {
    if (S.collapsed.has(path)) S.collapsed.delete(path);
    else S.collapsed.add(path);
    if (S.activeTab === 'tree') renderTree();
}

// ── Render: Stats ──────────────────────────────────────────────────────────────
async function renderStats() {
    // If we already have JSON data cached, use it immediately
    if (S.treeData) {
        _renderStatsData(S.treeData.stats, S.treeData.meta);
        return;
    }
    // Format is text/markdown — fetch JSON separately just for stats
    showLoading('Loading stats…');
    try {
        const d = await apiPost('/api/tree', getFilters('json'));
        if (d.error) throw new Error(d.error);
        const data = JSON.parse(d.output);
        _renderStatsData(data.stats, data.meta);
    } catch (e) {
        showErr('Stats error: ' + e.message);
    }
}

function _renderStatsData(s, meta) {
    const exts = Object.entries(s.ext_count || {}).sort((a, b) => b[1] - a[1]);
    const maxC = exts.length ? exts[0][1] : 1;

    let html =
        '<div class="stat-grid">' +
        statCard(s.total_files, 'Files') +
        statCard(s.total_dirs, 'Directories') +
        statCard(humanSize(s.total_size), 'Total Size') +
        '</div>';

    if (exts.length) {
        html += '<div class="section-title">File Types</div>' +
            '<table class="ext-tbl"><thead><tr>' +
            '<th>Extension</th><th>Count</th>' +
            (s.ext_tokens ? '<th>Tokens</th>' : '') +
            '<th style="width:90px"></th>' +
            '</tr></thead><tbody>';
        exts.slice(0, 25).forEach(([ext, cnt]) => {
            const w = Math.round(cnt / maxC * 100);
            const t = s.ext_tokens && s.ext_tokens[ext] ? s.ext_tokens[ext].toLocaleString() : '—';
            html += '<tr><td><code>' + esc(ext) + '</code></td><td>' + cnt + '</td>' +
                (s.ext_tokens ? '<td>' + t + '</td>' : '') +
                '<td><div class="bar" style="width:' + w + '%"></div></td></tr>';
        });
        html += '</tbody></table>';
    }

    const tok = s.total_tokens;
    if (tok) {
        html += '<p style="margin-top:12px;color:var(--text2);font-size:12px">~' +
            tok.toLocaleString() + ' total tokens</p>';
    }

    setContent(html);
}

function statCard(val, lbl) {
    return '<div class="stat-card"><div class="stat-val">' + val +
        '</div><div class="stat-lbl">' + lbl + '</div></div>';
}

// ── Render: File preview ───────────────────────────────────────────────────────
function renderFile() {
    const f = S.openFile;
    if (!f) return;
    const html =
        '<div class="file-hdr">' +
        '<span style="font-family:var(--mono)">' + esc(f.file) + '</span>' +
        '<span>' + humanSize(f.size) +
        ' &nbsp;<button class="btn btn-sm" onclick="copyFileContent()">Copy</button></span>' +
        '</div>' +
        '<div class="file-body" id="fileBody">' + esc(f.content) + '</div>';
    setContent(html);
}

async function openFileView(filePath) {
    // Normalize separators and strip root-directory prefix if the AI included it
    const norm = filePath.replace(/\\/g, '/').replace(/^\.\//, '');
    const rootName = S.root.replace(/\\/g, '/').split('/').pop();
    const cleanPath = (norm === rootName || norm.startsWith(rootName + '/'))
        ? norm.slice(rootName.length).replace(/^\//, '')
        : norm;

    if (!cleanPath) { showErr('Could not resolve file path: ' + filePath); return; }

    showLoading('Loading ' + cleanPath + '…');
    try {
        const url = '/api/file?root=' + encodeURIComponent(S.root) +
            '&file=' + encodeURIComponent(cleanPath);
        const d = await apiFetch(url);
        if (d.error) throw new Error(d.error);
        S.openFile = d;
        const tab = document.getElementById('tab-file');
        tab.classList.remove('hidden');
        tab.textContent = '📄 ' + cleanPath.split('/').pop();
        switchTab('file');
    } catch (e) {
        showErr('Could not open file: ' + e.message);
    }
}

function copyFileContent() {
    if (S.openFile) navigator.clipboard.writeText(S.openFile.content).catch(() => { });
}

// ── Copy tree ──────────────────────────────────────────────────────────────────
document.getElementById('btnCopy').addEventListener('click', async function () {
    const fmt = document.getElementById('fFormat').value;
    // Copy in the selected format; fall back to text for json (raw JSON is not useful to paste)
    const copyFmt = fmt === 'json' ? 'text' : fmt;
    try {
        const d = await apiPost('/api/tree', getFilters(copyFmt));
        if (d.error) throw new Error(d.error);
        await navigator.clipboard.writeText(d.output);
        const orig = this.textContent;
        this.textContent = '✓ Copied!';
        setTimeout(() => this.textContent = orig, 1600);
    } catch (e) {
        alert('Copy failed: ' + e.message);
    }
});

// ── API helpers ────────────────────────────────────────────────────────────────
async function apiFetch(url) {
    const r = await fetch(url);
    const contentType = r.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
        const d = await r.json();
        if (d.error) throw new Error(d.error);
        return d;
    }
    const body = await r.text();
    if (!r.ok) throw new Error('Server error (' + r.status + '): ' + (body || 'Unknown error'));
    return body;
}

async function apiPost(url, body) {
    const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const contentType = r.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
        const d = await r.json();
        // Return the object; caller checks d.error
        return d;
    }
    const text = await r.text();
    if (!r.ok) return { error: 'Server error (' + r.status + '): ' + (text || 'Unknown') };
    return { output: text, error: null };
}

// ── DOM helpers ────────────────────────────────────────────────────────────────
function el(tag, cls) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    return e;
}

function setContent(node) {
    const c = document.getElementById('content');
    if (typeof node === 'string') c.innerHTML = node;
    else { c.innerHTML = ''; c.appendChild(node); }
}

function showLoading(msg) {
    setContent('<div class="loading"><div class="spinner"></div> ' + esc(msg) + '</div>');
}

function showErr(msg) {
    setContent('<div class="err">⚠ ' + esc(msg) + '</div>');
}

function esc(s) {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function attrEsc(s) {
    return String(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function humanSize(b) {
    if (b == null) return '?';
    if (b < 1024) return b + 'B';
    if (b < 1048576) return (b / 1024).toFixed(1) + 'KB';
    return (b / 1048576).toFixed(1) + 'MB';
}

// ── Start ──────────────────────────────────────────────────────────────────────
init();