/* ================================================================
   PostEditor — the one editor used for posts, comments and replies.
   - textarea with live counters (characters, words, line breaks)
   - LinkedIn-style preview with the "…see more" fold
   - live quality meter (deterministic check, no AI) + Auto-fix + Fix with AI
   Usage:
     const ed = new PostEditor(el, { text, kind: 'post', actions: [{label, primary, onClick(ed)}] });
     ed.text           // current text
     PostEditor.attach(textarea, panelEl, { kind })   // add the meter to an existing textarea
   ================================================================ */
(function () {
    const FOLD = 210;            // characters before "…see more" (desktop)
    const LIMITS = {             // [sweet low, sweet high, hard max, max line breaks]
        post: [900, 1500, 3000, 25],
        comment: [200, 350, 1250, 60],
        reply: [150, 300, 1250, 60],
    };
    const STATUS = {
        ready: ['Ready to publish', 'No blocking issues found.', '#12b76a'],
        review: ['Worth a second look', 'No blockers, but a few things could be better.', '#f79009'],
        fix: ['Fix before posting', 'These issues cost reach or read as AI.', '#f04438'],
    };

    function initials(name) {
        return (name || 'You').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('') || 'Y';
    }

    function meterClass(value, lo, hi, max) {
        if (value > max) return 'm-bad';
        if (value < lo || value > hi) return 'm-warn';
        return 'm-ok';
    }

    /* ── Quality panel (shared by PostEditor and attach) ─────── */
    class QualityPanel {
        constructor(el, { onSelect } = {}) {
            this.el = el;
            this.onSelect = onSelect;
        }
        loading() {
            if (!this.el.innerHTML.trim()) {
                this.el.innerHTML = '<div class="skeleton" style="height:58px"></div>';
            }
        }
        render(report) {
            if (!report) { this.el.innerHTML = ''; return; }
            const [title, sub, color] = STATUS[report.status] || STATUS.review;
            const issue = (i) => `
                <div class="q-issue ${i.severity}" data-match="${esc(i.match || '')}">
                    <span class="q-sev"></span>
                    <div>
                        <div class="q-issue-msg">${esc(i.message)}</div>
                        ${i.fix ? `<div class="q-issue-fix">${esc(i.fix)}</div>` : ''}
                        ${i.match ? `<span class="q-issue-match">${esc(i.match)}</span>` : ''}
                    </div>
                </div>`;
            const blockers = report.blockers || [];
            const warnings = report.warnings || [];
            const tips = report.tips || [];
            this.el.innerHTML = `
                <div class="q-head">
                    <div class="q-ring" style="--p:${report.score};--c:${color}"><span>${report.score}</span></div>
                    <div><div class="q-status">${title}</div><div class="q-status-sub">${sub}</div></div>
                </div>
                ${blockers.length ? `<div class="q-section-label">Must fix (${blockers.length})</div>${blockers.map(issue).join('')}` : ''}
                ${warnings.length ? `<div class="q-section-label">Could improve (${warnings.length})</div>${warnings.map(issue).join('')}` : ''}
                ${!blockers.length && !warnings.length ? '<div class="q-empty">✓ Nothing to fix.</div>' : ''}
                ${tips.length ? `<div class="q-section-label">Tips</div>${tips.map(t => `<div class="q-tip">• ${esc(t)}</div>`).join('')}` : ''}`;
            this.el.querySelectorAll('.q-issue').forEach(node => {
                node.addEventListener('click', () => this.onSelect && this.onSelect(node.dataset.match));
            });
        }
    }

    async function checkQuality(text, kind) {
        return App.api('/api/quality/check', { method: 'POST', body: { text, kind }, quiet: true });
    }

    function selectInTextarea(textarea, match) {
        if (!match || match === '—') return;
        const idx = textarea.value.indexOf(match);
        if (idx < 0) return;
        textarea.focus();
        textarea.setSelectionRange(idx, idx + match.length);
        // scroll the selection into view
        const before = textarea.value.slice(0, idx).split('\n').length;
        textarea.scrollTop = Math.max(0, (before - 3) * 22);
    }

    function metersHtml(text, kind) {
        const [lo, hi, max, maxLines] = LIMITS[kind] || LIMITS.post;
        const chars = text.length;
        const words = text.trim() ? text.trim().split(/\s+/).length : 0;
        const lines = (text.match(/\n/g) || []).length;
        const hook = (text.split('\n').find(l => l.trim()) || '').length;
        const parts = [
            `<span class="${meterClass(chars, lo, hi, max)}"><b>${chars.toLocaleString()}</b> / ${lo.toLocaleString()}–${hi.toLocaleString()} chars</span>`,
            `<span><b>${words}</b> words</span>`,
        ];
        if (kind === 'post') {
            parts.push(`<span class="${lines > maxLines ? 'm-bad' : lines > maxLines - 3 ? 'm-warn' : 'm-ok'}"><b>${lines}</b> / ${maxLines} line breaks</span>`);
            parts.push(`<span class="${hook > FOLD ? 'm-warn' : 'm-ok'}">hook <b>${hook}</b> / ${FOLD}</span>`);
        }
        return parts.join('');
    }

    async function runAutofix(getText, setText, kind) {
        const r = await App.api('/api/quality/autofix', { method: 'POST', body: { text: getText(), kind } });
        if (r.text !== getText()) {
            setText(r.text);
            showToast(r.changes.length ? r.changes.join(' · ') : 'Tidied up');
        } else {
            showToast('Nothing to auto-fix — try Fix with AI for the rest', 'info');
        }
        return r.audit;
    }

    async function runAiFix(getText, setText, kind, btn) {
        App.busy(btn, true, 'Fixing…');
        try {
            const r = await App.api('/api/quality/ai-fix', { method: 'POST', body: { text: getText(), kind } });
            if (r.changed) { setText(r.text); showToast('AI fixed the flagged issues — review the changes'); }
            else showToast('Nothing to fix', 'info');
            return r.audit;
        } finally {
            App.busy(btn, false);
        }
    }

    /* ── Full editor ───────────────────────────────────────────── */
    const EMPTY_HINT = '<p class="tiny muted" style="padding: 8px 2px;">The quality check appears once there is text to check.</p>';

    class PostEditor {
        constructor(root, opts = {}) {
            this.opts = Object.assign({
                kind: 'post', text: '', placeholder: 'Write your post…', showPreview: true,
                author: (window.APP && APP.author) || 'You', headline: (window.APP && APP.headline) || '',
                actions: [], onChange: null, minHeight: null,
            }, opts);
            this.root = root;
            this.report = null;
            this.expanded = false;
            this._render();
            this.text = this.opts.text;
        }

        get text() { return this.ta.value; }
        set text(value) {
            this.ta.value = value || '';
            this._changed(true);
        }

        _render() {
            const o = this.opts;
            const preview = o.showPreview && o.kind === 'post';
            this.root.innerHTML = `
                <div class="pe ${o.showPreview ? '' : 'pe-single'}">
                    <div>
                        <textarea class="pe-textarea" spellcheck="true" placeholder="${esc(o.placeholder)}"
                            ${o.minHeight ? `style="min-height:${o.minHeight}px"` : ''}></textarea>
                        <div class="pe-meters"></div>
                        <div class="pe-toolbar">
                            <button type="button" class="btn btn-ghost btn-sm" data-act="autofix" title="Safe fixes that never change your meaning">Auto-fix</button>
                            <button type="button" class="btn btn-ghost btn-sm" data-act="aifix" title="Claude rewrites only the flagged parts">Fix with AI</button>
                            <button type="button" class="btn btn-ghost btn-sm" data-act="copy">Copy</button>
                            <span class="spacer"></span>
                            ${o.actions.map((a, i) => `<button type="button" class="btn ${a.primary ? 'btn-primary' : 'btn-ghost'} btn-sm" data-action="${i}">${esc(a.label)}</button>`).join('')}
                        </div>
                    </div>
                    <div class="pe-side">
                        ${preview ? '<div class="li-card"></div>' : ''}
                        <div class="card card-pad pe-quality"></div>
                    </div>
                </div>`;
            this.ta = this.root.querySelector('textarea');
            this.meters = this.root.querySelector('.pe-meters');
            this.previewEl = this.root.querySelector('.li-card');
            this.panel = new QualityPanel(this.root.querySelector('.pe-quality'), {
                onSelect: (m) => selectInTextarea(this.ta, m),
            });
            this._debouncedCheck = App.debounce(() => this.check(), 350);
            this.ta.addEventListener('input', () => this._changed(false));
            this.root.querySelector('[data-act="autofix"]').addEventListener('click', async () => {
                this.report = await runAutofix(() => this.text, (t) => { this.text = t; }, o.kind);
            });
            this.root.querySelector('[data-act="aifix"]').addEventListener('click', async (e) => {
                const r = await runAiFix(() => this.text, (t) => { this.text = t; }, o.kind, e.currentTarget).catch(() => null);
                if (r) { this.report = r; this.panel.render(r); }
            });
            this.root.querySelector('[data-act="copy"]').addEventListener('click', () => App.copy(this.text));
            this.root.querySelectorAll('[data-action]').forEach(btn => {
                btn.addEventListener('click', () => o.actions[+btn.dataset.action].onClick(this, btn));
            });
        }

        _changed(immediate) {
            this.meters.innerHTML = metersHtml(this.text, this.opts.kind);
            this._renderPreview();
            if (immediate) this.check(); else { this.panel.loading(); this._debouncedCheck(); }
            if (this.opts.onChange) this.opts.onChange(this.text);
        }

        _renderPreview() {
            if (!this.previewEl) return;
            const text = this.text;
            const cut = text.length > FOLD && !this.expanded;
            let shown = cut ? text.slice(0, FOLD).replace(/\s+\S*$/, '') : text;
            this.previewEl.innerHTML = `
                <div class="li-head">
                    <div class="li-avatar">${esc(initials(this.opts.author))}</div>
                    <div><div class="li-name">${esc(this.opts.author)}</div>
                    <div class="li-meta">${esc(this.opts.headline || 'Preview')} · now · 🌐</div></div>
                </div>
                <div class="li-body">${esc(shown)}${cut ? '<span class="li-more">…see more</span>' : ''}</div>
                ${text.length > FOLD ? `<div class="li-foldnote">${this.expanded ? 'Showing full post' : 'Readers see this much before "…see more"'}</div>` : ''}
                <div class="li-actions"><span>Like</span><span>Comment</span><span>Repost</span><span>Send</span></div>`;
            const more = this.previewEl.querySelector('.li-more');
            if (more) more.addEventListener('click', () => { this.expanded = true; this._renderPreview(); });
            if (this.expanded && !cut) {
                const note = this.previewEl.querySelector('.li-foldnote');
                if (note) note.addEventListener('click', () => { this.expanded = false; this._renderPreview(); });
            }
        }

        async check() {
            if (!this.text.trim()) {  // nothing to score yet
                this.report = null;
                const q = this.root.querySelector('.pe-quality');
                if (q) q.innerHTML = EMPTY_HINT;
                return null;
            }
            try {
                this.report = await checkQuality(this.text, this.opts.kind);
                this.panel.render(this.report);
            } catch (e) { /* offline: keep last report */ }
            return this.report;
        }

        focus() { this.ta.focus(); }
    }

    /* ── Attach the meter + buttons to an existing textarea ──────── */
    PostEditor.attach = function (textarea, panelEl, { kind = 'post' } = {}) {
        panelEl.innerHTML = `
            <div class="pe-meters"></div>
            <div class="pe-toolbar" style="margin-bottom:12px">
                <button type="button" class="btn btn-ghost btn-sm" data-act="autofix">Auto-fix</button>
                <button type="button" class="btn btn-ghost btn-sm" data-act="aifix">Fix with AI</button>
            </div>
            <div class="pe-quality"></div>`;
        const meters = panelEl.querySelector('.pe-meters');
        const panel = new QualityPanel(panelEl.querySelector('.pe-quality'), { onSelect: (m) => selectInTextarea(textarea, m) });
        const setText = (t) => { textarea.value = t; textarea.dispatchEvent(new Event('input', { bubbles: true })); };
        const refresh = async () => {
            meters.innerHTML = metersHtml(textarea.value, kind);
            if (!textarea.value.trim()) { panelEl.querySelector('.pe-quality').innerHTML = EMPTY_HINT; return; }
            try { panel.render(await checkQuality(textarea.value, kind)); } catch (e) { /* ignore */ }
        };
        const debounced = App.debounce(refresh, 350);
        textarea.addEventListener('input', () => { meters.innerHTML = metersHtml(textarea.value, kind); debounced(); });
        panelEl.querySelector('[data-act="autofix"]').addEventListener('click', async () => {
            panel.render(await runAutofix(() => textarea.value, setText, kind));
        });
        panelEl.querySelector('[data-act="aifix"]').addEventListener('click', async (e) => {
            const r = await runAiFix(() => textarea.value, setText, kind, e.currentTarget).catch(() => null);
            if (r) panel.render(r);
        });
        refresh();
        return { refresh };
    };

    window.PostEditor = PostEditor;
})();
