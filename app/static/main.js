/* ═══════════════════════════════════════════════════════════════════════════
   JobHunter — main.js v3.0
   Unified JavaScript utilities
   ═══════════════════════════════════════════════════════════════════════════ */

// ── Auto-submit filter forms on select change ────────────────────────────
document.querySelectorAll('form.auto-submit select').forEach(sel => {
  sel.addEventListener('change', () => sel.closest('form').submit());
});

// ── Manual refresh button ────────────────────────────────────────────────
function triggerRefresh(btn) {
  btn.disabled = true;
  const nativeText = btn.textContent;
  btn.textContent = 'Refreshing…';

  fetch('/api/refresh', { method: 'POST' })
    .then(r => r.json())
    .then(() => {
      btn.textContent = 'Done ✓';
      showToast('Data synchronized successfully!', 'success');
      setTimeout(() => window.location.reload(), 1000);
    })
    .catch(() => {
      showToast('Failed to refresh data.', 'error');
      btn.textContent = nativeText;
      btn.disabled = false;
    });
}

// ── Copy link utility ────────────────────────────────────────────────────
document.querySelectorAll('.copy-link-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const url = btn.dataset.url;
    if (!url) return;
    navigator.clipboard.writeText(url).then(() => {
      const original = btn.textContent;
      btn.textContent = 'Copied!';
      showToast('Link copied to clipboard.', 'info');
      setTimeout(() => (btn.textContent = original), 2000);
    });
  });
});

// ── Clear search on Escape ───────────────────────────────────────────────
document.querySelectorAll('input[name="q"]').forEach(input => {
  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      input.value = '';
      input.closest('form').submit();
    }
  });
});

// ── Toast notification system (single source of truth) ───────────────────
function showToast(message, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const icons = { info: '💡', success: '✓', error: '✕' };
  toast.innerHTML = `<span>${icons[type] || icons.info}</span> <span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('removing');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}