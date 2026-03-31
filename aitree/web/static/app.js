// ── State ─────────────────────────────────────────────────────────────────────
const S = {
    root: '.',
    treeData: null,
    rawOutput: null,
    activeTab: 'tree',
    openFile: null,
    collapsed: new Set(),
    pollHash: '',
    searchQuery: '',
    wordWrap: false,
};

// ── File type colors ──────────────────────────────────────────────────────────
const EXT_COLORS = {
    // Python
    py: '#3b82f6', pyw: '#3b82f6',
    // JavaScript
    js: '#f59e0b', mjs: '#f59e0b', cjs: '#f59e0b',
    // TypeScript
    ts: '#2563eb',
    // React / JSX / TSX
    jsx: '#61dafb', tsx: '#38bdf8',
    // Web
    html: '#f97316', htm: '#f97316',
    css: '#06b6d4', scss: '#ec4899', sass: '#ec4899', less: '#7c3aed',
    // Data/config
    json: '#84cc16', yaml: '#ef4444', yml: '#ef4444',
    toml: '#f43f5e', xml: '#fb923c', env: '#84cc16',
    // Docs
    md: '#a78bfa', mdx: '#a78bfa', txt: '#9ca3af', rst: '#9ca3af',
    // Shell
    sh: '#22c55e', bash: '#22c55e', zsh: '#22c55e', fish: '#22c55e',
    ps1: '#2563eb', bat: '#fbbf24', cmd: '#fbbf24',
    // Languages
    go: '#38bdf8', rs: '#f97316', rb: '#ef4444', php: '#818cf8',
    java: '#f59e0b', kt: '#818cf8', swift: '#f97316',
    c: '#6b7280', cpp: '#3b82f6', h: '#6b7280', cs: '#818cf8',
    lua: '#2563eb', r: '#2563eb', jl: '#818cf8',
    // Frameworks
    vue: '#22c55e', svelte: '#f97316', astro: '#f97316',
    // Images
    png: '#ec4899', jpg: '#ec4899', jpeg: '#ec4899',
    gif: '#ec4899', svg: '#f97316', ico: '#ec4899', webp: '#ec4899',
    // Data
    csv: '#22c55e', sql: '#3b82f6',
    // Misc
    lock: '#9ca3af', sum: '#9ca3af',
    zip: '#9ca3af', tar: '#9ca3af', gz: '#9ca3af',
};

const LANG_MAP = {
    js: 'javascript', mjs: 'javascript', cjs: 'javascript',
    ts: 'typescript', tsx: 'typescript',
    jsx: 'javascript',
    py: 'python', pyw: 'python',
    html: 'xml', htm: 'xml', xml: 'xml',
    css: 'css', scss: 'scss', sass: 'scss', less: 'less',
    json: 'json', yaml: 'yaml', yml: 'yaml', toml: 'toml',
    md: 'markdown', mdx: 'markdown',
    sh: 'bash', bash: 'bash', zsh: 'bash', fish: 'bash',
    ps1: 'powershell',
    go: 'go', rs: 'rust', rb: 'ruby', php: 'php',
    java: 'java', kt: 'kotlin', swift: 'swift',
    c: 'c', cpp: 'cpp', h: 'c', cs: 'csharp',
    lua: 'lua', r: 'r', sql: 'sql',
    vue: 'xml', svelte: 'xml', astro: 'xml',
};

function getExt(name) {
    if (!name) return '';
    const parts = name.split('.');
    return parts.length > 1 ? parts.pop().toLowerCase() : '';
}

function fileColor(name) {
    return EXT_COLORS[getExt(name)] || '#6b7280';
}

function fileLang(name) {
    return LANG_MAP[getExt(name)] || null;
}

// ── Theme ─────────────────────────────────────────────────────────────────────
function initTheme() {
    const saved = localStorage.getItem('aitree-theme') || 'dark';
    applyTheme(saved, true);
}

function applyTheme(theme, init) {
    document.documentElement.setAttribute('data-theme', theme);
    if (!init) localStorage.setItem('aitree-theme', theme);
    const isDark = theme === 'dark';
    const sunEl = document.getElementById('iconSun');
    const moonEl = document.getElementById('iconMoon');
    if (sunEl) sunEl.style.display = isDark ? '' : 'none';
    if (moonEl) moonEl.style.display = isDark ? 'none' : '';
    const hlLink = document.getElementById('hlCss');
    if (hlLink) {
        hlLink.href = isDark
            ? 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.10.0/styles/tokyo-night-dark.min.css'
            : 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.10.0/styles/github.min.css';
    }
    // Re-render file preview so highlighting colours update
    if (!init && S.activeTab === 'file' && S.openFile) {
        setTimeout(renderFile, 80); // small delay so new stylesheet loads
    }
}

