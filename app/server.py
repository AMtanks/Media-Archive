import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
import secrets
import time
import hashlib
import hmac
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .engine import Engine
from .secrets import Vault
from .store import Store, canonical_path, utcnow
from .previews import PreviewCache, IMAGE_TYPES, VIDEO_TYPES

STATIC = Path(__file__).parent / "static"


class AuthorInput(BaseModel):
    handle: str = Field(min_length=1, max_length=200)


class SettingsInput(BaseModel):
    download_dir: str = Field(min_length=3, max_length=500)
    interval_minutes: int = Field(ge=15, le=10080)
    overlap_days: int = Field(ge=1, le=90)
    automatic: bool
    proxy: str = Field(default="", max_length=500)
    include_replies: bool = True
    include_retweets: bool = False
    include_quotes: bool = False
    download_concurrency: int = Field(default=4, ge=1, le=8)


class CredentialsInput(BaseModel):
    auth_token: str = Field(min_length=10, max_length=4096)
    ct0: str = Field(default="", max_length=4096)


class SyncInput(BaseModel):
    full: bool = False


class ToggleInput(BaseModel):
    enabled: bool


class MediaInput(BaseModel):
    path: str = Field(max_length=1000)


class BatchMediaInput(BaseModel):
    media_ids: list[int] = Field(min_length=1, max_length=100)


class RestoreInput(BaseModel):
    tweet_id: str = Field(pattern=r"^(?:(?:instagram|weibo):)?\d+$", max_length=60)
    num: int = Field(ge=1, le=100)


class LanguageInput(BaseModel):
    language: str


