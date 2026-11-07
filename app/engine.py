import json
import itertools
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import getproxies

from .store import utcnow, canonical_path


def incremental_cutoff(author, settings, full=False):
    if full or not author.get("last_success"):
        return None
    return (datetime.fromisoformat(author["last_success"]) -
            timedelta(days=settings["overlap_days"])).isoformat()


def transient_failure(message):
    text = message.lower()
    return any(term in text for term in ("rate limit", "429", "timeout", "timed out", "connection", "network", "网络", "本轮未返回媒体"))


def rate_limited(message):
    text = message.lower()
    return "rate limit" in text or "429" in text


class Engine:
    def __init__(self, store, vault):
        self.store, self.vault = store, vault
        self.queue = queue.PriorityQueue()
        self.sequence = itertools.count()
        self.queue_wakeup = threading.Event()
        self.manual_pending = set()
        self.pending = {}
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.process = None
        self.current = None
        self.cancelled = False
        # Upgrade old rate-limit failures once: the old daily schedule delayed retries.
        if not self.store.get_setting("retry_upgrade_done", False):
            now = datetime.now(timezone.utc)
            rate_until = ""
            with self.store.connect() as db:
                for row in db.execute("SELECT id,error FROM authors WHERE status='error'").fetchall():
                    if not transient_failure(row["error"]):
                        continue
                    limited = rate_limited(row["error"])
                    retry_at = (now + timedelta(minutes=15 if limited else 5)).isoformat()
                    db.execute("""UPDATE authors SET next_run=?,retry_count=1,
                        retry_full=COALESCE((SELECT mode='full' FROM runs WHERE runs.author_id=authors.id ORDER BY id DESC LIMIT 1),0)
                        WHERE id=?""", (retry_at, row["id"]))
                    if limited:
                        rate_until = retry_at
            if rate_until:
                self.store.save_settings({"rate_limit_until": rate_until})
            self.store.save_settings({"retry_upgrade_done": True})

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True, name="download-queue")
        self.thread.start()
        self.scheduler = threading.Thread(target=self._schedule, daemon=True, name="sync-scheduler")
        self.scheduler.start()

    def enqueue(self, author_id, full=False, manual=False):
        self.maintain_catalog()
        author = self.store.author(author_id)
        if not author:
            raise ValueError("推主不存在")
        if author["folder_removed"]:
            raise ValueError("本地文件夹已删除；请先恢复文件夹，再手动同步")
        platform = author['handle'].split(':', 1)[0] if ':' in author['handle'] else 'twitter'
        from .secrets import PlatformVault
        credentials = self.vault.read() if platform == 'twitter' else PlatformVault(self.store.root, platform).read()
        if not credentials.get({'twitter': 'auth_token', 'instagram': 'sessionid', 'weibo': 'SUB'}[platform]):
            raise ValueError("请先在设置中保存登录 Cookie")
        with self.lock:
            if author_id in self.pending:
                if not manual or self.current == author_id or author_id in self.manual_pending:
                    return False
                # Replace the automatic ticket with a priority manual one.
            ticket = uuid.uuid4().hex
            self.pending[author_id] = ticket
            if manual:
                self.manual_pending.add(author_id)
            self.store.update_author(author_id, status="queued", error="")
            self.queue.put((0 if manual else 1, next(self.sequence), author_id,
                            full or bool(author["retry_full"]), ticket, manual))
            self.queue_wakeup.set()
            return True

    def maintain_catalog(self):
        with self.lock:
            root = canonical_path(self.store.get_setting("download_dir"))
            if root.is_dir():
                for author in self.store.authors():
                    if author["id"] in self.pending and author["files"] and not self.store.author_folder(author).is_dir():
                        self.cancel(author["id"])
            self.store.prune_catalog(self.pending)

    def cancel(self, author_id):
        with self.lock:
            if self.current == author_id:
                self.cancelled = True
                if self.process and self.process.poll() is None:
                    self.process.terminate()
                else:
                    self.store.update_author(author_id, status="idle", retry_full=0, retry_count=0, next_run=(
                        datetime.now(timezone.utc) + timedelta(minutes=self.store.get_setting("interval_minutes", 60))).isoformat())
            else:
                self.pending.pop(author_id, None)
                self.manual_pending.discard(author_id)
                self.store.update_author(author_id, status="idle", retry_full=0, retry_count=0, next_run=(
                    datetime.now(timezone.utc) + timedelta(minutes=self.store.get_setting("interval_minutes", 60))).isoformat())

    def close(self):
        self.stop_event.set()
        self.queue_wakeup.set()
        with self.lock:
            self.cancelled = True
            if self.process and self.process.poll() is None:
                self.process.terminate()
        if hasattr(self, "thread"):
            self.thread.join(timeout=5)

    def _schedule(self):
        while not self.stop_event.wait(10):
            try:
                self.maintain_catalog()
                if not self.store.get_setting("automatic", True):
                    continue
                now = utcnow()
                for author in self.store.authors():
                    if author["enabled"] and (not author["next_run"] or author["next_run"] <= now):
                        try:
                            self.enqueue(author["id"])
                        except ValueError:
                            continue
            except Exception as exc:
                self.store.add_event(None, "error", f"自动同步暂不可用：{type(exc).__name__}")

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                item = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            priority, order, author_id, full, ticket, manual = item
            deferred = False
            try:
                with self.lock:
                    if self.pending.get(author_id) != ticket:
                        continue
                    until = self.store.get_setting("rate_limit_until", "")
                    author = self.store.author(author_id)
                    if not manual and author and ':' not in author['handle'] and until and until > utcnow():
                        # Keep automatic retries parked, but let a manual request pass.
                        self.queue.put(item)
                        deferred = True
                    else:
                        self.current, self.cancelled = author_id, False
                if deferred:
                    self.queue_wakeup.wait(0.5)
                    self.queue_wakeup.clear()
                    continue
                self._run(author_id, full)
            except Exception as exc:
                self.store.update_author(author_id, status="error", error=f"任务异常：{type(exc).__name__}",
                                         next_run=(datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat())
                self.store.add_event(None, "error", f"任务异常：{type(exc).__name__}")
                with self.store.connect() as db:
                    db.execute("UPDATE runs SET status='error',finished_at=? WHERE author_id=? AND status='running'",
                               (utcnow(), author_id))
            finally:
                with self.lock:
                    if not deferred and self.pending.get(author_id) == ticket:
                        self.pending.pop(author_id, None)
                        self.manual_pending.discard(author_id)
                    if self.current == author_id and not deferred:
                        self.current, self.process = None, None
                    if not deferred:
                        self.store.prune_catalog(self.pending)
                self.queue.task_done()

    def _run(self, author_id, full):
        author, settings = self.store.author(author_id), self.store.settings()
        if not author:
            return
        started = utcnow()
        mode = "full" if full or not author["last_success"] else "incremental"
        with self.store.connect() as db:
            run_id = db.execute("INSERT INTO runs(author_id,handle,mode,status,started_at) VALUES (?,?,?,'running',?)",
                                (author_id, author["handle"], mode, started)).lastrowid
        self.store.update_author(author_id, status="running", last_attempt=started, error="", retry_full=int(mode == "full"))
        self.store.add_event(run_id, "info", f"开始{'历史扫描' if mode == 'full' else '增量同步'} @{author['handle']}")
        platform = author['handle'].split(':', 1)[0] if ':' in author['handle'] else 'twitter'
        from .secrets import PlatformVault
        credentials = self.vault.read() if platform == 'twitter' else PlatformVault(self.store.root, platform).read()
        payload = {"handle": author["handle"], "settings": settings, "credentials": credentials,
                   "platform": platform,
                   "user_id": author.get("user_id", ""), "folder_name": author.get("folder_name", ""),
                   "archive_key": author.get("archive_key", ""),
                   "data_dir": str(self.store.root), "cutoff": incremental_cutoff(author, settings, full),
                   "proxy": settings["proxy"] or getproxies().get("https") or getproxies().get("http")}
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        # pythonw has no standard streams in its child unless redirected; use console interpreter hidden.
        interpreter = (Path(sys.executable) if getattr(sys, "frozen", False) else
                       Path(sys.executable).with_name("python.exe") if os.name == "nt" else Path(sys.executable))
        command = [str(interpreter), "--worker"] if getattr(sys, "frozen", False) else [str(interpreter), "-m", "app.worker"]
        downloaded = skipped = 0
        errors = []
        seen = 0
        done = False
        with self.lock:
            if self.cancelled or self.stop_event.is_set():
                self._finish_cancelled(author_id, run_id, settings)
                return
            self.process = subprocess.Popen(
                command, cwd=Path(__file__).resolve().parent.parent,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            proc = self.process
        try:
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    # Never store an unexpected traceback containing configuration or credentials.
                    continue
                kind = event.get("event")
                if kind == "profile":
                    with self.lock:
                        if self.cancelled or self.stop_event.is_set():
                            continue
                        bound = self.store.bind_profile(author_id, event) if platform == 'twitter' else self.store.bind_external_profile(author_id, event)
                        missing = self.store.reconcile_missing(bound)
                        if missing:
                            self.store.add_event(run_id, "info", f"检测到已删除媒体，已保留忽略规则")
                        binding = {k: bound[k] for k in ("handle", "user_id", "folder_name", "archive_key")}
                        proc.stdin.write(json.dumps(binding, ensure_ascii=False) + "\n")
                        proc.stdin.flush()
                        self.store.add_event(run_id, "info", "保存目录：" + bound["folder_name"])
                elif kind == "excluded":
                    skipped += 1
                    with self.store.connect() as db:
                        db.execute("UPDATE runs SET skipped=? WHERE id=?", (skipped, run_id))
                elif kind == "avatar":
                    self.store.add_event(run_id, "info", "推主头像已保存到 " + event["path"])
                elif kind in {"saved", "skipped"}:
                    downloaded += kind == "saved"
                    skipped += kind == "skipped"
                    self._record_media(author_id, event)
                    with self.store.connect() as db:
                        db.execute("UPDATE runs SET downloaded=?,skipped=? WHERE id=?", (downloaded, skipped, run_id))
                    if kind == "saved":
                        self.store.add_event(run_id, "success", Path(event["path"]).name)
                elif kind == "log":
                    message = event.get("message", "")
                    for value in credentials.values():
                        if value:
                            message = message.replace(value, "[hidden]")
                    self.store.add_event(run_id, event["level"], message)
                    if event["level"] in {"error", "critical", "warning"}:
                        errors.append(message)
                elif kind == "done":
                    done = True
                    seen = event.get("seen", 0)
            return_code = proc.wait()
        finally:
            proc.stdin.close()
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
            proc.stdout.close()
        cancelled = self.cancelled or self.stop_event.is_set()
        ok = not cancelled and return_code == 0 and done and not errors
        # Empty responses cannot certify a complete initial scan or move a watermark forward.
        if ok and not seen:
            ok = False
            errors.append("本轮未返回媒体，无法确认扫描完整性；请检查登录状态、账号权限或稍后重试")
        status = "cancelled" if cancelled else "success" if ok else "error"
        error = "" if ok or cancelled else (errors[-1] if errors else "下载未完成，请检查网络或登录 Cookie")
        interval = self.store.get_setting("interval_minutes", 60)
        retryable = not ok and not cancelled and transient_failure(" ".join(errors) or error)
        count = author["retry_count"] + 1 if retryable else 0
        delay = min(120, 15 * 2 ** min(count - 1, 3)) if retryable and rate_limited(" ".join(errors)) else min(60, 5 * 2 ** min(count - 1, 4)) if retryable else interval if ok or cancelled else max(15, interval)
        next_run = (datetime.now(timezone.utc) + timedelta(minutes=delay)).isoformat()
        if platform == 'twitter' and retryable and rate_limited(" ".join(errors)):
            self.store.save_settings({"rate_limit_until": next_run})
        fields = {"status": "idle" if ok or cancelled else "error", "error": error,
                  "retry_count": count, "retry_full": int(retryable and mode == "full"), "next_run": next_run}
        if retryable:
            self.store.add_event(run_id, "info", f"等待 {delay} 分钟后自动重试；从扫描范围重新检查，已保存及忽略的文件会跳过")
        if ok:
            fields["last_success"] = started  # start, not end: posts published during the scan stay eligible
        self.store.update_author(author_id, **fields)
        with self.store.connect() as db:
            db.execute("UPDATE runs SET status=?,finished_at=?,error=? WHERE id=?", (status, utcnow(), error, run_id))
        self.store.add_event(run_id, "success" if ok else "info" if cancelled else "error",
                             f"{'本轮扫描完成' if ok else '任务已停止' if cancelled else '本轮未完成'}：新增 {downloaded}，跳过 {skipped}。{error}")

    def _finish_cancelled(self, author_id, run_id, settings):
        self.store.update_author(author_id, status="idle", retry_full=0, retry_count=0, next_run=(
            datetime.now(timezone.utc) + timedelta(minutes=settings["interval_minutes"])).isoformat())
        with self.store.connect() as db:
            db.execute("UPDATE runs SET status='cancelled',finished_at=? WHERE id=?", (utcnow(), run_id))

    def _record_media(self, author_id, event):
        with self.store.connect() as db:
            db.execute("""INSERT INTO media VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(path) DO UPDATE SET size=excluded.size,author_id=excluded.author_id""",
                       (str(canonical_path(event["path"])), author_id, event["tweet_id"], event["num"], event["published_at"],
                        event["size"], event["kind"], utcnow(),))