function toggleTheme() {
    const cur = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(cur === 'dark' ? 'light' : 'dark');
    localStorage.setItem('aitree-theme', document.documentElement.getAttribute('data-theme'));
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
function switchTab(name) {
    S.activeTab = name;
    document.querySelectorAll('.tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === name);
    });
    const toolbar = document.getElementById('treeToolbar');
    if (toolbar) toolbar.style.display = name === 'tree' ? '' : 'none';
    if (name === 'tree') renderTree();
    if (name === 'stats') renderStats();
    if (name === 'file') renderFile();
}

document.querySelector('.tabbar').addEventListener('click', e => {
    const t = e.target.closest('.tab');
    if (t && t.dataset.tab) switchTab(t.dataset.tab);
});

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
    initTheme();
    initSidebarResize();
    initKeyboardShortcuts();

    try {
        const d = await apiFetch('/api/poll');
        S.root = d.path || '.';
        S.pollHash = d.hash || '';
        const pathEl = document.getElementById('pathDisp');
        pathEl.textContent = S.root;
        pathEl.title = S.root;
    } catch (_) { }

    await loadTree();
    startPolling();

    // Real-time tree search
    const searchInput = document.getElementById('searchInput');
    searchInput.addEventListener('input', e => {
        S.searchQuery = e.target.value.trim().toLowerCase();
        document.getElementById('searchClear').style.display = S.searchQuery ? '' : 'none';
        if (S.activeTab === 'tree') renderTree();
    });

    // Enter to apply filters
    document.querySelectorAll('#fDepth, #fInclude, #fExclude').forEach(input => {
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter') applyFilters();
        });
    });
}

function clearSearch() {
    S.searchQuery = '';
    const si = document.getElementById('searchInput');
    si.value = '';
    document.getElementById('searchClear').style.display = 'none';
    if (S.activeTab === 'tree') renderTree();
}

// ── Polling ───────────────────────────────────────────────────────────────────
function startPolling() {
    setInterval(async () => {
        try {
            const d = await apiFetch('/api/poll');
            if (d.hash && d.hash !== S.pollHash) {
                S.pollHash = d.hash;
                await loadTree(true);
            }
        } catch (_) { }
    }, 2000);
}

// ── Tree loading ──────────────────────────────────────────────────────────────
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
    const si = document.getElementById('searchInput');

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
            si.disabled = false;
            si.placeholder = 'Search files…   /';
        } else {
            const d = await apiPost('/api/tree', getFilters(fmt));
            if (d.error) throw new Error(d.error);
            S.rawOutput = d.output;
            S.treeData = null;
            document.getElementById('infoDisp').textContent = fmt + ' mode';
            si.disabled = true;
            si.placeholder = 'Search — json mode only';
        }

        if (S.activeTab === 'tree') renderTree();
        else if (S.activeTab === 'stats') renderStats();

    } catch (e) {
        if (!silent) showErr('Tree error: ' + e.message);
    }
}

function applyFilters() { loadTree(); }

function onFormatChange() {
    S.treeData = null;
    S.rawOutput = null;
    loadTree();
}

// ── Search helpers ────────────────────────────────────────────────────────────
function nodeMatchesSearch(node, q) {
    if (!q) return true;
    if (node.name.toLowerCase().includes(q)) return true;
    if (node.type === 'directory' && node.children) {
        return node.children.some(c => nodeMatchesSearch(c, q));
    }
    return false;
}

function highlightText(text, query) {
    if (!query) return esc(text);
    const lower = text.toLowerCase();
    const idx = lower.indexOf(query);
    if (idx === -1) return esc(text);
    return (
        esc(text.slice(0, idx)) +
        '<mark>' + esc(text.slice(idx, idx + query.length)) + '</mark>' +
        esc(text.slice(idx + query.length))
    );
}