def create_app(data_dir, start_engine=True):
    store = Store(data_dir)
    vault = Vault(store.root)
    engine = Engine(store, vault)
    token = secrets.token_urlsafe(32)
    previews = PreviewCache(store.root)
    preview_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="preview")

    def preview_key(media_id, variant):
        return hmac.new(token.encode(), f"{media_id}:{variant}".encode(), hashlib.sha256).hexdigest()

    def with_previews(items):
        for item in items:
            if "media_id" in item:
                item["thumbnail_url"] = f"/preview/{item['media_id']}/thumb?key={preview_key(item['media_id'], 'thumb')}"
                item["content_url"] = f"/preview/{item['media_id']}/content?key={preview_key(item['media_id'], 'content')}"
        return items

    @asynccontextmanager
    async def lifespan(app):
        if start_engine:
            engine.start()
        yield
        if start_engine:
            engine.close()
        preview_executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="X Archive", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.vault, app.state.engine = store, vault, engine
    app.state.login_callback = None
    app.state.language_callback = None
    app.state.finish_weibo_login = None
    app.state.folder_callback = None
    app.state.activate_callback = None
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return HTMLResponse("Forbidden origin", status_code=403)
            if request.headers.get("x-app-token") != token:
                return HTMLResponse("Missing local session", status_code=403)
            if request.headers.get("content-length", "0").isdigit() and int(request.headers.get("content-length", "0")) > 20000:
                return HTMLResponse("Request too large", status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # Preview URLs carry a per-launch HMAC key, so the browser may cache thumbnails and originals for the session.
        preview = request.url.path.startswith("/preview/") and response.status_code == 200
        response.headers["Cache-Control"] = "private, max-age=86400" if preview else "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    # A second launch asks the running window to come forward. The custom header forces a CORS preflight, so web pages cannot trigger it.
    @app.post("/activate", status_code=204)
    def activate(request: Request):
        if request.headers.get("x-activate") != "1":
            raise HTTPException(403)
        # The callback returns False while the app is quitting; the caller then waits and starts a fresh instance.
        if app.state.activate_callback is None or app.state.activate_callback() is False:
            raise HTTPException(409)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text(encoding="utf-8").replace("__APP_TOKEN__", token)

    @app.get("/api/state")
    def state():
        engine.maintain_catalog()
        result = store.snapshot()
        visible = store.gallery_author_ids()
        result["totals"]["excluded"] = store.media_page(excluded=True, visible_author_ids=visible)["total"]
        for author in result["authors"]:
            if author["status"] == "queued":
                if author["id"] in engine.manual_pending:
                    author["queue_reason"] = "等待当前扫描结束后立即开始" if engine.current else "即将开始手动同步"
                elif ':' not in author['handle'] and store.get_setting("rate_limit_until", "") > utcnow():
                    author["queue_reason"] = "X 限流冷却中，可点立即同步尝试"
                else:
                    author["queue_reason"] = "等待前面的扫描完成"
            author["gallery_available"] = author["id"] in visible
            avatar_file = store.avatar_path(author)
            author["avatar_url"] = f"/avatars/{author['id']}?v={avatar_file.stat().st_mtime_ns}" if avatar_file.is_file() else None
        result["recent"] = [m for m in result["recent"] if m["author_id"] in visible]
        with_previews(result["recent"])
        settings = store.settings()
        settings.pop("initialized", None)
        result["settings"] = settings
        try:
            result["credentials_saved"] = bool(vault.read().get("auth_token"))
            result["credential_error"] = ""
        except Exception:
            result["credentials_saved"] = False
            result["credential_error"] = "登录凭证无法解密，请重新登录"
        result["desktop_login"] = app.state.login_callback is not None
        from .secrets import PlatformVault
        result["platform_credentials"] = {}
        for platform in ("instagram", "weibo"):
            try:
                result["platform_credentials"][platform] = bool(PlatformVault(store.root, platform).read())
            except Exception:
                result["platform_credentials"][platform] = False
        result["folder_picker"] = app.state.folder_callback is not None
        result["engine_version"] = __import__("gallery_dl.version", fromlist=["__version__"]).__version__
        result["running_author"] = engine.current
        return result

    @app.put("/api/ui-language")
    def ui_language(body: LanguageInput):
        if body.language not in {'zh-CN', 'en'}:
            raise HTTPException(400, 'Unsupported language')
        store.save_settings({'ui_language': body.language})
        if app.state.language_callback:
            app.state.language_callback()
        return {'ok': True}

    @app.post("/api/authors")
    def add_author(body: AuthorInput):
        try:
            return {"id": store.add_author(body.handle)}
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/avatars/{author_id}")
    def avatar(author_id: int):
        author = require_author(author_id)
        path = store.avatar_path(author)
        if not path.is_file():
            raise HTTPException(404, "头像尚未保存")
        from PIL import Image
        with Image.open(path) as image:
            mime = Image.MIME.get(image.format, "image/jpeg")
        return FileResponse(path, media_type=mime)

    @app.get("/api/media")
    def media(author_id: int = 0, excluded: bool = False, offset: int = 0, kind: str = "all", all_items: bool = False, platform: str = "all"):
        if offset < 0:
            raise HTTPException(400, "页码无效")
        if platform not in {"all", "twitter", "instagram", "weibo"}:
            raise HTTPException(400, "平台筛选无效")
        engine.maintain_catalog()
        result = store.media_page(author_id, excluded, offset, kind, store.gallery_author_ids(), all_items=all_items, platform=platform)
        with_previews(result["items"])
        return result

    @app.get("/preview/{media_id}/{variant}")
    async def preview(media_id: int, variant: str, key: str = ""):
        if variant not in {"thumb", "content"} or not hmac.compare_digest(key, preview_key(media_id, variant)):
            raise HTTPException(403, "预览链接已失效，请刷新应用")
        with store.connect() as db:
            row = db.execute("""SELECT m.* FROM media m JOIN authors a ON a.id=m.author_id WHERE m.rowid=? AND a.folder_removed=0 AND NOT EXISTS
                (SELECT 1 FROM exclusions e WHERE e.tweet_id=m.tweet_id AND e.num=m.num)""", (media_id,)).fetchone()
        path = canonical_path(row["path"]) if row else None
        if not path or not path.is_file() or path.suffix.lower() not in IMAGE_TYPES | VIDEO_TYPES:
            raise HTTPException(404, "文件已不在原位置")
        if variant == "thumb":
            try:
                return FileResponse(await asyncio.get_running_loop().run_in_executor(preview_executor, previews.thumbnail, path), media_type="image/jpeg")
            except Exception as exc:
                # Do not expose local paths or media metadata in a decoder traceback.
                raise HTTPException(422, "暂时无法生成预览，可打开本地文件查看") from exc
        return FileResponse(path, filename=path.name, content_disposition_type="inline")

    @app.post("/api/media/delete")
    def delete_media(body: MediaInput):
        with store.connect() as db:
            row = db.execute("SELECT m.*,a.handle FROM media m LEFT JOIN authors a ON a.id=m.author_id WHERE path=?", (body.path,)).fetchone()
        if not row:
            raise HTTPException(404, "媒体记录不存在")
        delete_record(row)
        return {"ok": True}

    def delete_record(row):
        path = Path(row["path"])
        folder = Path(store.get_setting("download_dir"))
        if not canonical_path(path).is_relative_to(canonical_path(folder)) or not row["handle"]:
            raise HTTPException(409, "文件位于旧的保存位置，请在资源管理器中处理")
        # Persist exclusion before unlink: an in-flight worker checks it again after writing.
        store.exclude(row["tweet_id"], row["num"], row["handle"], str(path), "manual")
        # A player that just released the file can keep its handle for a moment on Windows; retry briefly.
        for attempt in range(6):
            try:
                path.unlink(missing_ok=True)
                break
            except OSError:
                if attempt == 5:
                    raise HTTPException(409, "已加入忽略清单，但文件删除失败，请关闭占用文件的程序后重试")
                time.sleep(0.2)

    @app.post("/api/media/delete-batch")
    def delete_media_batch(body: BatchMediaInput):
        deleted, failed = [], []
        with engine.lock:
            for media_id in dict.fromkeys(body.media_ids):
                with store.connect() as db:
                    row = db.execute("SELECT m.*,a.handle FROM media m JOIN authors a ON a.id=m.author_id WHERE m.rowid=?", (media_id,)).fetchone()
                if not row:
                    failed.append({"media_id": media_id, "error": "媒体记录不存在"})
                    continue
                try:
                    delete_record(row)
                    deleted.append(media_id)
                except HTTPException as exc:
                    failed.append({"media_id": media_id, "error": exc.detail})
        return {"deleted": deleted, "failed": failed}

    @app.post("/api/media/open")
    def open_media(body: MediaInput):
        with store.connect() as db:
            row = db.execute("SELECT path FROM media WHERE path=?", (body.path,)).fetchone()
        path = canonical_path(row[0]) if row else None
        if not path or not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mkv", ".mov"}:
            raise HTTPException(404, "媒体文件不存在或格式不支持")
        if os.name == "nt":
            os.startfile(str(path))
        return {"ok": True}

    @app.post("/api/media/restore")
    def restore_media(body: RestoreInput):
        with engine.lock:
            if engine.pending:
                raise HTTPException(409, "请先停止下载任务，再允许媒体重新下载")
            with store.connect() as db:
                # Remove the absent-file record too, so reconciliation won't exclude it again.
                db.execute("DELETE FROM media WHERE tweet_id=? AND num=? AND EXISTS (SELECT 1 FROM exclusions WHERE tweet_id=? AND num=?)",
                           (body.tweet_id, body.num, body.tweet_id, body.num))
                db.execute("DELETE FROM exclusions WHERE tweet_id=? AND num=?", (body.tweet_id, body.num))
        return {"ok": True}

    def require_author(author_id):
        author = store.author(author_id)
        if not author:
            raise HTTPException(404, "推主不存在")
        return author

    @app.patch("/api/authors/{author_id}")
    def toggle_author(author_id: int, body: ToggleInput):
        require_author(author_id)
        store.update_author(author_id, enabled=int(body.enabled))
        return {"ok": True}

    @app.delete("/api/authors/{author_id}")
    def delete_author(author_id: int, delete_files: bool = False):
        with engine.lock:
            author = require_author(author_id)
            if author_id in engine.pending:
                raise HTTPException(409, "请先停止这个推主的任务，再移出列表")
            if delete_files:
                try:
                    store.delete_author_files(author)
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc
                except OSError as exc:
                    raise HTTPException(409, "文件删除未完成，推主仍保留在列表中；请检查文件占用和权限，部分文件可能已删除") from exc
            store.clear_author_catalog(author_id, remove=True)
        return {"ok": True}

    @app.post("/api/authors/{author_id}/sync")
    def sync_author(author_id: int, body: SyncInput):
        require_author(author_id)
        try:
            return {"queued": engine.enqueue(author_id, body.full, manual=True)}
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/sync-all")
    def sync_all():
        count, skipped = 0, 0
        for author in store.authors():
            if author['enabled']:
                try:
                    count += engine.enqueue(author['id'])
                except ValueError:
                    skipped += 1
        return {"queued": count, "unavailable": skipped}

    @app.post("/api/authors/{author_id}/cancel")
    def cancel(author_id: int):
        require_author(author_id)
        engine.cancel(author_id)
        return {"ok": True}

    @app.put("/api/settings")
    def settings(body: SettingsInput):
        values = body.model_dump()
        target = Path(values["download_dir"]).expanduser()
        if not target.is_absolute():
            raise HTTPException(400, "保存位置必须是完整的绝对路径")
        protected = [store.root, Path(__file__).resolve().parent,
                     Path(__file__).resolve().parent.parent / ".venv"]
        if any(target.resolve() == p or p in target.resolve().parents for p in protected):
            raise HTTPException(400, "请选择独立的媒体文件夹，不要使用应用数据或代码目录")
        proxy = values["proxy"].strip()
        if proxy and (urlparse(proxy).scheme not in {"http", "https", "socks5", "socks5h"} or not urlparse(proxy).hostname):
            raise HTTPException(400, "代理格式示例：http://127.0.0.1:7890")
        values["proxy"] = proxy
        with engine.lock:
            previous = store.settings()
            critical = {"download_dir", "include_replies", "include_retweets", "include_quotes"}
            changed = any(values[k] != previous[k] for k in critical)
            if changed and engine.pending:
                raise HTTPException(409, "请先停止下载任务，再修改保存位置或媒体范围")
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise HTTPException(400, "无法创建保存文件夹，请检查路径和写入权限")
            values["download_dir"] = str(target.resolve())
            store.save_settings(values)
            with store.connect() as db:
                if changed:
                    db.execute("UPDATE authors SET last_success=NULL,next_run=NULL")
                else:
                    from datetime import datetime, timedelta, timezone
                    next_run = (datetime.now(timezone.utc) + timedelta(minutes=values["interval_minutes"])).isoformat()
                    db.execute("UPDATE authors SET next_run=? WHERE next_run IS NOT NULL AND retry_count=0", (next_run,))
        return {"ok": True}

    @app.put("/api/credentials")
    def credentials(body: CredentialsInput):
        try:
            vault.save(body.auth_token.strip(), body.ct0.strip())
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True}

    @app.delete("/api/credentials")
    def clear_credentials():
        with engine.lock:
            if engine.pending:
                raise HTTPException(409, "请先停止所有下载任务")
            vault.clear()
        return {"ok": True}

    @app.post("/api/login")
    def login():
        if app.state.login_callback is None:
            raise HTTPException(400, "请从桌面启动器打开应用，或手动填写 Cookie")
        app.state.login_callback()
        return {"ok": True}

    @app.post("/api/login/{platform}")
    def platform_login(platform: str):
        if platform not in {"instagram", "weibo"}:
            raise HTTPException(404, "不支持的平台")
        if app.state.login_callback is None:
            raise HTTPException(400, "请从桌面启动器打开应用")
        app.state.login_callback(platform)
        return {"ok": True}

    @app.delete("/api/credentials/{platform}")
    def clear_platform_credentials(platform: str):
        if platform not in {"instagram", "weibo"}:
            raise HTTPException(404, "不支持的平台")
        from .secrets import PlatformVault
        with engine.lock:
            if engine.pending:
                raise HTTPException(409, "请先停止所有下载任务")
            PlatformVault(store.root, platform).clear()
        return {"ok": True}

    @app.post("/api/login/weibo/finish")
    def finish_weibo_login():
        if app.state.finish_weibo_login is None or not app.state.finish_weibo_login():
            raise HTTPException(409, "请先打开微博登录窗口并完成登录")
        return {"ok": True}

    @app.post("/api/pick-folder")
    def pick_folder():
        if app.state.folder_callback is None:
            raise HTTPException(400, "当前窗口不支持选择文件夹，请直接填写路径")
        return {"path": app.state.folder_callback()}

    @app.post("/api/open-folder")
    def open_folder():
        folder = Path(store.get_setting("download_dir"))
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(folder))
        return {"ok": True}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
