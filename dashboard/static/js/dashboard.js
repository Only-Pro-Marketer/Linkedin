/* ================================================================
   Pro Marketer — Dashboard JS
   Sidebar toggle, scroll-reveal, page animations, auto-refresh
   ================================================================ */

// ── Sidebar Toggle ─────────────────────────────────────────────
function toggleSidebar() {
    document.documentElement.classList.toggle('sidebar-collapsed');
    const collapsed = document.documentElement.classList.contains('sidebar-collapsed');
    localStorage.setItem('sidebar-collapsed', collapsed);
}

// Mobile menu
function toggleMobileMenu() {
    document.body.classList.toggle('sidebar-open');
}

// Close mobile menu on overlay click (handled inline) and on escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.body.classList.remove('sidebar-open');
    }
});

// ── Scroll Reveal ───────────���──────────────────────────────────
const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('revealed');
            revealObserver.unobserve(entry.target);
        }
    });
}, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));
});

// ── Stat Number Animation ──────────────────────────────────────
function animateValue(el, start, end, duration) {
    if (start === end) return;
    const range = end - start;
    const startTime = performance.now();

    function tick(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // Ease out cubic
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = Math.round(start + range * eased);
        el.textContent = current.toLocaleString();
        if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
}

function animateStats() {
    document.querySelectorAll('[data-animate-value]').forEach(el => {
        const target = parseInt(el.dataset.animateValue, 10);
        if (!isNaN(target)) {
            animateValue(el, 0, target, 600);
        }
    });
}

// ── Auto-refresh queue ─────────────────────────────────────────
if (window.location.pathname === '/') {
    setInterval(() => {
        if (typeof loadQueue === 'function') loadQueue();
    }, 60000);
}

// ── Init ──────��────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Animate stats on page load
    animateStats();
});
