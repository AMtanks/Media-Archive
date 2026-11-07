// Appearance: "system" follows Windows, or a fixed light/dark choice. Loaded in <head> so the first paint already uses the right theme.
(() => {
  const KEY = 'xarchive-theme';
  const media = matchMedia('(prefers-color-scheme: light)');
  let choice = 'system';
  try { choice = localStorage.getItem(KEY) || 'system'; } catch (_) { /* Falls back to the system theme. */ }
  const apply = () => {
    const theme = choice === 'system' ? (media.matches ? 'light' : 'dark') : choice;
    document.documentElement.dataset.theme = theme;
    document.querySelectorAll('[data-theme-choice]').forEach(button => button.setAttribute('aria-checked', String(button.dataset.themeChoice === choice)));
  };
  apply();
  media.addEventListener('change', apply);
  document.addEventListener('DOMContentLoaded', apply);
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-theme-choice]');
    if (!button) return;
    choice = button.dataset.themeChoice;
    try { localStorage.setItem(KEY, choice); } catch (_) { /* Applies for this session only. */ }
    document.documentElement.classList.add('theme-switching');
    apply();
    setTimeout(() => document.documentElement.classList.remove('theme-switching'), 50);
  });
})();
