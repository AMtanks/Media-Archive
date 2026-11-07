'use strict';
// Translate application-owned labels only. User names, file names and unrecognized
// server diagnostics are left intact. The original text stays available for switching back.
(() => {
  const translations = {
    'Media Archive 首页':'Media Archive home','主导航':'Main navigation','推主':'Authors','媒体':'Media','同步记录':'Sync history','设置':'Settings',
    '筛选平台':'Filter by platform','全部':'All','微博':'Weibo',
    '正在读取登录状态':'Checking sign-in status','本地运行':'Running locally','打开文件夹':'Open folder',
    '应用连接中断，正在重连。下载任务在后台独立运行。':'Connection lost. Reconnecting; downloads continue in the background.',
    '添加推主，自动保存每一次更新。':'Add authors and automatically save their updates.','添加推主':'Add authors','连接 X 账号':'Connect X account',
    '登录状态只保存在这台电脑。连接后扫描历史内容，并定时保存新增媒体。':'Your sign-in stays on this computer. Connect to scan past posts and periodically save new media.',
    '连接':'Connect','概览':'Overview','等待加载':'Loading','图片与视频':'Images and videos','占用空间':'Storage used','本地文件总大小':'Total local file size',
    '自动同步':'Automatic sync','应用运行时生效':'While the app is running','列表':'Authors','搜索':'Search','查找推主':'Search authors','全部同步':'Sync all',
    '状态':'Status','已保存':'Saved','上次完成':'Last completed','自动':'Auto','操作':'Actions','正在读取本地记录…':'Loading local records…',
    '最近保存':'Recently saved','还没有归档文件':'No saved files yet','动态':'Activity','全部记录':'View all',
    '文件按 UTC 发文时间命名，如':'Files are named by post time in UTC, for example','2026-11-07_143025Z_推文ID_01.jpg':'2026-11-07_143025Z_tweetID_01.jpg','，末尾序号保持同一推文内的顺序。':'; the final number preserves media order within a post.',
    '浏览已保存的内容，删掉不想要的。':'Browse saved media and remove what you do not want.','全部推主':'All authors','筛选推主':'Filter authors',
    '筛选媒体':'Filter media','全部类型':'All types','图片':'Images','视频':'Videos','筛选状态':'Filter status','忽略清单':'Ignored','刷新':'Refresh',
    '拖动框选 · Del 删除 · ← → 翻看':'Drag to select · Del to delete · ← → to browse',
    '选择当前筛选条件下的全部媒体，包含尚未滚动显示的项目':'Select all matching media, including items not yet displayed',
    '全选':'Select all','取消':'Cancel','删除并忽略':'Delete and ignore','最近 60 次扫描任务。':'The latest 60 scans.',
    '开始时间':'Started','新增':'Added','跳过':'Skipped','日志':'Log','最近 100 条 · 凭证自动隐藏':'Latest 100 entries · credentials hidden automatically',
    '外观':'Appearance','主题':'Theme','跟随系统':'System','浅色':'Light','深色':'Dark','语言':'Language','X 账号':'X account',
    '登录状态':'Sign-in status','凭证由当前 Windows 账户加密保存在本机。':'Credentials are encrypted locally using your Windows account.',
    '未连接':'Not connected','登录 X':'Sign in to X','清除凭证':'Clear credentials','登录成功后自动保存连接状态。':'Your connection is saved after sign-in.',
    '手动填写 Cookie':'Enter cookies manually','必填':'Required','可选':'Optional','粘贴 Cookie 的值':'Paste the cookie value','粘贴 ct0 Cookie 的值':'Paste the ct0 cookie value',
    '在已登录 X 的浏览器中按 F12 → Application → Cookies → https://x.com，复制相应值。请勿分享这些值。':'In a browser signed in to X, press F12 → Application → Cookies → https://x.com and copy the values. Do not share them.',
    '加密保存':'Encrypt and save','保存与同步':'Storage and sync','保存位置':'Save location','选择…':'Choose…',
    '推主文件夹首次以“显示名@账号”命名，此后固定。更改位置后会重新扫描。':'Author folders are initially named “display name@handle” and remain fixed. Changing the location triggers a rescan.',
    '同步间隔':'Sync interval','每 15 分钟':'Every 15 minutes','每 30 分钟':'Every 30 minutes','每小时':'Hourly','每 3 小时':'Every 3 hours','每 6 小时':'Every 6 hours','每 12 小时':'Every 12 hours','每天':'Daily',
    '增量补查':'Incremental overlap','回看 1 天':'Look back 1 day','回看 3 天（推荐）':'Look back 3 days (recommended)','回看 7 天':'Look back 7 days','回看 30 天':'Look back 30 days','回看 90 天':'Look back 90 days',
    '同时下载':'Concurrent downloads','1 个文件':'1 file','2 个文件':'2 files','4 个文件（推荐）':'4 files (recommended)','6 个文件':'6 files','8 个文件':'8 files',
    '自动增量同步':'Automatic incremental sync','应用运行时，按间隔检查已启用的推主。':'Check enabled authors periodically while the app is running.',
    '媒体范围':'Media scope','回复中的媒体':'Media in replies','转推中的媒体':'Media in reposts','引用推文的原帖媒体':'Original media in quoted posts','修改媒体范围会触发历史补查。':'Changing the media scope triggers a historical rescan.',
    '网络':'Network','代理':'Proxy','留空使用系统代理，如 http://127.0.0.1:7890':'Leave blank to use the system proxy, e.g. http://127.0.0.1:7890',
    '浏览器能打开 X 但下载失败时，可填写本机代理地址。':'If X opens in your browser but downloads fail, enter your local proxy address.',
    '设置仅保存在本机':'Settings are stored locally','保存':'Save',
    '图片请求原图，视频选取 X 提供的最高码率，均不二次压缩。文件以 UTC 发文时间命名，修改时间同样设为发文时间。':'Images are requested at original size and videos at the highest bitrate offered by X, without recompression. Names use UTC post time and file modification times match the post time.',
    'X 的历史检索可能遗漏内容。“本轮完成”表示当前返回的内容已处理，不代表平台历史完整，可用“历史补查”再检查。':'X may omit older posts. “Completed” means returned items were processed, not that the entire history was retrieved. Use a historical scan to check again.',
    '关闭窗口会收到系统托盘继续同步；休眠或退出后暂停，重启时检查到期任务。':'Closing the window sends the app to the system tray and sync continues. Sleep or exit pauses sync; due tasks are checked on restart.',
    '关闭':'Close','输入账号或主页链接，每行一个。':'Enter one account or profile URL per line.','推主账号':'Author account','添加':'Add',
    '移出推主？':'Remove author?','本地文件保留，媒体和同步记录清空。忽略规则继续保留，重新添加后不会补回已删除内容。':'Local files are kept; media and sync records are cleared. Ignore rules are retained if the author is added again.',
    '“仅移出”保留本地文件。“移出并删除文件”会永久删除当前保存位置中该推主的整个文件夹，包括头像和其中其他文件。两种操作都会清空媒体和同步记录，保留已有忽略规则。':'“Remove only” keeps local files. “Remove and delete files” permanently deletes the author’s entire folder at the current save location, including the avatar and other contents. Both clear media and sync records while retaining existing ignore rules.',
    '仅移出':'Remove only','移出并删除文件':'Remove and delete files','已移出推主并删除当前文件夹':'Author removed and current folder deleted',
    '保存目录不可用，无法确认文件是否已删除；请先检查磁盘':'Save location unavailable; check the drive before deleting files.',
    '推主文件夹路径无效，已停止删除':'Invalid author folder path; deletion stopped.',
    '推主文件夹是链接，已停止删除，请在资源管理器中检查':'Author folder is a link; deletion stopped. Check it in File Explorer.',
    '推主文件夹不在保存目录中，已停止删除':'Author folder is outside the save location; deletion stopped.',
    '推主保存位置不是文件夹，已停止删除':'Author save location is not a folder; deletion stopped.',
    '文件删除未完成，推主仍保留在列表中；请检查文件占用和权限，部分文件可能已删除':'Deletion was incomplete; the author remains in the list. Check file access and permissions; some files may already have been deleted.',
    '移出':'Remove','关闭预览':'Close preview','上一份媒体':'Previous media','下一份媒体':'Next media','上一份':'Previous','下一份':'Next','缩略图':'Thumbnails',
    '尚未完成':'Not yet completed','应用服务暂时无法连接，请重试':'Cannot connect to the app. Please retry.','请检查填写内容后重试':'Check your entries and try again.',
    '等待同步':'Waiting to sync','已加入队列':'Queued','正在扫描':'Scanning','需要重试':'Retry needed','本轮完成':'Completed','已停止':'Stopped','上次中断':'Interrupted',
    '查看媒体':'View media','等待前面的扫描完成':'Waiting for the current scan','首次扫描历史内容':'First scan will check historical posts','自动同步已暂停':'Automatic sync paused','本地时间':'Local time',
    '立即同步':'Sync now','停止':'Stop','同步':'Sync','历史补查':'Historical scan','重新检查历史内容，跳过已下载文件':'Check older posts again, skipping downloaded files',
    '没有找到这个推主':'No matching author','收藏从一位推主开始':'Start by adding an author','试试其他账号名称。':'Try another account name.','点击“添加推主”，输入账号或主页链接。':'Select “Add authors” and enter an account or profile URL.',
    '视频封面':'Video cover','已保存图片':'Saved image','预览暂不可用，点击打开文件':'Preview unavailable; click to open','原文件':'Original file','已保存的原图':'Saved original image',
    '已开启':'Enabled','已暂停':'Paused','可在下载设置中开启':'Enable in settings','X 登录凭证已保存':'X credentials saved','尚未连接 X 账号':'X account not connected','凭证已保存':'Credentials saved','尚未连接':'Not connected',
    '当前为浏览器模式。请使用“手动填写 Cookie”，或从桌面启动器打开应用。':'Browser mode: enter cookies manually or open the desktop app.',
    '还没有保存的媒体':'No saved media yet','连接 X 后同步推主，这里会显示图片和视频封面。':'Connect X and sync authors to see image and video previews here.',
    '一切准备就绪':'Ready to go','添加推主并连接 X，这里会显示实时下载进展。':'Add an author and connect X to see download progress here.',
    '暂无日志。开始同步后，任务进展会显示在这里。':'No log entries yet. Sync progress will appear here.','历史扫描':'Historical scan',
    '还没有同步记录':'No sync history yet','第一次扫描完成后，可在这里查看新增文件和跳过的数量。':'After the first scan, added and skipped counts appear here.',
    'X 登录凭证已加密保存，可以开始同步':'X credentials were encrypted and saved. You can now sync.',
    '已允许重新下载，请运行该推主的历史补查':'Redownload allowed. Run a historical scan for this author.',
    '已优先安排手动同步；如有扫描正在进行，将在其结束后开始':'Manual sync prioritized. It will start after the current scan finishes.',
    '这个推主的任务已在进行或已优先安排':'This author is already syncing or prioritized.','正在停止任务，已下载文件会保留':'Stopping the task. Downloaded files will be kept.',
    '请在新打开的 X 窗口中登录。成功后会自动保存连接。':'Sign in through the X window. Your connection will be saved automatically.',
    '本地下载凭证已清除':'Local credentials cleared','已移出列表并清空媒体和同步记录，本地文件保留':'Author removed and media and sync records cleared. Local files were kept.',
    '登录凭证已加密保存':'Credentials encrypted and saved','设置已保存':'Settings saved','下载设置已保存':'Download settings saved',
    '这里还没有媒体':'No media here yet','试试其他推主或媒体类型，或先运行一次同步。':'Try another author or media type, or run a sync first.',
    '暂时无法读取媒体':'Cannot load media','请点击“刷新”重试。':'Select Refresh to try again.','已从本地移除':'Removed locally',
    'Windows 中删除或移动':'Deleted or moved in Windows','应用内删除':'Deleted in the app','允许重新下载':'Allow redownload','删除并忽略，不再补回':'Delete and ignore; do not download again',
    '等待当前扫描结束后立即开始':'Will start after the current scan','即将开始手动同步':'Manual sync starting shortly','X 限流冷却中，可点立即同步尝试':'X rate limit cooldown; select Sync now to try',
    '其他平台账号':'Other platform accounts','凭证加密保存在本机。':'Credentials are encrypted and stored locally.',
    '登录 Instagram':'Sign in to Instagram','登录微博':'Sign in to Weibo',
    '输入 X 账号，或 X、Instagram、微博的主页链接，每行一个。':'Enter an X account or an X, Instagram, or Weibo profile URL, one per line.',
    '已在窗口中登录':'I have signed in','微博登录成功后，请保持登录窗口打开，再点击“已在窗口中登录”。':'After signing in to Weibo, keep the login window open and select “I have signed in”.',
    '正在读取微博登录状态，请稍候。':'Reading the Weibo session, please wait.','请先打开微博登录窗口并完成登录':'Open the Weibo login window and sign in first.',
    '微博 / Weibo':'Weibo',
    '账号应为 1–15 位英文字母、数字或下划线':'An X handle must contain 1–15 letters, numbers, or underscores.',
    '请输入 X / Twitter 的账号或主页链接':'Enter an X / Twitter handle or profile URL.',
    '平台账号无效':'Invalid platform account.','平台身份资料无效':'Invalid platform profile.',
    '账号身份发生变化，已暂停以保护原有收藏':'The account identity changed. Sync paused to protect existing media.',
    '推主身份资料无效':'Invalid author profile.','推主文件夹必须位于媒体保存目录内':'The author folder must be inside the media save location.',
    '媒体文件夹不可用，请检查磁盘或路径；未将文件标记为删除':'Media folder unavailable. Check the drive or path; files have not been marked as deleted.',
    '这个推主已经在列表中':'This author is already in the list.','这个平台账号已在列表中':'This platform account is already in the list.',
    '推主的新账号已在列表中，请先处理重复账号':'The new handle is already in the list. Resolve the duplicate first.',
    '这个推主已在列表中，请移除重复添加的账号':'This author is already in the list. Remove the duplicate account.',
    '新旧推主目录同时存在，已停止迁移，请先检查目录内容':'Both old and new folders exist. Migration stopped; inspect both folders.',
    '原媒体文件夹不可用，已暂停迁移；不会重新下载已删除内容':'The original media folder is unavailable. Migration paused; deleted files will not be redownloaded.',
    '页码无效':'Invalid page.','平台筛选无效':'Invalid platform filter.','预览链接已失效，请刷新应用':'Preview link expired. Refresh the app.',
    '媒体文件不存在或格式不支持':'Media file is missing or its format is unsupported.',
    '代理格式示例：http://127.0.0.1:7890':'Proxy example: http://127.0.0.1:7890','不支持的平台':'Unsupported platform.',
    '暂时无法生成预览，可打开本地文件查看':'Preview unavailable. Open the local file instead.',
    '不支持的平台主页链接':'Unsupported platform profile URL.','请输入完整的平台主页链接':'Enter a complete profile URL.',
    '请输入包含数字用户 ID 的微博主页链接':'Enter a Weibo profile URL containing a numeric user ID.',
    '媒体缺少稳定的帖子编号、发文时间或媒体序号':'Media is missing a stable post ID, date, or position.',
    '请输入 Instagram 用户主页链接':'Enter an Instagram profile URL.',
    '登录凭证加密目前仅支持 Windows':'Credential encryption currently requires Windows.',
    'auth_token 格式不正确，请复制 Cookie 的值':'Invalid auth_token. Copy the cookie value.',
    '没有可保存的登录凭证':'No credentials to save.',
    '不支持的主页链接':'Unsupported profile URL.','无法确认账号身份，已停止扫描':'Cannot verify account identity; scan stopped.',
    '帖子缺少发文日期，已停止扫描':'Post has no publication date; scan stopped.','推主保存位置不是文件夹':'Author save location is not a folder.',
    '本地文件夹已删除，媒体记录已清空；自动同步已暂停':'The local folder was deleted; media records were cleared and automatic sync paused.',
    '文件夹已恢复，可手动同步或开启自动同步':'The folder was restored. Sync manually or enable automatic sync.',
    '正在下载 FFmpeg（约 30 MB，仅首次）…':'Downloading FFmpeg (first use only)…','FFmpeg 已就绪':'FFmpeg is ready.',
    '此视频需要 FFmpeg 合并原始流。FFmpeg 自动下载失败，请检查网络/代理后重试，或手动把 ffmpeg.exe 放到数据目录的 ffmpeg 文件夹，不会保存为播放列表文件。':'This video requires FFmpeg. Automatic download failed; check the network or proxy, or place ffmpeg.exe in the data/ffmpeg folder.',
    '请在新打开的窗口中登录。成功后会自动保存连接。':'Sign in through the new window. Your connection will be saved automatically.',
    '登录凭证无法解密，请重新登录':'Cannot decrypt credentials; please sign in again.',
    '本轮未返回媒体，无法确认扫描完整性；请检查登录状态、账号权限或稍后重试':'No media returned; the scan may be incomplete. Check sign-in and account access or retry later.',
    '下载未完成，请检查网络或登录 Cookie':'Download incomplete. Check your network or sign-in cookies.',
    '本地文件夹已删除；请先恢复文件夹，再手动同步':'The local folder was deleted. Restore it before syncing manually.',
    '请先在设置中保存登录 Cookie':'Save your sign-in cookie in Settings first.',
    '此视频需要 FFmpeg 合并原始流。请安装 FFmpeg 后重试，不会保存为播放列表文件。':'This video requires FFmpeg to merge streams. Install FFmpeg and retry.',
    '检测到已删除媒体，已保留忽略规则':'Deleted media detected; the ignore rule was retained.',
    '头像尚未保存':'Avatar has not been saved.','媒体记录不存在':'Media record not found.',
    '文件已不在原位置':'The file is no longer at its original location.','文件位于旧的保存位置，请在资源管理器中处理':'The file is in the old save location. Manage it in File Explorer.',
    '已加入忽略清单，但文件删除失败，请关闭占用文件的程序后重试':'The item was ignored, but the file could not be deleted. Close programs using it and retry.',
    '请先停止下载任务，再允许媒体重新下载':'Stop downloads before allowing this media to be downloaded again.',
    '推主不存在':'Author not found.','请先停止这个推主的任务，再移出列表':'Stop this author’s task before removing them.',
    '保存位置必须是完整的绝对路径':'The save location must be an absolute path.',
    '请选择独立的媒体文件夹，不要使用应用数据或代码目录':'Choose a separate media folder, not the application data or code folder.',
    '请先停止下载任务，再修改保存位置或媒体范围':'Stop downloads before changing the save location or media scope.',
    '无法创建保存文件夹，请检查路径和写入权限':'Could not create the save folder. Check the path and write permissions.',
    '请先停止所有下载任务':'Stop all download tasks first.',
    '请从桌面启动器打开应用，或手动填写 Cookie':'Open the desktop app or enter cookies manually.',
    '当前窗口不支持选择文件夹，请直接填写路径':'Folder selection is unavailable in this window; enter the path instead.',
  };
  const patterns = [
    [/^显示 (\d+) 位推主 · 按添加顺序$/, (_, n) => `Showing ${n} authors · in order added`],
    [/^(\d+) 位启用自动同步$/, (_, n) => `${n} authors enabled for automatic sync`],
    [/^每 (\d+) 分钟 · 应用运行时$/, (_, n) => `Every ${n} minutes · while the app is running`],
    [/^已忽略 ([\d,]+) 个文件$/, (_, n) => `${n} files ignored`],
    [/^(已保存|忽略清单) · 共 ([\d,]+) 份$/, (_, kind, n) => `${kind === '已保存' ? 'Saved' : 'Ignored'} · ${n} items`],
    [/^已选 (\d+) 项$/, (_, n) => `${n} selected`],
    [/^已加入 (\d+) 位推主的同步任务$/, (_, n) => `Queued sync for ${n} authors`],
    [/^已添加 (\d+) 位推主$/, (_, n) => `Added ${n} authors`],
    [/^已删除并忽略 (\d+) 项$/, (_, n) => `Deleted and ignored ${n} items`],
    [/^已删除 (\d+) 项；(\d+) 项未完成：(.*)$/, (_, n, m, error) => `Deleted ${n}; ${m} failed: ${error}`],
    [/^已删除 (\d+) 项；后续删除未完成：(.*)$/, (_, n, error) => `Deleted ${n}; remaining items failed: ${error}`],
    [/^@(.+) 将停止出现在列表中。$/, (_, name) => `@${name} will be removed from the list.`],
    [/^下次 (.+)$/, (_, date) => `Next: ${date}`],
    [/^(.+) 自动重试$/, (_, date) => `Automatic retry: ${date}`],
    [/^结束 (.+)$/, (_, date) => `Finished: ${date}`],
    [/^第 (\d+) 份$/, (_, n) => `Item ${n}`],
    [/^自动同步 (@.+)$/, (_, name) => `Automatic sync ${name}`],
    [/^移出 (@.+)$/, (_, name) => `Remove ${name}`],
    [/^预览 (.+)$/, (_, name) => `Preview ${name}`],
    [/^删除并忽略 (.+)$/, (_, name) => `Delete and ignore ${name}`],
    [/^(.+) · 原文件$/, (_, detail) => `${detail} · Original file`],
    [/^开始(历史扫描|增量同步) (@.+)$/, (_, mode, name) => `Started ${mode === '历史扫描' ? 'historical scan' : 'incremental sync'} for ${name}`],
    [/^保存目录：(.+)$/, (_, folder) => `Save folder: ${folder}`],
    [/^推主头像已保存到 (.+)$/, (_, path) => `Avatar saved to ${path}`],
    [/^等待 (\d+) 分钟后自动重试；从扫描范围重新检查，已保存及忽略的文件会跳过$/, (_, n) => `Retrying in ${n} minutes; saved and ignored files will be skipped.`],
    [/^(本轮扫描完成|任务已停止|本轮未完成)：新增 (\d+)，跳过 (\d+)。(.*)$/, (_, status, added, skipped, error) => `${{'本轮扫描完成':'Scan completed','任务已停止':'Task stopped','本轮未完成':'Scan incomplete'}[status]}: ${added} added, ${skipped} skipped. ${translate(error)}`],
    [/^(自动同步暂不可用|任务异常|头像暂未更新|并发下载任务失败)：(.+)$/, (_, type, reason) => `${{'自动同步暂不可用':'Automatic sync unavailable','任务异常':'Task error','头像暂未更新':'Avatar not updated','并发下载任务失败':'Concurrent download failed'}[type]}: ${reason}`],
    [/^([A-Za-z]+(?:Error|Exception)): (.+)$/, (_, type, message) => `${type}: ${translate(message)}`],
    [/^FFmpeg 下载失败（(.+)）$/, (_, reason) => `FFmpeg download failed (${reason})`],
    [/^yt-dlp (.+) 已是最新版本$/, (_, version) => `yt-dlp ${version} is up to date`],
    [/^yt-dlp 已更新到 (.+)，下次同步生效$/, (_, version) => `yt-dlp updated to ${version}; effective on the next sync`],
    [/^yt-dlp 更新检查失败：(.+)$/, (_, reason) => `yt-dlp update check failed: ${reason}`],
    [/^([^\n]+)：([^\n]+)$/, (_, prefix, message) => `${prefix}: ${translate(message)}`],
  ];
  function translate(text) {
    if (text.includes('\n')) return text.split('\n').map(translate).join('\n');
    const trimmed = text.trim();
    let result = translations[trimmed];
    if (result === undefined) for (const [pattern, replace] of patterns) { if (pattern.test(trimmed)) { result = trimmed.replace(pattern, replace); break; } }
    return result === undefined ? text : text.replace(trimmed, result);
  }
  const originals = new WeakMap(), attrs = new WeakMap();
  function excluded(el) {
    return !!el.closest('script,style,textarea,code:not(.naming-note code),.author-cell a,.author-handle,.tile-caption,.recent-caption,.picker-option,.media-filename,#viewer-author') || (el.tagName === 'OPTION' && el.parentElement?.id === 'media-author' && el.value !== '0');
  }
  function updateText(node) {
    const el = node.parentElement;
    if (!el || excluded(el)) return;
    let saved = originals.get(node);
    if (!saved || (node.data !== saved.original && node.data !== saved.translated)) {
      saved = {original:node.data, translated:translate(node.data)}; originals.set(node, saved);
    }
    const value = window.appLanguage === 'en' ? saved.translated : saved.original;
    if (node.data !== value) node.data = value;
  }
  function updateAttributes(el) {
    if (excluded(el)) return;
    let saved = attrs.get(el); if (!saved) { saved = {}; attrs.set(el, saved); }
    for (const name of ['title','aria-label','placeholder','alt']) {
      const current = el.getAttribute(name); if (current === null) continue;
      let entry = saved[name];
      if (!entry || (current !== entry.original && current !== entry.translated)) entry = saved[name] = {original:current, translated:translate(current)};
      const value = window.appLanguage === 'en' ? entry.translated : entry.original;
      if (current !== value) el.setAttribute(name,value);
    }
  }
  function update(root) {
    if (root.nodeType === Node.TEXT_NODE) { updateText(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE) return;
    updateAttributes(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) { const node = walker.currentNode; if (node.nodeType === Node.TEXT_NODE) updateText(node); else updateAttributes(node); }
  }
  function setLanguage(language) {
    window.appLanguage = language === 'en' ? 'en' : 'zh-CN';
    document.documentElement.lang = window.appLanguage;
    try { localStorage.setItem('xarchive-language',window.appLanguage); } catch (_) {}
    const token = document.querySelector('meta[name="app-token"]')?.content;
    if (token) fetch('/api/ui-language', {method:'PUT', headers:{'Content-Type':'application/json','X-App-Token':token}, body:JSON.stringify({language:window.appLanguage})}).catch(() => {});
    document.querySelectorAll('[data-language]').forEach(button => button.setAttribute('aria-checked',String(button.dataset.language === window.appLanguage)));
    update(document.body);
    window.dispatchEvent(new Event('app-language-change'));
  }
  let stored; try { stored = localStorage.getItem('xarchive-language'); } catch (_) {}
  setLanguage(stored);
  document.querySelectorAll('[data-language]').forEach(button => button.addEventListener('click',() => setLanguage(button.dataset.language)));
  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') updateText(record.target);
      else if (record.type === 'attributes') updateAttributes(record.target);
      else record.addedNodes.forEach(update);
    }
  }).observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['title','aria-label','placeholder','alt']});
})();
