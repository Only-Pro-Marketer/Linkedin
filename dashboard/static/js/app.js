/* ================================================================
   Content Engine — shared UI helpers (loaded on every page)
   App.api        fetch JSON, show errors as toasts
   App.confirm    promise-based confirm dialog (use for anything that publishes)
   App.fmtDate    format a UTC ISO string in the posting timezone
   App.copy       copy to clipboard with a toast
   App.debounce   debounce helper
   App.qualityBadge  HTML for the Ready / Review / Needs fixes badge
   ================================================================ */
(function () {
    const App = {};

    App.api = async function (url, { method = 'GET', body, quiet = false } = {}) {
        const opts = { method, headers: {} };
        if (body !== undefined) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        let res;
        try {
            res = await fetch(url, opts);
        } catch (e) {
            if (!quiet) showToast('Network error — is the app running?', 'error');
            throw e;
        }
        let data = null;
        try { data = await res.json(); } catch (e) { data = null; }
        if (!res.ok) {
            const msg = (data && (data.error || data.detail)) || `Request failed (${res.status})`;
            if (!quiet) showToast(typeof msg === 'string' ? msg : 'Request failed', 'error');
            const err = new Error(typeof msg === 'string' ? msg : 'Request failed');
            err.status = res.status;
            err.data = data;
            throw err;
        }
        return data;
    };

    App.confirm = function ({ title = 'Are you sure?', message = '', confirmText = 'Confirm',
                              cancelText = 'Cancel', danger = false } = {}) {
        return new Promise(resolve => {
            const overlay = document.createElement('div');
            overlay.className = 'cm-overlay';
            overlay.setAttribute('role', 'dialog');
            overlay.setAttribute('aria-modal', 'true');
            overlay.innerHTML = `
                <div class="cm-box">
                    <div class="cm-title">${esc(title)}</div>
                    ${message ? `<div class="cm-msg">${esc(message)}</div>` : ''}
                    <div class="cm-actions">
                        <button type="button" class="btn btn-ghost btn-md" data-act="cancel">${esc(cancelText)}</button>
                        <button type="button" class="btn ${danger ? 'btn-danger-solid' : 'btn-primary'} btn-md" data-act="ok">${esc(confirmText)}</button>
                    </div>
                </div>`;
            const done = (value) => {
                document.removeEventListener('keydown', onKey, true);
                overlay.remove();
                resolve(value);
            };
            const onKey = (e) => {
                if (e.key === 'Escape') { e.stopPropagation(); done(false); }
                if (e.key === 'Enter') { e.preventDefault(); done(true); }
            };
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) done(false);
                const act = e.target.closest('[data-act]');
                if (act) done(act.dataset.act === 'ok');
            });
            document.addEventListener('keydown', onKey, true);
            document.body.appendChild(overlay);
            overlay.querySelector('[data-act="ok"]').focus();
        });
    };

    App.fmtDate = function (iso, opts = {}) {
        if (!iso) return '';
        try {
            return new Intl.DateTimeFormat(undefined, Object.assign(
                { timeZone: (window.APP && APP.tz) || undefined, dateStyle: 'medium', timeStyle: 'short' }, opts
            )).format(new Date(iso));
        } catch (e) { return new Date(iso).toLocaleString(); }
    };

    App.relTime = function (iso) {
        if (!iso) return '';
        const diff = (Date.now() - new Date(iso).getTime()) / 1000;
        const abs = Math.abs(diff);
        const fmt = (n, unit) => `${Math.round(n)} ${unit}${Math.round(n) === 1 ? '' : 's'}`;
        let out;
        if (abs < 60) out = 'just now';
        else if (abs < 3600) out = fmt(abs / 60, 'minute');
        else if (abs < 86400) out = fmt(abs / 3600, 'hour');
        else out = fmt(abs / 86400, 'day');
        if (out === 'just now') return out;
        return diff >= 0 ? `${out} ago` : `in ${out}`;
    };

    App.copy = async function (text, label = 'Copied to clipboard') {
        try {
            await navigator.clipboard.writeText(text);
            showToast(label);
        } catch (e) {
            showToast('Copy failed — select the text and copy it manually', 'error');
        }
    };

    App.debounce = function (fn, ms = 300) {
        let t;
        return function (...args) {
            clearTimeout(t);
            t = setTimeout(() => fn.apply(this, args), ms);
        };
    };

    App.busy = function (btn, on, label) {
        if (!btn) return;
        if (on) {
            btn.dataset.label = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = `<span class="spin"></span>${label ? ' ' + esc(label) : ''}`;
        } else {
            btn.disabled = false;
            if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
        }
    };

    App.parseJSON = function (value, fallback = null) {
        if (value == null) return fallback;
        if (typeof value === 'object') return value;
        try { return JSON.parse(value); } catch (e) { return fallback; }
    };

    const Q_LABEL = { ready: 'Ready', review: 'Review', fix: 'Needs fixes' };
    App.qualityBadge = function (report, score) {
        const r = App.parseJSON(report, null);
        const status = r ? r.status : null;
        const s = r ? r.score : score;
        if (!status) return '<span class="q-badge q-none"><span class="q-dot"></span>Not checked</span>';
        const n = (r.blockers || []).length;
        const title = n ? `${n} issue${n > 1 ? 's' : ''} to fix before posting` : `Quality score ${s}/100`;
        return `<span class="q-badge q-${status}" title="${esc(title)}"><span class="q-dot"></span>${Q_LABEL[status] || status} · ${s}</span>`;
    };

    window.App = App;
    window.confirmModal = App.confirm;
})();