// ── Render: Tree ──────────────────────────────────────────────────────────────
function renderTree() {
    // Raw text / markdown
    if (S.rawOutput !== null && S.rawOutput !== undefined) {
        const pre = el('pre', '');
        pre.style.cssText = 'font-family:var(--mono);font-size:12.5px;line-height:1.7;white-space:pre-wrap;color:var(--text)';
        pre.textContent = S.rawOutput;
        setContent(pre);
        return;
    }

    if (!S.treeData) { showLoading('Loading…'); return; }

    const root = S.treeData.tree;
    const q = S.searchQuery;
    const wrap = el('div', 'tree-wrap');

    // Root directory row
    const rootRow = el('div', 'tn directory');
    rootRow.innerHTML =
        '<span class="tn-pre"></span>' +
        '<span class="dir-icon">▾</span>' +
        '<span class="nm" data-dir="">' + highlightText(root.name, q) + '/</span>';
    wrap.appendChild(rootRow);

    if (!S.collapsed.has('') || q) {
        const kids = q
            ? (root.children || []).filter(c => nodeMatchesSearch(c, q))
            : (root.children || []);
        appendChildren(kids, '', wrap, [], q);
    }

    // Footer
    const s = S.treeData.stats;
    const tok = s.total_tokens && document.getElementById('fTokens').checked
        ? ' · ~' + s.total_tokens.toLocaleString() + ' tokens'
        : '';
    let footerText;
    if (q) {
        const vis = countVisible(root.children || [], q);
        footerText = 'Showing ' + vis + ' of ' + s.total_files + ' files' + tok;
    } else {
        footerText = s.total_dirs + ' dirs · ' + s.total_files + ' files · ' + humanSize(s.total_size) + tok;
    }
    const footer = el('div', 'tree-footer');
    footer.textContent = footerText;
    wrap.appendChild(footer);

    setContent(wrap);
}

function countVisible(children, q) {
    let n = 0;
    for (const node of children) {
        if (!nodeMatchesSearch(node, q)) continue;
        if (node.type === 'file') n++;
        else if (node.children) n += countVisible(node.children, q);
    }
    return n;
}

function appendChildren(children, parentPath, container, ancestorsLast, q) {
    const list = q ? children.filter(c => nodeMatchesSearch(c, q)) : children;

    list.forEach((node, i) => {
        const isLast = i === list.length - 1;
        const nodePath = parentPath ? parentPath + '/' + node.name : node.name;
        const prefix = ancestorsLast.map(last => last ? '    ' : '│   ').join('')
            + (isLast ? '└── ' : '├── ');

        const row = el('div', 'tn ' + node.type);

        if (node.type === 'directory') {
            const coll = !q && S.collapsed.has(nodePath);
            row.innerHTML =
                '<span class="tn-pre">' + prefix + '</span>' +
                '<span class="dir-icon">' + (coll ? '▸' : '▾') + '</span>' +
                '<span class="nm" data-dir="' + attrEsc(nodePath) + '">' +
                highlightText(node.name, q) + '/</span>';
            container.appendChild(row);

            if (!coll && node.children) {
                const kids = q ? node.children.filter(c => nodeMatchesSearch(c, q)) : node.children;
                appendChildren(kids, nodePath, container, ancestorsLast.concat([isLast]), q);
            }

        } else {
            const color = fileColor(node.name);
            const sz = node.size != null
                ? '<span class="sz">' + humanSize(node.size) + '</span>'
                : '';
            const tok = (node.tokens != null && document.getElementById('fTokens').checked)
                ? '<span class="tok">' + node.tokens.toLocaleString() + 't</span>'
                : '';
            row.innerHTML =
                '<span class="tn-pre">' + prefix + '</span>' +
                '<span class="fi-dot" style="background:' + color + '"></span>' +
                '<span class="nm" data-file="' + attrEsc(nodePath) + '">' +
                highlightText(node.name, q) + '</span>' + sz + tok;
            container.appendChild(row);
        }
    });
}

// Tree click delegation
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

function expandAll() {
    S.collapsed.clear();
    if (S.activeTab === 'tree') renderTree();
}

function collapseAll() {
    if (!S.treeData) return;
    function walk(node, path) {
        if (node.type !== 'directory') return;
        if (path) S.collapsed.add(path);
        for (const child of (node.children || [])) {
            walk(child, path ? path + '/' + child.name : child.name);
        }
    }
    for (const child of (S.treeData.tree.children || [])) {
        walk(child, child.name);
    }
    if (S.activeTab === 'tree') renderTree();
}

