"""One isolated gallery-dl job. Credentials arrive through stdin, never argv/files."""
import collections
import json
import logging
import os
import shutil
import sys
import copy
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from gallery_dl.extractor.common import Extractor, Message
from datetime import datetime, timezone
from pathlib import Path

from gallery_dl import config, exception
from gallery_dl.job import DownloadJob

PAYLOAD = {}
YTDL_USED = False
SUMMARY = {"downloaded": 0, "skipped": 0, "seen": 0}
EVENT_LOCK = threading.RLock()
HTTP_LOCAL = threading.local()


def media_folder():
    return Path(PAYLOAD["settings"]["download_dir"]) / (PAYLOAD.get("folder_name") or PAYLOAD["handle"])


def is_target(profile):
    return (str(profile.get("id")) == str(PAYLOAD["user_id"]) if PAYLOAD.get("user_id")
            else profile.get("name", "").lower() == PAYLOAD["handle"].lower())


def emit(event, **fields):
    with EVENT_LOCK:
        print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def as_utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def date_prefix(value):
    return as_utc(value).strftime("%Y-%m-%d_%H%M%SZ")


class Events(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.INFO:
            message = record.getMessage()
            for value in PAYLOAD.get("credentials", {}).values():
                if value:
                    message = message.replace(value, "[hidden]")
            emit("log", level=record.levelname.lower(), message=message)


class QuietOutput:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class AssetJob(DownloadJob):
    def __init__(self, url, parent=None):
        super().__init__(url, parent)
        self.out = QuietOutput()
        self.ignore = False
        self.older = 0

    def initialize(self, kwdict=None):
        super().initialize(kwdict)
        if not self.hooks:
            self.hooks = collections.defaultdict(list)
        self.register_hooks({"after": self.saved, "skip": self.skipped})
        if self.archive is not None:
            recorded = self.archive.check

            def check_existing(metadata):
                if not recorded(metadata):
                    return False
                self.pathfmt.fix_extension()
                path = Path(self.pathfmt.realpath)
                if path.is_file():
                    if path.stat().st_size > 0:
                        return True
                    path.unlink()  # A zero-byte failed file is repairable, not an intentional deletion.
                return False

            self.archive.check = check_existing

    def handle_url(self, url, kwdict):
        if excluded(kwdict):
            report_excluded(kwdict)
            return
        kwdict["_app_date"] = date_prefix(kwdict.get("date_original") or kwdict["date"])
        media_url = url.partition("?")[0].lower()
        if media_url.endswith((".m3u8", ".mpd")):
            from app import ffmpeg_fetch
            if not ffmpeg_fetch.ensure(PAYLOAD["data_dir"], PAYLOAD.get("proxy"), self.log.info):
                self.status |= 4
                self.log.error("此视频需要 FFmpeg 合并原始流。FFmpeg 自动下载失败，请检查网络/代理后重试，或手动把 ffmpeg.exe 放到数据目录的 ffmpeg 文件夹，不会保存为播放列表文件。")
                return
            global YTDL_USED
            YTDL_USED = True
            kwdict["_ytdl_manifest"] = "hls" if media_url.endswith(".m3u8") else "dash"
            kwdict["extension"] = "mp4"
            url = "ytdl:" + url
        super().handle_url(url, kwdict)

    def saved(self, pathfmt):
        if excluded(pathfmt.kwdict):
            Path(pathfmt.realpath).unlink(missing_ok=True)
            report_excluded(pathfmt.kwdict)
            return
        with EVENT_LOCK:
            SUMMARY["downloaded"] += 1
            self.report_media(pathfmt, "saved")

    def skipped(self, pathfmt):
        with EVENT_LOCK:
            SUMMARY["skipped"] += 1
            self.report_media(pathfmt, "skipped")

    def report_media(self, pathfmt, event):
        path = Path(pathfmt.realpath)
        if not path.is_file():
            return
        metadata = pathfmt.kwdict
        posted = as_utc(metadata.get("date_original") or metadata["date"])
        if event == "saved":
            os.utime(path, (posted.timestamp(), posted.timestamp()))
        emit(event, path=str(path.resolve()), tweet_id=str(metadata["tweet_id"]),
             num=metadata["num"], published_at=posted.isoformat(), size=path.stat().st_size,
             kind="video" if path.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"} else "image")


def excluded(metadata):
    database = Path(PAYLOAD["data_dir"]) / "library.sqlite3"
    if not database.exists():
        return False
    with sqlite3.connect(database, timeout=30) as db:
        key = (str(metadata["tweet_id"]), metadata["num"])
        if db.execute("SELECT 1 FROM exclusions WHERE tweet_id=? AND num=?", key).fetchone():
            return True
        from .store import canonical_path, utcnow
        target = canonical_path(media_folder())
        # Recheck at dispatch time too: Explorer deletion may happen during a long scan.
        for (filename,) in db.execute("SELECT path FROM media WHERE tweet_id=? AND num=?", key).fetchall():
            path = canonical_path(filename)
            if path.parent != target:
                continue
            try:
                path.stat()
            except FileNotFoundError:
                if not target.is_dir():
                    raise OSError("Media folder unavailable")
                db.execute("INSERT OR IGNORE INTO exclusions VALUES (?,?,?,?,?,?)",
                           (*key, PAYLOAD["handle"], filename, "external", utcnow()))
                return True
        return False


def report_excluded(metadata):
    with EVENT_LOCK:
        SUMMARY["skipped"] += 1
        emit("excluded", tweet_id=str(metadata["tweet_id"]), num=metadata["num"])


class AssetExtractor(Extractor):
    # A CDN download has its own HTTP session, PathFormat and archive connection.
    # It never issues a Twitter API request or shares mutable extractor state.
    category = "twitter"
    subcategory = "asset"
    filename_fmt = "{tweet_id}_{num}.{extension}"
    directory_fmt = ("{category}",)
    archive_fmt = "{tweet_id}_{num}"
    root = "https://x.com"
    url = "https://x.com/asset"
    cookies_domain = None

    def __init__(self, url, metadata):
        import re
        super().__init__(re.match(r".*", self.url))
        self.session = getattr(HTTP_LOCAL, "session", None)
        self.asset_url, self.metadata = url, metadata

    def initialize(self):
        super().initialize()
        HTTP_LOCAL.session = self.session

    def items(self):
        yield Message.Directory, "", self.metadata
        yield Message.Url, self.asset_url, self.metadata


class Pipeline:
    def __init__(self):
        media_folder().mkdir(parents=True, exist_ok=True)
        # Set WAL once before starting workers. Reissuing journal_mode from every
        # concurrent archive connection can fail immediately while another writes.
        archive_path = build_config(PAYLOAD)['extractor']['twitter']['archive']
        with sqlite3.connect(archive_path, timeout=30) as db:
            db.execute('PRAGMA journal_mode=WAL').fetchone()
        self.pool = ThreadPoolExecutor(max_workers=PAYLOAD["settings"].get("download_concurrency", 4),
                                       thread_name_prefix="media-download")
        self.slots = threading.BoundedSemaphore(32)
        self.lock = threading.Lock()
        self.keys = set()
        self.status = 0
        self.avatar_requested = False

    def submit(self, key, task, *args):
        if key in self.keys:
            return
        self.keys.add(key)
        self.slots.acquire()  # bounded prefetch keeps memory and expired media URLs bounded
        future = self.pool.submit(task, *args)
        future.add_done_callback(self.complete)

    def complete(self, future):
        try:
            status = future.result() or 0
        except Exception as exc:
            logging.error("并发下载任务失败：%s", type(exc).__name__)
            status = 1
        with self.lock:
            self.status |= status
        self.slots.release()


def asset_metadata(metadata):
    # Twitter metadata includes nested generator fallbacks and live path proxies.
    # Copy only fields the filename, archive and download hooks actually consume.
    keys = ("tweet_id", "num", "date", "date_original", "extension", "author", "user", "type", "bitrate", "duration")
    result = {k: copy.deepcopy(metadata[k]) for k in keys if k in metadata}
    # Our image policy deliberately has no lower-quality fallbacks.
    return result


def download_asset(url, metadata):
    return AssetJob(AssetExtractor(url, metadata)).run()


def save_avatar(url):
    # Only accept profile images hosted by Twitter; no credentials sent to other hosts.
    hostname = (urlparse(url).hostname or '').lower()
    platform = PAYLOAD.get('platform', 'twitter')
    allowed = {'twitter': ('pbs.twimg.com', 'abs.twimg.com'),
               'instagram': ('cdninstagram.com', 'fbcdn.net'),
               'weibo': ('sinaimg.cn',)}[platform]
    if not any(hostname == host or hostname.endswith('.' + host) for host in allowed):
        return
    import requests
    from PIL import Image
    from io import BytesIO
    session = requests.Session()
    if PAYLOAD.get("proxy"):
        session.proxies.update({"https": PAYLOAD["proxy"], "http": PAYLOAD["proxy"]})
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        content = response.content
        if len(content) > 10_000_000:
            raise ValueError("Avatar too large")
        with Image.open(BytesIO(content)) as image:
            extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}[image.format]
            image.verify()
        cached = Path(PAYLOAD["data_dir"]) / "avatars" / ((PAYLOAD.get("user_id") or PAYLOAD["handle"].lower()).replace(':', '_') + ".img")
        cached.parent.mkdir(parents=True, exist_ok=True)
        temp = cached.with_suffix(".part")
        temp.write_bytes(content)
        temp.replace(cached)
        folder = media_folder()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / ("avatar." + extension)
        shutil.copyfile(cached, target)
        emit("avatar", path=str(target), size=len(content))
    except Exception as exc:
        # Avatar failure doesn't certify a media failure, nor advance a failed media scan.
        emit("log", level="info", message="头像暂未更新：" + type(exc).__name__)
    finally:
        session.close()


class ArchiveJob(AssetJob):
    def __init__(self, url, parent=None):
        super().__init__(url, parent)
        self.pipeline_owner = parent is None or not hasattr(parent, "pipeline")
        self.pipeline = Pipeline() if self.pipeline_owner else parent.pipeline

    def handle_directory(self, kwdict):
        for profile in (kwdict.get("user", {}), kwdict.get("author", {})):
            if (is_target(profile)
                    and profile.get("profile_image") and not self.pipeline.avatar_requested):
                self.pipeline.avatar_requested = True
                self.pipeline.submit("avatar", save_avatar, profile["profile_image"])
        published = as_utc(kwdict.get("date_original") or kwdict["date"])
        cutoff = PAYLOAD.get("cutoff")
        self.ignore = not (
            is_target(kwdict.get("author", {})) or
            PAYLOAD["settings"]["include_retweets"] and kwdict.get("retweet_id") or
            PAYLOAD["settings"]["include_quotes"] and kwdict.get("quote_id")
        )
        if cutoff and published < as_utc(cutoff):
            self.ignore = True
            self.older += 1
            # Don't stop at one old pinned/out-of-order tweet.
            if self.older >= 40:
                raise exception.StopExtraction()
        else:
            self.older = 0
        SUMMARY["seen"] += 1
        if SUMMARY["seen"] % 20 == 0:
            emit("progress", **SUMMARY)
        if not self.ignore:
            super().handle_directory(kwdict)


    def handle_url(self, url, kwdict):
        if self.ignore:
            return
        key = (str(kwdict["tweet_id"]), kwdict["num"])
        self.pipeline.submit(key, download_asset, url, asset_metadata(kwdict))

    def handle_finalize(self):
        try:
            super().handle_finalize()
        finally:
            if self.pipeline_owner:
                self.pipeline.pool.shutdown(wait=True)
                self.status |= self.pipeline.status


def build_config(payload):
    settings = payload["settings"]
    root = Path(settings["download_dir"]).resolve()
    archive = Path(payload["data_dir"]) / "archives" / (payload.get("archive_key") or payload["handle"].lower().replace(':', '_'))
    archive.mkdir(parents=True, exist_ok=True)
    # Archive is scoped to destination: changing the folder must not suppress downloads.
    import hashlib
    destination_id = hashlib.sha256(str(root).lower().encode()).hexdigest()[:16]
    twitter = {
        "base-directory": str(root), "directory": [payload.get("folder_name") or payload["handle"]],
        "filename": "{_app_date}_{tweet_id}_{num:02}.{extension}",
        "archive": str(archive / f"{destination_id}.sqlite3"),
        "archive-format": "{tweet_id}_{num}", "archive-event": "file",
        "cookies": {k: v for k, v in payload["credentials"].items() if v} if payload.get('platform', 'twitter') == 'twitter' else {},
        "size": ["orig"], "videos": True, "previews": False,
        "retweets": settings["include_retweets"], "quoted": settings["include_quotes"],
        "replies": settings["include_replies"], "pinned": False,
        "strategy": "with_replies" if settings["include_replies"] else "media",
        "ratelimit": "abort", "retries-api": 3,
        "sleep-request": "1.0-2.0", "sleep": 0, "skip": True,
        "archive-reuse": False, "async": False,
        "path-restrict": "windows", "path-extended": True,
    }
    if payload.get("proxy"):
        twitter["proxy"] = payload["proxy"]
    platform = payload.get('platform', 'twitter')
    extractors = {"twitter": twitter, "timeout": 30, "retries": 3}
    if platform != 'twitter':
        extractors[platform] = {"cookies": {k: v for k, v in payload['credentials'].items() if v},
                                "videos": 'merged' if platform == 'instagram' else True,
                                "sleep-request": '1.0-2.0' if platform == 'weibo' else '6.0-12.0',
                                "retries": 3, "proxy": payload.get('proxy') or None}
    return {"extractor": extractors,
            "output": {"mode": "null"}, "downloader": {"http": {"part": True},
                "ytdl": {"module": "yt_dlp", "format": "bestvideo*+bestaudio/best",
                         "raw-options": {"noplaylist": True}}}}


def run_external():
    """Adapt platform records to the same download and tombstone pipeline as X."""
    from gallery_dl import extractor
    from app.platforms import media_metadata
    platform, account = PAYLOAD['handle'].split(':', 1)
    urls = ([f'https://www.instagram.com/{account}/posts/', f'https://www.instagram.com/{account}/reels/']
            if platform == 'instagram' else [f'https://weibo.com/u/{account}?tabtype=feed'])
    if PAYLOAD.get('_verify_reels') and platform == 'instagram':
        urls = urls[1:]
    pipeline = None
    ignore = False
    old_count = 0
    try:
        for url in urls:
            source = extractor.find(url)
            if source is None:
                raise ValueError('不支持的主页链接')
            old_count = 0
            for kind, value, metadata in source:
                if kind == Message.Directory:
                    if PAYLOAD.get('_max_posts') and SUMMARY['seen'] >= PAYLOAD['_max_posts']:
                        break  # Bounded isolated verification only; normal sync never sets this.
                    user = metadata.get('user') or {}
                    user_id = str((user.get('pk') or user.get('id')) if platform == 'instagram' else user.get('id'))
                    if not user_id.isdigit():
                        raise ValueError('无法确认账号身份，已停止扫描')
                    if platform == 'weibo' and user_id != account:
                        ignore = True
                        continue
                    if pipeline is None:
                        display = (metadata.get('fullname') or user.get('full_name') or account) if platform == 'instagram' else (user.get('screen_name') or account)
                        emit('profile', user_id=user_id, handle=account, display_name=display)
                        PAYLOAD.update(json.loads(sys.stdin.readline()))
                        for key, setting in build_config(PAYLOAD).items():
                            config.set((), key, setting)
                        pipeline = Pipeline()
                        avatar = user.get('profile_pic_url') if platform == 'instagram' else (user.get('avatar_hd') or user.get('avatar_large'))
                        if avatar:
                            pipeline.submit('avatar', save_avatar, avatar)
                    elif PAYLOAD.get('user_id') != f'{platform}:{user_id}':
                        ignore = True
                        continue
                    date = metadata.get('date')
                    if not date:
                        raise ValueError('帖子缺少发文日期，已停止扫描')
                    cutoff = PAYLOAD.get('cutoff')
                    ignore = bool(cutoff and as_utc(date) < as_utc(cutoff))
                    old_count = old_count + 1 if ignore else 0
                    SUMMARY['seen'] += 1
                    if old_count >= 40:
                        break
                elif kind == Message.Url and not ignore and pipeline:
                    normalized = media_metadata(platform, metadata)
                    if metadata.get('_http_headers'):
                        normalized['_http_headers'] = copy.deepcopy(metadata['_http_headers'])
                    if platform == 'weibo':
                        normalized.setdefault('_http_headers', {})['Referer'] = 'https://weibo.com/'
                    pipeline.submit((normalized['tweet_id'], normalized['num']), download_asset, value, normalized)
    finally:
        if pipeline:
            pipeline.pool.shutdown(wait=True)
    status = pipeline.status if pipeline else 0
    emit('done', status=status, **SUMMARY)
    return 1 if status else 0


def main():
    global PAYLOAD
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    PAYLOAD = json.loads(sys.stdin.readline())
    logging.basicConfig(level=logging.INFO, handlers=[Events()], force=True)
    from app import ytdlp_update
    ytdlp_update.prefer_local(PAYLOAD["data_dir"])
    for key, value in build_config(PAYLOAD).items():
        config.set((), key, value)
    config.set((), "cache", {"file": str(Path(PAYLOAD["data_dir"]) / "gallery-cache.sqlite3")})
    try:
        if PAYLOAD.get('platform', 'twitter') != 'twitter':
            return run_external()
        identity = "id:" + PAYLOAD["user_id"] if PAYLOAD.get("user_id") else PAYLOAD["handle"]
        from gallery_dl import extractor
        profile_extractor = extractor.find(f"https://x.com/{identity}/info")
        for _, _, profile in profile_extractor:
            emit("profile", user_id=str(profile["id"]), handle=profile["name"], display_name=profile["nick"])
        # Parent binds the immutable folder and migrates existing files before any download starts.
        binding = json.loads(sys.stdin.readline())
        PAYLOAD.update(binding)
        for key, value in build_config(PAYLOAD).items():
            config.set((), key, value)
        identity = "id:" + PAYLOAD["user_id"]
        job = ArchiveJob(f"https://x.com/{identity}/timeline")
        status = job.run()
        if status and YTDL_USED:
            logging.info(ytdlp_update.update_if_newer(PAYLOAD["data_dir"], PAYLOAD.get("proxy")))
        emit("done", status=status, **SUMMARY)
        return 1 if status else 0
    except Exception as exc:
        logging.error("%s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
