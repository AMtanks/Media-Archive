'use strict';
const $ = (selector) => document.querySelector(selector);
const token = $('meta[name="app-token"]').content;
let state, currentView = 'library', settingsLoaded = false, removeId = null, toastTimer, refreshing = false;
let mediaResult = null, mediaLoading = false, mediaRequest = 0;
let authorPlatform = 'all', mediaPlatform = 'all';
let recentSignature = null, viewerItems = [], viewerIndex = 0, viewerDeleting = false;
const selectedMedia = new Set(), GALLERY_BATCH = 30;
let renderedMediaCount = 0;
let gallerySignature = '', layoutFrame = 0, selectionDrag = null, suppressPreview = false, deletingMedia = false;
let lastPointerPoint = null, galleryHoverResumePoint = null, eventSignature = "", lastGalleryLoad = 0;
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const accountName = (handle) => (handle || '').includes(':') ? handle.split(':').slice(1).join(':') : (handle || '');
const platformName = (handle) => handle?.startsWith('instagram:') ? 'Instagram' : handle?.startsWith('weibo:') ? 'Weibo' : 'X';
const platformKey = (handle) => handle?.startsWith('instagram:') ? 'instagram' : handle?.startsWith('weibo:') ? 'weibo' : 'twitter';
const profileUrl = (handle) => handle?.startsWith('instagram:') ? `https://www.instagram.com/${encodeURIComponent(accountName(handle))}/` : handle?.startsWith('weibo:') ? `https://weibo.com/u/${encodeURIComponent(accountName(handle))}` : `https://x.com/${encodeURIComponent(handle)}/media`;
const number = (value) => Number(value || 0).toLocaleString(window.appLanguage || 'zh-CN');
function bytes(value) { let n = Number(value || 0), i = 0; const units = ['B','KB','MB','GB','TB']; while(n >= 1024 && i < 4) { n /= 1024; i++; } return `${n.toFixed(i ? 1 : 0)} ${units[i]}`; }
function time(value, short = false) { if (!value) return '尚未完成'; const d = new Date(value); return d.toLocaleString(window.appLanguage || 'zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',...(short ? {} : {year:'numeric'})}); }
function toast(message, error = false) { clearTimeout(toastTimer); $('#toast').textContent = message; $('#toast').classList.remove('hidden'); $('#toast').classList.toggle('error', error); toastTimer = setTimeout(() => $('#toast').classList.add('hidden'), error ? 8000 : 4000); }
async function api(path, method = 'GET', body) {
  const response = await fetch(`/api/${path}`, {method, headers:{'X-App-Token': token, ...(body === undefined ? {} : {'Content-Type':'application/json'})}, ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  let data; try { data = await response.json(); } catch { throw new Error('应用服务暂时无法连接，请重试'); }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请检查填写内容后重试');
  return data;
}
function view(name) {
  currentView = name;
  document.querySelectorAll('.view').forEach((el) => el.classList.toggle('hidden', el.id !== `view-${name}`));
  document.querySelectorAll('[data-view]').forEach((el) => el.classList.toggle('active', el.dataset.view === name));
  const names = {library:'推主',activity:'同步记录',settings:'设置',media:'媒体'};
  $('#breadcrumb').textContent = names[name];
  location.hash = name;
  window.scrollTo({top:0,behavior:'instant'});
  if (state && name === 'media') loadMedia(mediaResult ? {keepPosition:true} : {});
  if (state && name === 'settings' && !settingsLoaded) fillSettings();
}
function badge(status) {
  const labels = {idle:'等待同步',queued:'已加入队列',running:'正在扫描',error:'需要重试',success:'本轮完成',cancelled:'已停止',interrupted:'上次中断'};
  const marks = {running:'↻',success:'✓',error:'!',queued:'◷',idle:'·',cancelled:'Ⅱ',interrupted:'Ⅱ'};
  return `<span class="state ${esc(status)}"><span class="state-dot" aria-hidden="true"></span>${labels[status] || esc(status)}</span>`;
}
function renderAuthors() {
  if (!state) return;
  const search = $('#search-authors').value.trim().toLowerCase().replace(/^@/, '');
  const authors = state.authors.filter((a) => (authorPlatform === 'all' || platformKey(a.handle) === authorPlatform) && (a.handle + " " + a.display_name).toLowerCase().includes(search));
  $('#result-count').textContent = authors.length;
  $('#table-foot').textContent = `显示 ${authors.length} 位推主 · 按添加顺序`;
  $('#authors-body').innerHTML = authors.length ? authors.map((a) => {
    const busy = ['queued','running'].includes(a.status);
    const status = a.status === 'idle' && a.last_success ? 'success' : a.status;
    return `<tr><td><div class="author-cell"><span class="avatar" aria-hidden="true">${a.avatar_url ? `<img src="${esc(a.avatar_url)}" alt="" loading="lazy">` : esc(a.handle[0].toUpperCase())}</span><div><a href="${esc(profileUrl(a.handle))}" target="_blank" rel="noopener noreferrer">${esc(a.display_name || accountName(a.handle))}</a><small class="author-handle">${platformName(a.handle)} · @${esc(accountName(a.handle))}</small><small><button class="text-button" data-action="manage-media" data-id="${a.id}">查看媒体</button></small></div></div></td><td>${badge(status)}${a.error ? `<div class="state-note" title="${esc(a.error)}">${esc(a.error)}</div>${a.retry_count && a.enabled && state.settings.automatic ? `<div class="state-note">${time(a.next_run,true)} 自动重试</div>` : ''}` : `<div class="state-note">${a.status === 'queued' ? esc(a.queue_reason || '等待前面的扫描完成') : a.next_run && a.enabled && state.settings.automatic ? `下次 ${time(a.next_run, true)}` : a.enabled ? '首次扫描历史内容' : '自动同步已暂停'}</div>`}</td><td class="numeric"><strong>${number(a.files)}</strong><div class="muted small">${bytes(a.bytes)}</div></td><td><span>${time(a.last_success, true)}</span>${a.last_success ? '<div class="muted small">本地时间</div>' : ''}</td><td class="center"><label class="switch"><input type="checkbox" data-toggle="${a.id}" aria-label="自动同步 @${esc(accountName(a.handle))}" ${a.enabled ? 'checked' : ''}><span class="switch-track"></span></label></td><td><div class="row-actions">${a.status === 'queued' ? `<button data-action="sync" data-id="${a.id}">立即同步</button><button data-action="cancel" data-id="${a.id}">停止</button>` : `<button data-action="${busy ? 'cancel' : 'sync'}" data-id="${a.id}">${busy ? '停止' : '同步'}</button>`}<button class="quiet" data-action="full" data-id="${a.id}" ${busy ? 'disabled' : ''} title="重新检查历史内容，跳过已下载文件">历史补查</button><button class="icon-button" data-action="remove" data-id="${a.id}" ${busy ? 'disabled' : ''} aria-label="移出 @${esc(accountName(a.handle))}">×</button></div></td></tr>`;
  }).join('') : `<tr><td colspan="6" class="empty-table"><strong>${search ? '没有找到这个推主' : '收藏从一位推主开始'}</strong>${search ? '试试其他账号名称。' : '点击“添加推主”，输入账号或主页链接。'}</td></tr>`;
}
// The author table is capped at ten visible rows; the rest scroll inside the table box.
const authorsBox = $('#authors-wrap'), authorsBody = $('#authors-body');
function fitAuthorRows() {
  const rows = authorsBody.rows;
  if (!rows.length || rows[0].cells.length !== 6) { authorsBox.style.maxHeight = ''; return; }
  let height = authorsBox.querySelector('thead').offsetHeight + 2;
  for (let i = 0; i < Math.min(10, rows.length); i++) height += rows[i].offsetHeight;
  authorsBox.style.maxHeight = `${height}px`;
}
new ResizeObserver(fitAuthorRows).observe(authorsBody);
// Thumbnails stay transparent until fully downloaded, then fade in, so a half-loaded image never paints row by row.
document.addEventListener('load', event => { if (event.target.matches?.('img.media-thumb')) event.target.classList.add('loaded'); }, true);
// Gallery cards can finish loading while virtualised out of the DOM, where the events above never arrive. Settle them on re-attach.
function settleThumb(card) {
  const img = card.querySelector('img.media-thumb');
  if (!img || !img.complete || img.classList.contains('loaded')) return;
  if (img.naturalWidth) img.classList.add('loaded');
  else img.closest('.preview-surface')?.classList.add('failed');
}
// Author filter: a custom list (10 rows, then scroll) backed by the hidden native select, which keeps the value and change event.
const authorPicker = $('#author-picker'), authorNative = $('#media-author');
const authorButton = authorPicker.querySelector('.picker-button'), authorList = authorPicker.querySelector('.picker-list');
function syncAuthorPicker() {
  authorButton.firstElementChild.textContent = authorNative.selectedOptions[0]?.textContent || '全部推主';
  if (authorList.classList.contains('hidden')) return;
  authorList.innerHTML = [...authorNative.options].map(o => `<div class="picker-option" role="option" data-value="${esc(o.value)}" aria-selected="${o.selected}">${esc(o.textContent)}</div>`).join('');
}
function setAuthorPicker(open) {
  if (open === !authorList.classList.contains('hidden')) return;
  authorList.classList.toggle('hidden', !open);
  authorButton.setAttribute('aria-expanded', String(open));
  if (open) { syncAuthorPicker(); authorList.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest'}); }
}
function chooseAuthor(value) {
  setAuthorPicker(false);
  if (authorNative.value === value) return;
  authorNative.value = value;
  syncAuthorPicker();
  authorNative.dispatchEvent(new Event('change'));
}
authorButton.addEventListener('click', () => setAuthorPicker(authorList.classList.contains('hidden')));
// Keep focus on the button while choosing, otherwise focusout closes the list before the click lands.
authorList.addEventListener('pointerdown', event => event.preventDefault());
authorList.addEventListener('click', event => { const option = event.target.closest('.picker-option'); if (option) chooseAuthor(option.dataset.value); });
document.addEventListener('pointerdown', event => { if (!authorPicker.contains(event.target)) setAuthorPicker(false); });
authorPicker.addEventListener('focusout', event => { if (!authorPicker.contains(event.relatedTarget)) setAuthorPicker(false); });
authorPicker.addEventListener('keydown', event => {
  const open = !authorList.classList.contains('hidden');
  if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); setAuthorPicker(false); authorButton.focus(); return; }
  if (!['ArrowDown','ArrowUp','Home','End','Enter',' '].includes(event.key)) return;
  event.preventDefault();
  if (!open) { setAuthorPicker(true); return; }
  const items = [...authorList.children];
  let index = items.findIndex(el => el.classList.contains('active'));
  if (index < 0) index = items.findIndex(el => el.getAttribute('aria-selected') === 'true');
  if (event.key === 'Enter' || event.key === ' ') { if (items[index]) chooseAuthor(items[index].dataset.value); authorButton.focus(); return; }
  index = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : index + (event.key === 'ArrowDown' ? 1 : -1);
  index = Math.max(0, Math.min(items.length - 1, index));
  items.forEach((el, i) => el.classList.toggle('active', i === index));
  items[index]?.scrollIntoView({block:'nearest'});
});
new MutationObserver(syncAuthorPicker).observe(authorNative, {childList:true});
function imageMarkup(item, fullHeight = true) {
  return `<span class="preview-surface ${fullHeight ? '' : 'cropped'}"><img class="media-thumb" src="${esc(item.thumbnail_url)}" alt="${esc(item.kind === 'video' ? '视频封面' : '已保存图片')}" loading="lazy" decoding="async"><span class="preview-fallback">${item.kind === 'video' ? '▶' : '▧'}<small>预览暂不可用，点击打开文件</small></span>${item.kind === 'video' ? '<span class="play-mark" aria-hidden="true">▶</span>' : ''}</span>`;
}
let viewerLoad = 0;
// Preloaded originals, nearest-first. Holding the Image keeps its decoded bitmap ready; the cap bounds memory.
const VIEWER_AHEAD = 10, viewerWarm = new Map();
function warmViewerImage(item) {
  if (!item || item.kind === 'video') return;
  const url = item.content_url;
  if (viewerWarm.has(url)) { const img = viewerWarm.get(url); viewerWarm.delete(url); viewerWarm.set(url, img); return; }
  const img = new Image();
  img.decoding = 'async';
  img.src = url;
  img.decode().catch(() => {});
  viewerWarm.set(url, img);
  while (viewerWarm.size > VIEWER_AHEAD + 6) viewerWarm.delete(viewerWarm.keys().next().value);
}
function showViewer(items, index) {
  viewerItems = items;
  viewerIndex = index;
  const item = items[index];
  if (!item) return;
  $('#viewer-author').textContent = `${item.display_name || ''} ${platformName(item.handle)} · @${accountName(item.handle)}`.trim();
  $('#viewer-meta').textContent = `${time(item.published_at)} · ${bytes(item.size)} · 原文件`;
  const stage = $('#viewer-stage'), load = ++viewerLoad;
  if (item.kind === 'video') stage.innerHTML = `<video controls playsinline preload="metadata" controlslist="nodownload noremoteplayback" disablepictureinpicture poster="${esc(item.thumbnail_url)}" src="${esc(item.content_url)}"></video>`;
  else {
    // Keep the previous picture until the new original is fully decoded, so it never paints top-down over a blank stage.
    // If decoding takes a moment, show the (already cached) thumbnail in the meantime.
    // Reuse the preloaded (already decoded) element when there is one.
    const img = viewerWarm.get(item.content_url) || Object.assign(new Image(), {src:item.content_url});
    img.alt = '已保存的原图';
    const placeholder = setTimeout(() => {
      if (load !== viewerLoad) return;
      stage.innerHTML = `<img class="viewer-placeholder" src="${esc(item.thumbnail_url)}" alt="">`;
    }, 120);
    const show = () => { clearTimeout(placeholder); if (load === viewerLoad) stage.replaceChildren(img); };
    // A fully downloaded image paints whole, so swap as soon as the bytes are in (decode() can stall while the window is hidden).
    if (img.complete) show();
    else { img.addEventListener('load', show, {once:true}); img.addEventListener('error', show, {once:true}); img.decode().then(show, () => {}); }
  }
  // Preload the next 10 (and the previous one) so fast paging never waits on the network.
  [index - 1, ...Array.from({length:VIEWER_AHEAD}, (_, i) => index + 1 + i)].forEach(i => warmViewerImage(items[i]));
  const video = $('#viewer-stage video');
  if (video) {
    try {
      const saved = JSON.parse(localStorage.getItem('xarchive-video-volume') || 'null');
      if (saved && Number.isFinite(saved.volume)) video.volume = Math.max(0, Math.min(1, saved.volume));
      if (saved && typeof saved.muted === 'boolean') video.muted = saved.muted;
    } catch (_) { /* Playback still works if local storage is unavailable. */ }
    video.addEventListener('volumechange', () => {
      try { localStorage.setItem('xarchive-video-volume', JSON.stringify({volume:video.volume, muted:video.muted})); } catch (_) {}
    });
  }
  $('#viewer-counter').textContent = `${index + 1} / ${items.length}`;
  renderStrip(items, index);
  $('[data-action="viewer-prev"]').disabled = index === 0;
  $('[data-action="viewer-next"]').disabled = index + 1 === items.length;
  document.body.classList.add('gallery-hover-paused');
  if (!$('#viewer-dialog').open) $('#viewer-dialog').showModal();
  if (video) video.play().catch(() => {});
}
// Filmstrip under the viewer (Photos-style): narrow thumbs either side, the current one wider at its real aspect.
// Nodes are keyed by media id and only moved with transforms, so paging, clicks and deletions glide instead of re-rendering.
const STRIP_RADIUS = 24, STRIP_W = 26, STRIP_H = 42, STRIP_FOCUS_H = 52, STRIP_GAP = 2, STRIP_FOCUS_GAP = 8;
const stripNodes = new Map();
let stripItems = null;
function stripFocusWidth(node) {
  const img = node.firstElementChild, aspect = img.naturalWidth ? img.naturalWidth / img.naturalHeight : .75;
  return Math.round(Math.max(STRIP_W + 8, Math.min(STRIP_FOCUS_H * 1.8, STRIP_FOCUS_H * aspect)));
}
function renderStrip(items, index) {
  const strip = $('#viewer-strip');
  if (stripItems !== items) { strip.replaceChildren(); stripNodes.clear(); stripItems = items; }
  const from = Math.max(0, index - STRIP_RADIUS), to = Math.min(items.length - 1, index + STRIP_RADIUS);
  const keep = new Set(items.slice(from, to + 1).map(item => item.media_id));
  stripNodes.forEach((node, id) => { if (!keep.has(id)) { node.remove(); stripNodes.delete(id); } });
  const focusNode = stripNodes.get(items[index].media_id);
  const focusWidth = focusNode ? stripFocusWidth(focusNode) : STRIP_FOCUS_H * .75;
  for (let i = from; i <= to; i++) {
    const item = items[i];
    let node = stripNodes.get(item.media_id), fresh = false;
    if (!node) {
      node = document.createElement('button');
      node.type = 'button';
      node.className = 'strip-item no-anim';
      node.tabIndex = -1;
      const img = new Image();
      img.alt = ''; img.draggable = false; img.decoding = 'async';
      img.addEventListener('load', () => { img.classList.add('loaded'); if (stripItems === viewerItems && viewerItems[viewerIndex]?.media_id === item.media_id) renderStrip(viewerItems, viewerIndex); }, {once:true});
      img.src = item.thumbnail_url;
      node.append(img);
      stripNodes.set(item.media_id, node);
      strip.append(node);
      fresh = true;
    }
    const focus = i === index, width = focus ? (node === focusNode ? focusWidth : stripFocusWidth(node)) : STRIP_W, height = focus ? STRIP_FOCUS_H : STRIP_H;
    const left = focus ? -width / 2
      : i > index ? focusWidth / 2 + STRIP_FOCUS_GAP + (i - index - 1) * (STRIP_W + STRIP_GAP)
      : -focusWidth / 2 - STRIP_FOCUS_GAP - (index - i) * STRIP_W - (index - i - 1) * STRIP_GAP;
    node.dataset.index = i;
    node.classList.toggle('current', focus);
    node.setAttribute('aria-label', `第 ${i + 1} 份`);
    node.style.width = `${width}px`;
    node.style.height = `${height}px`;
    node.style.transform = `translate(${left}px, -50%)`;
    if (fresh) { void node.offsetWidth; node.classList.remove('no-anim'); }
  }
}
$('#viewer-strip').addEventListener('click', event => {
  const node = event.target.closest('.strip-item');
  if (node && stripItems && !viewerDeleting) showViewer(stripItems, Number(node.dataset.index));
});
$('#viewer-dialog').addEventListener('close', () => {
  $('#viewer-stage').innerHTML = '';
  $('#viewer-strip').replaceChildren(); stripNodes.clear(); stripItems = null;
  // Modal focus restoration is not a fresh hover on the original card.
  galleryHoverResumePoint = lastPointerPoint;
  document.body.classList.add('gallery-hover-paused');
});
$('#viewer-dialog').addEventListener('click', event => {
  const rect = event.currentTarget.getBoundingClientRect();
  if (event.target === event.currentTarget && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) event.currentTarget.close();
});
// Wheel inside the viewer steps to the previous/next item; the page behind the modal never scrolls.
let viewerWheelAcc = 0, viewerWheelLast = 0, viewerWheelStep = 0;
$('#viewer-dialog').addEventListener('wheel', event => {
  event.preventDefault();
  const now = performance.now();
  const dy = event.deltaMode === 1 ? event.deltaY * 33 : event.deltaMode === 2 ? event.deltaY * innerHeight : event.deltaY;
  if (now - viewerWheelLast > 150) viewerWheelAcc = 0;
  viewerWheelLast = now;
  if (viewerDeleting || !dy) return;
  // A mouse notch (|delta| >= 50) is one deliberate step, so fast spinning pages as fast as the wheel turns.
  // Touchpads send a stream of small deltas: accumulate them and pace steps so a fling doesn't skip dozens.
  let steps;
  if (Math.abs(dy) >= 50) { steps = Math.sign(dy); viewerWheelAcc = 0; }
  else {
    if (Math.sign(dy) !== Math.sign(viewerWheelAcc)) viewerWheelAcc = 0;
    viewerWheelAcc += dy;
    if (Math.abs(viewerWheelAcc) < 60 || now - viewerWheelStep < 120) return;
    steps = Math.sign(viewerWheelAcc); viewerWheelAcc = 0;
  }
  viewerWheelStep = now;
  const index = Math.max(0, Math.min(viewerItems.length - 1, viewerIndex + steps));
  if (index !== viewerIndex) showViewer(viewerItems, index);
}, {passive: false});
document.addEventListener('error', event => {
  if (event.target.matches('img.media-thumb')) event.target.closest('.preview-surface')?.classList.add('failed');
}, true);
function eventMarkup(event) { return `<div class="event"><span class="status-dot ${event.level === 'success' ? 'connected' : ''}"></span><div><div class="event-message ${event.level === 'error' ? 'danger' : ''}">${esc(event.message)}</div><div class="event-time">${time(event.created_at)}</div></div></div>`; }
function updateGalleryAuthors() {
  if (!state) return;
  const s = state;
  const galleryAuthors = s.authors.filter(a => a.gallery_available && (mediaPlatform === 'all' || platformKey(a.handle) === mediaPlatform));
  const authorSelect = $('#media-author');
  const previousAuthor = authorSelect.value;
  if (authorSelect.dataset.ids !== galleryAuthors.map(a => `${a.id}:${a.handle}:${a.display_name}`).join(',')) {
    authorSelect.innerHTML = '<option value="0">全部推主</option>' + galleryAuthors.map(a => `<option value="${a.id}">${esc(a.display_name || accountName(a.handle))} · ${platformName(a.handle)} @${esc(accountName(a.handle))}</option>`).join('');
    authorSelect.value = [...authorSelect.options].some(o => o.value === previousAuthor) ? previousAuthor : '0';
    authorSelect.dataset.ids = galleryAuthors.map(a => `${a.id}:${a.handle}:${a.display_name}`).join(',');
    if (authorSelect.value !== previousAuthor) { mediaResult = null; selectedMedia.clear(); renderSelection(); }
  }
  syncAuthorPicker();
}
function setPlatform(group, platform) {
  if (!['all','twitter','instagram','weibo'].includes(platform)) return;
  if (group === 'authors') {
    if (authorPlatform === platform) return;
    authorPlatform = platform;
    renderAuthors();
  } else if (group === 'media') {
    if (mediaPlatform === platform) return;
    mediaPlatform = platform;
    updateGalleryAuthors();
    mediaResult = null;
    selectedMedia.clear(); renderSelection();
    if (currentView === 'media') loadMedia();
  } else return;
  document.querySelectorAll(`[data-platform-group="${group}"] [data-platform]`).forEach(button => button.setAttribute('aria-pressed', String(button.dataset.platform === platform)));
}
document.querySelectorAll('.platform-filter').forEach(group => group.addEventListener('click', event => {
  const button = event.target.closest('button[data-platform]');
  if (button) setPlatform(group.dataset.platformGroup, button.dataset.platform);
}));
function render() {
  const s = state;
  $('#metric-authors').textContent = number(s.totals.authors);
  $('#metric-enabled').textContent = `${s.authors.filter((a) => a.enabled).length} 位启用自动同步`;
  $('#metric-files').textContent = number(s.totals.files);
  $('#metric-bytes').textContent = bytes(s.totals.bytes);
  $('#metric-sync').textContent = s.settings.automatic ? '已开启' : '已暂停';
  $('#metric-interval').textContent = s.settings.automatic ? `每 ${s.settings.interval_minutes} 分钟 · 应用运行时` : '可在下载设置中开启';
  $('#nav-count').textContent = s.totals.authors;
  $('#engine-version').textContent = `gdl ${s.engine_version}`;
  $('#auth-dot').classList.toggle('connected', s.credentials_saved);
  $('#auth-label').textContent = s.credentials_saved ? 'X 登录凭证已保存' : '尚未连接 X 账号';
  $('#settings-auth-status').textContent = s.credentials_saved ? '凭证已保存' : '尚未连接';
  for (const platform of ['instagram','weibo']) {
    $(`#${platform}-auth-status`).textContent = s.platform_credentials?.[platform] ? '凭证已保存' : '尚未连接';
    $(`[data-action="login-platform"][data-platform="${platform}"]`).disabled = !s.desktop_login;
  }
  $('#login-banner').classList.toggle('hidden', s.credentials_saved);
  $('#desktop-login').disabled = !s.desktop_login;
  $('#pick-folder').classList.toggle('hidden', !s.folder_picker);
  if (!s.desktop_login) $('#login-hint').textContent = '当前为浏览器模式。请使用“手动填写 Cookie”，或从桌面启动器打开应用。';
  $('#sync-all').disabled = !s.authors.some((a) => a.enabled && !['running','queued'].includes(a.status) && (platformName(a.handle) === 'X' ? s.credentials_saved : s.platform_credentials?.[a.handle.split(':')[0]]));
  updateGalleryAuthors();
  $('#excluded-count').textContent = `已忽略 ${number(s.totals.excluded)} 个文件`;
  renderAuthors();
  const signature = s.recent.slice(0,6).map(item => `${item.media_id}:${item.thumbnail_url}`).join(',');
  if (signature !== recentSignature) {
    recentSignature = signature;
    $('#recent-files').innerHTML = s.recent.length ? s.recent.slice(0,6).map((item,index) => `<button class="recent-tile" data-action="preview-recent" data-index="${index}" aria-label="预览 ${esc(item.kind === 'video' ? '视频' : '图片')}，发文 ${esc(time(item.published_at))}">${imageMarkup(item, false)}<span class="recent-caption">${item.kind === 'video' ? '▶ ' : ''}${time(item.published_at,true)}<small>${esc(item.display_name || item.handle || '')}</small></span></button>`).join('') : '<div class="empty-inline"><strong>还没有保存的媒体</strong>连接 X 后同步推主，这里会显示图片和视频封面。</div>';
  }
  const eventsKey = s.events.map(e => e.id).join(',');
  if (eventsKey !== eventSignature || !$('#live-events').innerHTML) {
    eventSignature = eventsKey;
    const live = $('#live-events'), scroll = live.scrollTop;
    live.innerHTML = s.events.length ? s.events.map(eventMarkup).join('') : '<div class="empty-inline"><strong>一切准备就绪</strong>添加推主并连接 X，这里会显示实时下载进展。</div>';
    live.scrollTop = scroll;
    $('#all-events').innerHTML = s.events.length ? s.events.map(eventMarkup).join('') : '<div class="empty-inline">暂无日志。开始同步后，任务进展会显示在这里。</div>';
  }
  $('#runs-body').innerHTML = s.runs.length ? s.runs.map((r) => `<tr><td><strong>@${esc(r.handle)}</strong><div class="muted small">${r.mode === 'full' ? '历史扫描' : '增量补查'}</div></td><td>${badge(r.status)}${r.error ? `<div class="event-detail">${esc(r.error)}</div>` : ''}</td><td>${time(r.started_at)}${r.finished_at ? `<div class="muted small">结束 ${time(r.finished_at,true)}</div>` : ''}</td><td class="numeric">${number(r.downloaded)}</td><td class="numeric muted">${number(r.skipped)}</td></tr>`).join('') : '<tr><td colspan="5" class="empty-table"><strong>还没有同步记录</strong>第一次扫描完成后，可在这里查看新增文件和跳过的数量。</td></tr>';
  if (!settingsLoaded) fillSettings();
  if (currentView === 'media' && !mediaResult && !mediaLoading) loadMedia();
  const catalogSignature = s.authors.map(a => `${a.id}:${a.files}:${a.gallery_available}`).join(',') + ':' + s.totals.excluded;
  if (currentView === 'media' && gallerySignature && catalogSignature !== gallerySignature && !mediaLoading && !deletingMedia && !selectedMedia.size && !selectionDrag && (Date.now() - lastGalleryLoad > 30000 || !s.authors.some(a => a.status === 'running'))) loadMedia({keepPosition:true});
}
function fillSettings() {
  const s = state.settings;
  $('#download-dir').value = s.download_dir;
  $('#concurrency').value = s.download_concurrency || 4;
  $('#interval').value = s.interval_minutes;
  $('#overlap').value = s.overlap_days;
  $('#automatic').checked = s.automatic;
  $('#proxy').value = s.proxy;
  $('#include-replies').checked = s.include_replies;
  $('#include-retweets').checked = s.include_retweets;
  $('#include-quotes').checked = s.include_quotes;
  settingsLoaded = true;
}
let refreshPromise = null, refreshQueued = false;
function refresh(fresh = true) {
  if (refreshPromise) { if (fresh) refreshQueued = true; return refreshPromise; }
  refreshPromise = (async () => { do { refreshQueued = false; await refreshOnce(); } while (refreshQueued); })().finally(() => { refreshPromise = null; });
  return refreshPromise;
}
async function refreshOnce() {
  refreshing = true;
  try { const wasConnected = state?.credentials_saved; state = await api('state'); $('#connection-error').classList.add('hidden'); render(); if (wasConnected === false && state.credentials_saved) toast('X 登录凭证已加密保存，可以开始同步'); }
  catch { $('#connection-error').classList.remove('hidden'); }
  finally { refreshing = false; }
}
document.addEventListener('click', async (event) => {
  if (suppressPreview) { event.preventDefault(); return; }
  if (selectedMedia.size && !event.target.closest('.media-card,#selection-toolbar,dialog,button,a,input,select,textarea,label')) { selectedMedia.clear(); renderSelection(); }
  const nav = event.target.closest('[data-view]'); if (nav) { view(nav.dataset.view); return; }
  const button = event.target.closest('[data-action]'); if (!button || button.disabled) return;
  const action = button.dataset.action, id = Number(button.dataset.id);
  if (action === 'preview-recent') { showViewer(state.recent.slice(0,6), Number(button.dataset.index)); return; }
  if (action === 'preview-media') { const index = Number(button.dataset.index); if (event.ctrlKey || event.metaKey || event.shiftKey || selectedMedia.size) toggleMedia(mediaResult.items[index].media_id); else showViewer(mediaResult.items, index); return; }
  if (action === 'clear-selection') { selectedMedia.clear(); renderSelection(); return; }
  if (action === 'select-all-media') { mediaResult.items.forEach(item => { if (item.media_id) selectedMedia.add(item.media_id); }); renderSelection(); return; }
  if (action === 'delete-selected') { await deleteItems([...selectedMedia]); return; }
  if (action === 'close-viewer') { $('#viewer-dialog').close(); return; }
  if (action === 'viewer-prev' || action === 'viewer-next') { if (viewerDeleting) return; showViewer(viewerItems, viewerIndex + (action === 'viewer-prev' ? -1 : 1)); return; }
  if (action === 'manage-media') { const author = state.authors.find(a => a.id === id); if (author && mediaPlatform !== 'all' && mediaPlatform !== platformKey(author.handle)) { setPlatform('media', platformKey(author.handle)); } if ($('#media-author').value !== String(id)) mediaResult = null; $('#media-author').value = String(id); syncAuthorPicker(); view('media'); return; }
  if (action === 'delete-media') { await deleteItems([mediaResult.items[Number(button.dataset.index)].media_id]); return; }
  if (action === 'settings' || action === 'activity') { view(action); return; }
  if (action === 'add-author') { $('#author-error').textContent = ''; $('#author-dialog').showModal(); $('#author-handles').focus(); return; }
  if (action === 'close-dialog') { $('#author-dialog').close(); return; }
  if (action === 'close-remove') { $('#remove-dialog').close(); return; }
  if (action === 'remove') { removeId = id; $('#remove-description').textContent = `@${state.authors.find((a) => a.id === id).handle} 将停止出现在列表中。`; $('#remove-dialog').showModal(); return; }
  button.disabled = true;
  try {
    if (action === 'open-media') await api('media/open', 'POST', {path:mediaResult.items[Number(button.dataset.index)].path});
    if (action === 'refresh-media') await loadMedia();
    if (action === 'restore-media') { const item = mediaResult.items[Number(button.dataset.index)]; await api('media/restore', 'POST', {tweet_id:item.tweet_id,num:item.num}); toast('已允许重新下载，请运行该推主的历史补查'); await loadMedia({keepPosition:true}); }
    if (action === 'sync' || action === 'full') { const r = await api(`authors/${id}/sync`, 'POST', {full: action === 'full'}); toast(r.queued ? '已优先安排手动同步；如有扫描正在进行，将在其结束后开始' : '这个推主的任务已在进行或已优先安排'); }
    if (action === 'cancel') { await api(`authors/${id}/cancel`, 'POST'); toast('正在停止任务，已下载文件会保留'); }
    if (action === 'sync-all') { const r = await api('sync-all', 'POST'); toast(`已加入 ${r.queued} 位推主的同步任务${r.unavailable ? `；${r.unavailable} 位暂不可同步，请检查平台登录` : ""}`); }
    if (action === 'open-folder') await api('open-folder', 'POST');
    if (action === 'login') { await api('login', 'POST'); toast('请在新打开的 X 窗口中登录。成功后会自动保存连接。'); }
    if (action === 'login-platform') { await api(`login/${button.dataset.platform}`, 'POST'); toast('请在新打开的窗口中登录。成功后会自动保存连接。'); }
    if (action === 'finish-weibo') { await api('login/weibo/finish', 'POST'); toast('正在读取微博登录状态，请稍候。'); }
    if (action === 'clear-platform') { await api(`credentials/${button.dataset.platform}`, 'DELETE'); toast('本地下载凭证已清除'); }
    if (action === 'clear-auth') { await api('credentials', 'DELETE'); toast('本地下载凭证已清除'); }
    if (action === 'pick-folder') { const r = await api('pick-folder', 'POST'); if (r.path) $('#download-dir').value = r.path; }
    await refresh();
  } catch (error) { toast(error.message, true); if (/Cookie|登录/.test(error.message)) view('settings'); }
  finally { button.disabled = false; }
});
document.addEventListener('change', async (event) => {
  if (event.target.matches('[data-toggle]')) {
    try { await api(`authors/${event.target.dataset.toggle}`, 'PATCH', {enabled:event.target.checked}); await refresh(); }
    catch (error) { event.target.checked = !event.target.checked; toast(error.message,true); }
  }
});
$('#search-authors').addEventListener('input', renderAuthors);
$('#author-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.submitter; button.disabled = true;
  const handles = $('#author-handles').value.split(/[\n,，]+/).map((s) => s.trim()).filter(Boolean);
  let added = 0; const errors = [];
  for (const handle of handles) { try { await api('authors','POST',{handle}); added++; } catch (error) { errors.push(`${handle}：${error.message}`); } }
  button.disabled = false;
  if (errors.length) { $('#author-error').textContent = `${added ? `已添加 ${added} 位。\n` : ''}${errors.join('\n')}`; $('#author-handles').value = handles.filter((h) => errors.some((e) => e.startsWith(h+'：'))).join('\n'); }
  else { $('#author-dialog').close(); $('#author-handles').value = ''; toast(`已添加 ${added} 位推主`); }
  await refresh();
});
let removeBusy = false;
$('#remove-dialog').addEventListener('cancel', event => { if (removeBusy) event.preventDefault(); });
$('#remove-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (removeBusy) return;
  const deleteFiles = event.submitter?.dataset.deleteFiles === 'true';
  const buttons = [...$('#remove-form').querySelectorAll('button')];
  removeBusy = true; buttons.forEach(button => { button.disabled = true; });
  try {
    await api(`authors/${removeId}${deleteFiles ? '?delete_files=true' : ''}`,'DELETE');
    $('#remove-dialog').close();
    toast(deleteFiles ? '已移出推主并删除当前文件夹' : '已移出列表并清空媒体和同步记录，本地文件保留');
    mediaResult = null; await refresh();
  } catch(error) { toast(error.message,true); }
  finally { removeBusy = false; buttons.forEach(button => { button.disabled = false; }); }
});
$('#credentials-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try { await api('credentials','PUT',{auth_token:$('#auth-token').value.trim(),ct0:$('#ct0').value.trim()}); $('#auth-token').value = ''; $('#ct0').value = ''; toast('登录凭证已加密保存'); await refresh(); }
  catch(error) { toast(error.message,true); } finally { button.disabled = false; }
});
$('#settings-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try { await api('settings','PUT',{download_dir:$('#download-dir').value.trim(),interval_minutes:Number($('#interval').value),overlap_days:Number($('#overlap').value),automatic:$('#automatic').checked,proxy:$('#proxy').value.trim(),include_replies:$('#include-replies').checked,include_retweets:$('#include-retweets').checked,include_quotes:$('#include-quotes').checked,download_concurrency:Number($('#concurrency').value)}); $('#settings-message').textContent = '设置已保存'; toast('下载设置已保存'); settingsLoaded = false; await refresh(); }
  catch(error) { $('#settings-message').textContent = error.message; toast(error.message,true); } finally { button.disabled = false; }
});
async function loadMedia({keepPosition = false} = {}) {
  const request = ++mediaRequest;
  mediaLoading = true;
  $('#media-body').setAttribute('aria-busy','true');
  if (!mediaResult) setGalleryHTML(Array.from({length:6},(_,i) => `<div class="gallery-skeleton" style="height:${[240,320,280][i%3]}px"></div>`).join(''));
  try {
    const excluded = $('#media-mode').value === 'excluded';
    $('#media-kind').disabled = excluded;
    if (excluded) $('#media-kind').value = 'all';
    const result = await api(`media?author_id=${Number($('#media-author').value)}&platform=${mediaPlatform}&kind=${$('#media-kind').value}&excluded=${excluded}&all_items=true`);
    if (request !== mediaRequest) return;
    mediaResult = result;
    lastGalleryLoad = Date.now();
    gallerySignature = state.authors.map(a => `${a.id}:${a.files}:${a.gallery_available}`).join(',') + ':' + state.totals.excluded;
    const keep = keepPosition && $('#media-body').classList.contains('excluded-gallery') === excluded ? renderedMediaCount : 0;
    if (keep) { const ids = new Set(result.items.map(item => item.media_id)); [...selectedMedia].forEach(id => { if (!ids.has(id)) selectedMedia.delete(id); }); }
    else selectedMedia.clear();
    $('#media-body').classList.toggle('excluded-gallery',excluded);
    if (!result.items.length) { renderedMediaCount = 0; setGalleryHTML('<div class="gallery-empty"><span>▧</span><strong>这里还没有媒体</strong><p>试试其他推主或媒体类型，或先运行一次同步。</p></div>'); }
    else if (keep) rebuildGallery(Math.max(keep, GALLERY_BATCH));
    else { renderedMediaCount = 0; setGalleryHTML(''); appendMediaBatch(); }
    renderSelection();
    $('#gallery-result-label').textContent = `${excluded ? '忽略清单' : '已保存'} · 共 ${number(result.total)} 份`;
    scheduleLayout();
  } catch (error) { if (request === mediaRequest) { setGalleryHTML('<div class="gallery-empty"><strong>暂时无法读取媒体</strong><p>请点击“刷新”重试。</p></div>'); toast(error.message, true); } }
  finally { if (request === mediaRequest) { mediaLoading = false; $('#media-body').setAttribute('aria-busy','false'); } }
}
for (const selector of ['#media-author','#media-kind','#media-mode']) $(selector).addEventListener('change', () => { loadMedia(); });
function mediaCardMarkup(item, index, excluded) {
  const name = item.path.replaceAll('\\','/').split('/').pop();
  const selected = selectedMedia.has(item.media_id);
  return excluded ? `<article class="media-card excluded-card"><div class="excluded-cover"><span>⊘</span><strong>已从本地移除</strong><small>${item.reason === 'external' ? 'Windows 中删除或移动' : '应用内删除'}</small></div><div class="card-detail"><code class="media-filename">${esc(name)}</code><button data-action="restore-media" data-index="${index}">允许重新下载</button></div></article>` : `<article class="media-card${selected ? ' selected' : ''}" data-media-id="${item.media_id}"><button class="card-preview" data-action="preview-media" data-index="${index}" aria-pressed="${selected}" aria-label="预览 ${esc(name)}">${imageMarkup(item)}</button><button class="tile-delete danger" data-action="delete-media" data-index="${index}" aria-label="删除并忽略 ${esc(name)}" title="删除并忽略，不再补回"><span class="delete-icon" aria-hidden="true"></span></button>${item.kind === 'video' ? '<span class="tile-video" aria-hidden="true">视频</span>' : ''}<div class="tile-overlay"><span class="tile-caption">${esc(item.display_name || item.handle)}<small>${time(item.published_at,true)}</small></span></div></article>`;
}
// Re-render the first `count` items, reusing existing cards so loaded images and the scroll position stay put.
function rebuildGallery(count) {
  const body = $('#media-body'), excluded = $('#media-mode').value === 'excluded';
  const existing = new Map();
  if (!excluded) galleryCards.forEach(card => { if (card.dataset.mediaId) existing.set(Number(card.dataset.mediaId), card); });
  const items = mediaResult.items.slice(0, count);
  const template = document.createElement('template');
  template.innerHTML = items.map((item, index) => existing.has(item.media_id) ? '' : mediaCardMarkup(item, index, excluded)).join('');
  const fresh = [...template.content.children];
  let next = 0;
  const nodes = items.map((item, index) => {
    const card = existing.get(item.media_id);
    if (!card) return fresh[next++];
    card.querySelectorAll('[data-index]').forEach(button => { button.dataset.index = index; });
    return card;
  });
  const keep = new Set(nodes);
  galleryCards.forEach(card => { if (!keep.has(card)) card.remove(); });
  body.querySelectorAll(':scope > :not(.media-card)').forEach(node => node.remove());
  body.append(...fresh);
  galleryCards = nodes;
  renderedMediaCount = items.length;
  scheduleLayout();
}
function appendMediaBatch() {
  if (!mediaResult || renderedMediaCount >= mediaResult.items.length || currentView !== 'media') return;
  const start = renderedMediaCount, end = Math.min(start + GALLERY_BATCH, mediaResult.items.length);
  const excluded = $('#media-mode').value === 'excluded';
  const template = document.createElement('template');
  template.innerHTML = mediaResult.items.slice(start,end).map((item,i) => mediaCardMarkup(item,start+i,excluded)).join('');
  const cards = [...template.content.children];
  galleryCards.push(...cards);
  $('#media-body').append(...cards);
  renderedMediaCount = end;
  scheduleLayout();
}
function maybeAppendMedia() {
  if (currentView !== 'media' || !mediaResult || renderedMediaCount >= mediaResult.items.length || mediaLoading || deletingMedia) return;
  if ($('#media-body').getBoundingClientRect().bottom < innerHeight + 900) appendMediaBatch();
}
window.addEventListener('scroll', maybeAppendMedia, {passive:true});
// Masonry layout. Card heights are cached and only re-measured when a card is new, its image settles, or the column width changes;
// positions are written only when they move. The resulting boxes also drive marquee hit-testing without touching the DOM.
// Only cards near the viewport stay in the DOM: with thousands attached, every layout (even moving the marquee box) re-walks them all.
let galleryBoxes = [], cardById = new Map(), layoutWidth = 0, galleryCards = [], windowFrame = 0;
const cardHeights = new WeakMap();
function setGalleryHTML(html) {
  const body = $('#media-body');
  body.innerHTML = html;
  galleryCards = [...body.querySelectorAll('.gallery-skeleton')];
  galleryBoxes = []; cardById = new Map();
  scheduleLayout();
}
// Attach cards within ~2 screens of the viewport, detach the rest. Positions come from the cached layout.
function updateWindow() {
  if (!galleryBoxes.length) return;
  const container = $('#media-body');
  const top = container.getBoundingClientRect().top, from = -top - innerHeight * 1.5, to = -top + innerHeight * 2.5;
  let remeasure = false;
  for (const box of galleryBoxes) {
    const card = box.card, attached = card.parentNode === container;
    if (box.y + box.h > from && box.y < to) {
      if (!attached) {
        container.appendChild(card);
        settleThumb(card);
        if (box.id) paintCard(card, selectedMedia.has(box.id));
        if (!card._settled) { cardHeights.delete(card); remeasure = true; }
      }
    } else if (attached && !card.contains(document.activeElement)) card.remove();
  }
  if (remeasure) scheduleLayout();
}
window.addEventListener('scroll', () => { cancelAnimationFrame(windowFrame); windowFrame = requestAnimationFrame(updateWindow); }, {passive:true});
function scheduleLayout() {
  cancelAnimationFrame(layoutFrame);
  layoutFrame = requestAnimationFrame(() => {
    const container = $('#media-body');
    const cards = galleryCards;
    const columns = Number(getComputedStyle(container).getPropertyValue('--gallery-columns')) || 3;
    const gap = 6, width = (container.clientWidth - gap * (columns - 1)) / columns;
    if (width <= 0) return;
    const resized = width !== layoutWidth;
    layoutWidth = width;
    const stale = cards.filter(card => resized || card._width !== width || !cardHeights.has(card));
    const measured = [];
    stale.forEach(card => {
      if (card.parentNode !== container) {
        // Detached: scale the cached height (media keep their aspect ratio) and re-measure once it is attached again.
        const previous = cardHeights.get(card);
        cardHeights.set(card, previous && card._width ? previous * width / card._width : width);
        card._settled = false;
      } else measured.push(card);
      if (card._width !== width) { card.style.width = `${width}px`; card._width = width; }
    });
    measured.forEach(card => { cardHeights.set(card, card.offsetHeight); const img = card.querySelector('img'); card._settled = !img || img.complete; });
    const heights = Array(columns).fill(0);
    galleryBoxes = cards.map(card => {
      const column = heights.indexOf(Math.min(...heights));
      const x = column * (width + gap), y = heights[column], h = cardHeights.get(card);
      const transform = `translate(${x}px,${y}px)`;
      if (card._transform !== transform) { card.style.transform = transform; card._transform = transform; }
      heights[column] += h + gap;
      return {card, id:Number(card.dataset.mediaId) || 0, x, y, w:width, h};
    });
    cardById = new Map(galleryBoxes.filter(box => box.id).map(box => [box.id, box.card]));
    container.style.height = cards.length ? `${Math.max(...heights) - gap}px` : 'auto';
    updateWindow();
    maybeAppendMedia();
  });
}
const remeasureCard = event => { const card = event.target.closest?.('.media-card'); if (card) cardHeights.delete(card); scheduleLayout(); };
$('#media-body').addEventListener('load', remeasureCard, true);
$('#media-body').addEventListener('error', remeasureCard, true);
let galleryWidth = 0;
new ResizeObserver(entries => { const width = entries[0].contentRect.width; if (width !== galleryWidth) { galleryWidth = width; scheduleLayout(); } }).observe($('#media-body'));
function renderSelectionToolbar() {
  $('#selection-toolbar').classList.toggle('hidden', !selectedMedia.size);
  $('#selection-count').textContent = `已选 ${selectedMedia.size} 项`;
}
function paintCard(card, selected) {
  if (!card || card.classList.contains('selected') === selected) return;
  card.classList.toggle('selected', selected);
  card.querySelector('.card-preview')?.setAttribute('aria-pressed', String(selected));
}
function renderSelection() {
  renderSelectionToolbar();
  galleryCards.forEach(card => { if (card.dataset.mediaId) paintCard(card, selectedMedia.has(Number(card.dataset.mediaId))); });
}
function setSelection(next) {
  const changed = [];
  selectedMedia.forEach(id => { if (!next.has(id)) changed.push(id); });
  next.forEach(id => { if (!selectedMedia.has(id)) changed.push(id); });
  if (!changed.length) return;
  selectedMedia.clear(); next.forEach(id => selectedMedia.add(id));
  changed.forEach(id => paintCard(cardById.get(id), selectedMedia.has(id)));
  renderSelectionToolbar();
}
function toggleMedia(id) { if (selectedMedia.has(id)) selectedMedia.delete(id); else selectedMedia.add(id); renderSelection(); }
async function deleteItems(ids) {
  if (!ids.length || deletingMedia || mediaLoading) return [];
  deletingMedia = true;
  const original = mediaResult, deleted = [], failed = [];
  $('[data-action="delete-selected"]').disabled = true;
  try {
    for (let i = 0; i < ids.length; i += 100) {
      const batch = await api('media/delete-batch','POST',{media_ids:ids.slice(i,i + 100)});
      deleted.push(...batch.deleted); failed.push(...batch.failed);
    }
    toast(failed.length ? `已删除 ${deleted.length} 项；${failed.length} 项未完成：${failed[0].error}` : `已删除并忽略 ${deleted.length} 项`, !!failed.length);
  } catch(error) { toast(`已删除 ${deleted.length} 项；后续删除未完成：${error.message}`,true); }
  finally {
    if (original && original === mediaResult && deleted.length) {
      const removed = new Set(deleted);
      const oldRendered = mediaResult.items.slice(0,renderedMediaCount);
      renderedMediaCount -= oldRendered.filter(item => removed.has(item.media_id)).length;
      mediaResult.items = mediaResult.items.filter(item => !removed.has(item.media_id));
      mediaResult.total = Math.max(0, mediaResult.total - deleted.length);
      deleted.forEach(id => selectedMedia.delete(id));
      const indexById = new Map(mediaResult.items.map((item,index) => [item.media_id,index]));
      galleryCards = galleryCards.filter(card => {
        const id = Number(card.dataset.mediaId);
        if (!id) return true;
        if (removed.has(id)) { card.remove(); return false; }
        card.querySelectorAll('[data-index]').forEach(button => { button.dataset.index = indexById.get(id); });
        return true;
      });
      if (!mediaResult.items.length) setGalleryHTML('<div class="gallery-empty"><span>▧</span><strong>这里还没有媒体</strong><p>试试其他推主或媒体类型，或先运行一次同步。</p></div>');
      $('#gallery-result-label').textContent = `已保存 · 共 ${number(mediaResult.total)} 份`;
      renderSelection(); scheduleLayout();
    }
    await refresh();
    if (original === mediaResult && state) gallerySignature = state.authors.map(a => `${a.id}:${a.files}:${a.gallery_available}`).join(',') + ':' + state.totals.excluded;
    deletingMedia = false;
    $('[data-action="delete-selected"]').disabled = false;
    maybeAppendMedia();
  }
  return deleted;
}
async function deleteViewerItem() {
  if (viewerDeleting || deletingMedia || mediaLoading) return;
  const item = viewerItems[viewerIndex];
  if (!item) return;
  const items = viewerItems, index = viewerIndex;
  viewerDeleting = true;
  // Release the playing video first: Windows refuses to delete a file the player still has open.
  const video = $('#viewer-stage video');
  if (video) { video.pause(); video.removeAttribute('src'); video.load(); }
  try {
    const deleted = await deleteItems([item.media_id]);
    if (!$('#viewer-dialog').open || viewerItems !== items) return;
    if (!deleted.includes(item.media_id)) { showViewer(items, index); return; }
    // The gallery result can be replaced during deletion; keep this viewer sequence in sync.
    const remaining = items.filter(entry => entry.media_id !== item.media_id);
    if (!remaining.length) { $('#viewer-dialog').close(); return; }
    showViewer(remaining, Math.min(index, remaining.length - 1));
  } finally { viewerDeleting = false; }
}
// Start on gallery media or workspace whitespace; controls keep their normal gestures.
document.addEventListener('pointerdown', event => {
  if (currentView !== 'media' || !event.target.closest('main') || document.querySelector('dialog[open]') || event.button !== 0 || event.pointerType === 'touch' || mediaLoading || deletingMedia || $('#media-mode').value === 'excluded' || event.target.closest('button:not(.card-preview),a,input,select,textarea,label,summary,.picker,[contenteditable="true"],#selection-toolbar')) return;
  if (!event.target.closest('.card-preview')) event.preventDefault();
  selectionDrag = {x:event.pageX,y:event.pageY,cx:event.clientX,cy:event.clientY,active:false,base:new Set(event.ctrlKey || event.metaKey || event.shiftKey ? selectedMedia : [])};
});
$('#media-body').addEventListener('dragstart', event => event.preventDefault());
function updateDrag() {
  const drag = selectionDrag;
  if (!drag?.active) return;
  const key = `${drag.cx},${drag.cy},${scrollX},${scrollY},${galleryBoxes.length}`;
  if (key === drag.key) return;
  drag.key = key;
  const x = drag.cx + scrollX, y = drag.cy + scrollY;
  const left = Math.min(drag.x,x), top = Math.min(drag.y,y), right = Math.max(drag.x,x), bottom = Math.max(drag.y,y);
  const box = $('#selection-box'); box.classList.remove('hidden');
  Object.assign(box.style,{left:`${left - scrollX}px`,top:`${top - scrollY}px`,width:`${right-left}px`,height:`${bottom-top}px`});
  const origin = $('#media-body').getBoundingClientRect(), ox = origin.left + scrollX, oy = origin.top + scrollY;
  const next = new Set(drag.base);
  for (const b of galleryBoxes) {
    if (!b.id) continue;
    const l = ox + b.x, t = oy + b.y;
    if (l + b.w > left && l < right && t + b.h > top && t < bottom) next.add(b.id);
  }
  setSelection(next);
}
function scrollDrag() {
  if (!selectionDrag?.active) return;
  const y = selectionDrag.cy;
  if (y > innerHeight - 60) window.scrollBy(0,Math.min(18,(y - innerHeight + 60)/3));
  if (y < 70) window.scrollBy(0,-Math.min(18,(70-y)/3));
  updateDrag(); requestAnimationFrame(scrollDrag);
}
document.addEventListener('pointermove', event => {
  lastPointerPoint = {x:event.clientX,y:event.clientY};
  if (!$('#viewer-dialog').open && document.body.classList.contains('gallery-hover-paused') &&
      (!galleryHoverResumePoint || Math.hypot(event.clientX-galleryHoverResumePoint.x,event.clientY-galleryHoverResumePoint.y)>3)) {
    document.body.classList.remove('gallery-hover-paused');
    galleryHoverResumePoint = null;
  }
  if (!selectionDrag) return;
  selectionDrag.cx = event.clientX; selectionDrag.cy = event.clientY;
  if (!selectionDrag.active && Math.hypot(event.pageX-selectionDrag.x,event.pageY-selectionDrag.y)>6) {
    selectionDrag.active = true; suppressPreview = true; document.body.classList.add('selecting-media'); scrollDrag();
  }
  if (selectionDrag.active) event.preventDefault();
});
function endDrag() {
  if (!selectionDrag) return;
  selectionDrag = null; $('#selection-box').classList.add('hidden'); document.body.classList.remove('selecting-media');
  setTimeout(() => { suppressPreview = false; },0);
}
document.addEventListener('pointerup', endDrag);
document.addEventListener('pointercancel', endDrag);
window.addEventListener('blur', endDrag);
document.addEventListener('keydown', event => {
  if ($('#viewer-dialog').open && !event.target.closest('input,textarea,select,[contenteditable="true"]')) {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      if (!viewerDeleting) {
        const index = viewerIndex + (event.key === 'ArrowLeft' ? -1 : 1);
        if (index >= 0 && index < viewerItems.length) showViewer(viewerItems, index);
      }
      return;
    }
    if (event.key === 'Delete') { event.preventDefault(); deleteViewerItem(); return; }
  }
  if (event.key === 'Delete' && currentView === 'media' && selectedMedia.size && !document.querySelector('dialog[open]') && !event.target.closest('input,textarea,select,[contenteditable="true"]')) { event.preventDefault(); deleteItems([...selectedMedia]); return; }
  if (event.key === 'Tab' && !$('#viewer-dialog').open) document.body.classList.remove('gallery-hover-paused');
  if (event.key === 'Escape' && !$('#viewer-dialog').open) { endDrag(); selectedMedia.clear(); renderSelection(); }
});
window.addEventListener('hashchange', () => { const name = location.hash.slice(1); if (['library','activity','settings','media'].includes(name) && name !== currentView) view(name); });
window.addEventListener('app-language-change', () => {
  if (!state) return;
  recentSignature = null; eventSignature = '';
  render();
  if ($('#viewer-dialog').open && viewerItems[viewerIndex]) {
    const item = viewerItems[viewerIndex];
    $('#viewer-meta').textContent = `${time(item.published_at)} · ${bytes(item.size)} · 原文件`;
  }
});
view(['library','activity','settings','media'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'library');
refresh(); setInterval(() => refresh(false), 2500);