// ── Render: Stats ─────────────────────────────────────────────────────────────
async function renderStats() {
    if (S.treeData) { _renderStatsData(S.treeData.stats, S.treeData.meta); return; }
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

function _renderStatsData(s) {
    const exts = Object.entries(s.ext_count || {}).sort((a, b) => b[1] - a[1]);
    const maxC = exts.length ? exts[0][1] : 1;
    const total = s.total_files || 1;
    const hasTokens = !!s.ext_tokens;

    const wrap = el('div', '');

    // Summary cards
    const grid = el('div', 'stat-grid');
    const cards = [
        [s.total_files, 'Files', '#3b82f6'],
        [s.total_dirs, 'Directories', '#22c55e'],
        [humanSize(s.total_size), 'Total Size', '#f59e0b'],
    ];
    if (s.total_tokens) {
        cards.push(['~' + (s.total_tokens / 1000).toFixed(1) + 'k', 'Tokens', '#a78bfa']);
    }
    grid.innerHTML = cards.map(([val, lbl, color]) =>
        '<div class="stat-card">' +
        '<div class="stat-val" style="color:' + color + '">' + val + '</div>' +
        '<div class="stat-lbl">' + lbl + '</div>' +
        '</div>'
    ).join('');
    wrap.appendChild(grid);

    // Extension table
    if (exts.length) {
        const title = el('div', 'section-title');
        title.textContent = 'File Types';
        wrap.appendChild(title);

        const tbl = el('table', 'ext-tbl');
        tbl.innerHTML =
            '<thead><tr>' +
            '<th>Extension</th>' +
            '<th>Count</th>' +
            '<th style="min-width:120px">Share</th>' +
            (hasTokens ? '<th>Tokens</th>' : '') +
            '</tr></thead>' +
            '<tbody>' +
            exts.slice(0, 30).map(([ext, cnt]) => {
                const pct = Math.round(cnt / total * 100);
                const barW = Math.round(cnt / maxC * 100);
                const color = EXT_COLORS[ext.replace('.', '')] || '#6b7280';
                const tokVal = hasTokens && s.ext_tokens[ext]
                    ? s.ext_tokens[ext].toLocaleString() : '';
                return '<tr>' +
                    '<td>' +
                    '<span class="fi-dot" style="background:' + color + ';margin-right:6px;vertical-align:middle"></span>' +
                    '<code>' + esc(ext || '(none)') + '</code>' +
                    '</td>' +
                    '<td>' + cnt + '</td>' +
                    '<td>' +
                    '<div class="ext-bar-wrap">' +
                    '<div class="ext-bar" style="width:' + barW + '%;background:' + color + '"></div>' +
                    '<span class="ext-pct">' + pct + '%</span>' +
                    '</div>' +
                    '</td>' +
                    (hasTokens ? '<td>' + (tokVal || '—') + '</td>' : '') +
                    '</tr>';
            }).join('') +
            '</tbody>';
        wrap.appendChild(tbl);
    }

    setContent(wrap);
}

// ── Render: File preview ──────────────────────────────────────────────────────
function renderFile() {
    const f = S.openFile;
    if (!f) return;

    const fname = (f.file || '').replace(/\\/g, '/').split('/').pop();
    const lang = fileLang(fname);
    const lines = f.content.split('\n');

    const wrap = el('div', 'file-preview');

    // Header
    const hdr = el('div', 'file-hdr');
    const parts = f.file.replace(/\\/g, '/').split('/');
    const crumb = el('div', 'file-breadcrumb');
    crumb.innerHTML = parts.map((p, i) =>
        i === parts.length - 1
            ? '<strong>' + esc(p) + '</strong>'
            : '<span>' + esc(p) + '</span><span class="crumb-sep">/</span>'
    ).join('');
    hdr.appendChild(crumb);

    const actions = el('div', 'file-hdr-actions');
    const wrapActive = S.wordWrap ? 'opacity:1' : 'opacity:.6';
    actions.innerHTML =
        '<span class="file-meta">' +
        humanSize(f.size) + ' · ' + lines.length + ' lines' +
        (lang ? ' · ' + lang : '') +
        '</span>' +
        '<button class="btn btn-sm" id="btnWrap" onclick="toggleWordWrap()" title="Toggle word wrap" style="' + wrapActive + '">' +
        '⇌ wrap' +
        '</button>' +
        '<button class="btn btn-sm" onclick="copyFileContent()">Copy</button>';
    hdr.appendChild(actions);
    wrap.appendChild(hdr);

    // Code + line numbers
    const codeArea = el('div', 'file-code-area');

    const lineNums = el('div', 'line-nums');
    lineNums.id = 'lineNums';
    lineNums.innerHTML = lines.map((_, i) => '<span>' + (i + 1) + '</span>').join('');

    const pre = el('pre', 'file-body' + (S.wordWrap ? ' word-wrap' : ''));
    pre.id = 'fileBody';
    const code = el('code', lang ? 'language-' + lang : '');
    code.textContent = f.content;
    pre.appendChild(code);

    codeArea.appendChild(lineNums);
    codeArea.appendChild(pre);
    wrap.appendChild(codeArea);

    setContent(wrap);

    // Apply syntax highlighting
    if (typeof hljs !== 'undefined') {
        try {
            hljs.highlightElement(code);
        } catch (_) { }
    }

    // Sync vertical scroll: code → line numbers
    pre.addEventListener('scroll', () => {
        lineNums.scrollTop = pre.scrollTop;
    });
}

function toggleWordWrap() {
    S.wordWrap = !S.wordWrap;
    const fb = document.getElementById('fileBody');
    const btn = document.getElementById('btnWrap');
    if (fb) fb.classList.toggle('word-wrap', S.wordWrap);
    if (btn) btn.style.opacity = S.wordWrap ? '1' : '.6';
}

async function openFileView(filePath) {
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
        document.getElementById('tabFileName').textContent = cleanPath.split('/').pop();
        switchTab('file');
    } catch (e) {
        showErr('Could not open file: ' + e.message);
    }
}

