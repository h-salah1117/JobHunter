// JobHunter — main.js
// Only English comments are allowed in code files.

// ── Auto-submit filter forms on select change ────────────────────────────────
document.querySelectorAll('form.auto-submit select').forEach(sel => {
  sel.addEventListener('change', () => sel.closest('form').submit());
});

// ── Manual refresh button tracking ───────────────────────────────────────────
function triggerRefresh(btn) {
  btn.disabled = true;
  const nativeText = btn.textContent;
  btn.textContent = 'Refreshing…';
  
  fetch('/api/refresh', { method: 'POST' })
    .then(r => r.json())
    .then(() => {
      btn.textContent = 'Done ✓';
      showToast('Market metrics synchronized successfully!', 'success');
      setTimeout(() => {
        window.location.reload();
      }, 1000);
    })
    .catch(() => {
      showToast('Failed to refresh data stream.', 'error');
      btn.textContent = nativeText;
      btn.disabled = false;
    });
}

// ── Job card copy link utility ───────────────────────────────────────────────
document.querySelectorAll('.copy-link-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const url = btn.dataset.url;
    if (!url) return;
    navigator.clipboard.writeText(url).then(() => {
      const original = btn.textContent;
      btn.textContent = 'Copied!';
      showToast('Link saved to clipboard.', 'info');
      setTimeout(() => (btn.textContent = original), 2000);
    });
  });
});

// ── Clear search field on escape key ─────────────────────────────────────────
document.querySelectorAll('input[name="q"]').forEach(input => {
  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      input.value = '';
      input.closest('form').submit();
    }
  });
});

// ── Modern Toast notification helper syncing with identity scheme ─────────────
function showToast(message, type = 'info') {
  const colors = {
    info:    'border-brand-teal text-brand-teal bg-brand-surface',
    success: 'border-emerald-500 text-emerald-400 bg-brand-surface',
    error:   'border-rose-500 text-rose-400 bg-brand-surface',
  };
  
  const toast = document.createElement('div');
  toast.className = `fixed bottom-6 right-6 z-50 px-5 py-3 rounded-xl border shadow-2xl text-sm font-medium transition-all duration-300 opacity-0 transform translate-y-2 flex items-center gap-2 ${colors[type] || colors.info}`;
  toast.innerHTML = `<span>⚡</span> <span>${message}</span>`;
  
  document.body.appendChild(toast);
  
  // Smooth fade-in animation trigger
  setTimeout(() => {
    toast.classList.remove('opacity-0', 'translate-y-2');
  }, 50);

  // Smooth teardown transition
  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-y-2');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}