function copyFileContent() {
    if (S.openFile) navigator.clipboard.writeText(S.openFile.content).catch(() => { });
}

// ── Copy tree ─────────────────────────────────────────────────────────────────
document.getElementById('btnCopy').addEventListener('click', async function () {
    const fmt = document.getElementById('fFormat').value;
    const copyFmt = fmt === 'json' ? 'text' : fmt;
    try {
        const d = await apiPost('/api/tree', getFilters(copyFmt));
        if (d.error) throw new Error(d.error);
        await navigator.clipboard.writeText(d.output);
        const orig = this.innerHTML;
        this.innerHTML =
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg> Copied!';
        setTimeout(() => this.innerHTML = orig, 1600);
    } catch (e) {
        alert('Copy failed: ' + e.message);
    }
});

// ── Sidebar resize ────────────────────────────────────────────────────────────
function initSidebarResize() {
    const sidebar = document.getElementById('sidebar');
    const resizer = document.getElementById('sidebarResizer');
    let isResizing = false;

    // Restore saved width
    const saved = localStorage.getItem('aitree-sidebar-width');
    if (saved) {
        sidebar.style.width = saved;
        document.documentElement.style.setProperty('--sidebar', saved);
    }

    resizer.addEventListener('mousedown', e => {
        isResizing = true;
        resizer.classList.add('resizing');
        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'col-resize';
        e.preventDefault();
    });

    document.addEventListener('mousemove', e => {
        if (!isResizing) return;
        const newW = Math.max(180, Math.min(500, e.clientX));
        sidebar.style.width = newW + 'px';
        document.documentElement.style.setProperty('--sidebar', newW + 'px');
    });

    document.addEventListener('mouseup', () => {
        if (!isResizing) return;
        isResizing = false;
        resizer.classList.remove('resizing');
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        localStorage.setItem('aitree-sidebar-width', sidebar.style.width);
    });
}

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
function initKeyboardShortcuts() {
    document.addEventListener('keydown', e => {
        const tag = document.activeElement.tagName;
        const isInput = tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA';

        if (e.key === '/' && !isInput) {
            e.preventDefault();
            const si = document.getElementById('searchInput');
            si.focus(); si.select();
        }

        if (e.key === 'Escape') {
            const si = document.getElementById('searchInput');
            if (document.activeElement === si && S.searchQuery) {
                clearSearch(); si.blur();
            } else if (document.activeElement === si) {
                si.blur();
            }
        }
    });
}

// ── API helpers ───────────────────────────────────────────────────────────────
async function apiFetch(url) {
    const r = await fetch(url);
    const ct = r.headers.get('content-type');
    if (ct && ct.includes('application/json')) {
        const d = await r.json();
        if (d.error) throw new Error(d.error);
        return d;
    }
    const body = await r.text();
    if (!r.ok) throw new Error('Server error (' + r.status + '): ' + (body || 'Unknown'));
    return body;
}

async function apiPost(url, body) {
    const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const ct = r.headers.get('content-type');
    if (ct && ct.includes('application/json')) return r.json();
    const text = await r.text();
    if (!r.ok) return { error: 'Server error (' + r.status + '): ' + (text || 'Unknown') };
    return { output: text, error: null };
}

// ── DOM helpers ───────────────────────────────────────────────────────────────
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
    setContent('<div class="loading"><div class="spinner"></div>' + esc(msg) + '</div>');
}

function showErr(msg) {
    setContent(
        '<div class="err">' +
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>' +
        esc(msg) + '</div>'
    );
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

// ── Start ─────────────────────────────────────────────────────────────────────
init();