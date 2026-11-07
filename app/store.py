"""Durable application state. Media files always stay outside the database."""
import json
import re
import sqlite3
import shutil
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def canonical_path(value):
    value = str(value)
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value).resolve()


def normalize_handle(value):
    value = value.strip()
    if "://" in value:
        url = urlparse(value)
        if url.hostname not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
            raise ValueError("请输入 X / Twitter 的账号或主页链接")
        value = url.path.strip("/").split("/")[0]
    value = value.lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", value) or value.lower() in {
        "home", "search", "i", "explore", "settings", "notifications", "messages"
    }:
        raise ValueError("账号应为 1–15 位英文字母、数字或下划线")
    return value


def folder_label(display_name, handle):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', display_name).strip(' .') or handle
    # Leave ample space for the media filenames, including UTF-16 surrogate pairs.
    name = name.encode('utf-16-le')[:160].decode('utf-16-le', errors='ignore').rstrip(' .')
    return f"{name}@{handle}"


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "library.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS authors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, handle TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    enabled INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'idle',
                    last_attempt TEXT, last_success TEXT, next_run TEXT,
                    error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY, author_id INTEGER NOT NULL, handle TEXT NOT NULL,
                    mode TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
                    finished_at TEXT, downloaded INTEGER NOT NULL DEFAULT 0,
                    skipped INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS media (
                    path TEXT PRIMARY KEY, author_id INTEGER NOT NULL, tweet_id TEXT NOT NULL,
                    num INTEGER NOT NULL, published_at TEXT NOT NULL, size INTEGER NOT NULL,
                    kind TEXT NOT NULL, downloaded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS media_author ON media(author_id);
                CREATE TABLE IF NOT EXISTS exclusions (
                    tweet_id TEXT NOT NULL, num INTEGER NOT NULL, handle TEXT NOT NULL,
                    path TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(tweet_id,num)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, run_id INTEGER, level TEXT NOT NULL,
                    message TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id TEXT PRIMARY KEY, folder_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    archive_key TEXT NOT NULL, display_name TEXT NOT NULL, handle TEXT NOT NULL
                );
            """)
            columns = {r[1] for r in db.execute("PRAGMA table_info(authors)")}
            for column in ("user_id", "display_name", "folder_name", "archive_key"):
                if column not in columns:
                    db.execute(f"ALTER TABLE authors ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            if "folder_removed" not in columns:
                db.execute("ALTER TABLE authors ADD COLUMN folder_removed INTEGER NOT NULL DEFAULT 0")
            if "retry_full" not in columns:
                db.execute("ALTER TABLE authors ADD COLUMN retry_full INTEGER NOT NULL DEFAULT 0")
            if "retry_count" not in columns:
                db.execute("ALTER TABLE authors ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
            # Windows extended paths and regular paths must refer to the same library row.
            keep = {}
            for row in db.execute("SELECT rowid,path FROM media ORDER BY rowid").fetchall():
                normalized = str(canonical_path(row["path"]))
                if normalized in keep:
                    db.execute("DELETE FROM media WHERE rowid=?", (row["rowid"],))
                else:
                    keep[normalized] = row["rowid"]
            for normalized, row_id in keep.items():
                db.execute("UPDATE media SET path=? WHERE rowid=?", (normalized, row_id))
            db.execute("""UPDATE authors SET next_run=?, retry_full=COALESCE(
                (SELECT mode='full' FROM runs WHERE runs.author_id=authors.id AND status='running' ORDER BY id DESC LIMIT 1), retry_full)
                WHERE status='running'""", (utcnow(),))
            db.execute("UPDATE runs SET status='interrupted',finished_at=? WHERE status='running'", (utcnow(),))
            db.execute("UPDATE authors SET status='idle' WHERE status IN ('running','queued')")
        if not self.get_setting("initialized", False):
            self.save_settings({
                "initialized": True, "download_dir": str(self.root.parent / "downloads"),
                "interval_minutes": 60, "overlap_days": 3, "automatic": True,
                "proxy": "", "include_replies": True, "include_retweets": False,
                "include_quotes": False,
            })
            # Fresh public installations start empty; sample authors belong only to isolated tests.
            if os.environ.get('MEDIA_ARCHIVE_TEST_SEED') == '1':
                self.add_author("Ku1Tetsuya")
        if self.get_setting("download_concurrency") is None:
            self.save_settings({"download_concurrency": 4})

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def get_setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def settings(self):
        with self.connect() as db:
            return {r["key"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM settings")}

    def save_settings(self, values):
        with self.connect() as db:
            db.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)", [
                (k, json.dumps(v, ensure_ascii=False)) for k, v in values.items()
            ])

    def add_author(self, handle):
        if '://' in handle and (urlparse(handle).hostname or '').lower() not in {'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'}:
            from .platforms import parse_profile_url
            platform, account = parse_profile_url(handle)
            handle = f'{platform}:{account}'
        else:
            handle = normalize_handle(handle)
        try:
            with self.connect() as db:
                cursor = db.execute("INSERT INTO authors(handle,created_at) VALUES (?,?)", (handle, utcnow()))
                return cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("这个推主已经在列表中") from exc

    def author(self, author_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM authors WHERE id=?", (author_id,)).fetchone()
        return dict(row) if row else None

    def avatar_path(self, author):
        identity = author.get("user_id") or author["handle"].lower()
        return self.root / "avatars" / (identity.replace(':', '_') + ".img")

    def bind_external_profile(self, author_id, profile):
        """Bind a platform-qualified identity and immutable folder for a new external account."""
        author = self.author(author_id)
        if not author or ':' not in author['handle']:
            raise ValueError('平台账号无效')
        platform, account = author['handle'].split(':', 1)
        if platform not in {'instagram', 'weibo'} or not str(profile['user_id']).isdigit():
            raise ValueError('平台身份资料无效')
        identity = f'{platform}:{profile["user_id"]}'
        if author['user_id'] and author['user_id'] != identity:
            raise ValueError('账号身份发生变化，已暂停以保护原有收藏')
        display = str(profile.get('display_name') or account)
        # Stable namespaced identity prevents cross-platform collisions.
        with self.connect() as db:
            if db.execute('SELECT 1 FROM authors WHERE user_id=? AND id<>?', (identity, author_id)).fetchone():
                raise ValueError('这个平台账号已在列表中')
            existing = db.execute('SELECT * FROM profiles WHERE user_id=?', (identity,)).fetchone()
            if existing:
                folder, archive_key = existing['folder_name'], existing['archive_key']
            else:
                folder = folder_label(display, account) + '_' + platform
                if db.execute('SELECT 1 FROM profiles WHERE folder_name=? COLLATE NOCASE', (folder,)).fetchone():
                    folder += '_' + str(profile['user_id'])
                archive_key = f'{platform}_{profile["user_id"]}'
                db.execute('INSERT INTO profiles VALUES (?,?,?,?,?)', (identity, folder, archive_key, display, author['handle']))
            db.execute('UPDATE authors SET user_id=?,display_name=?,folder_name=?,archive_key=? WHERE id=?',
                       (identity, display, folder, archive_key, author_id))
        return self.author(author_id)

    def bind_profile(self, author_id, profile):
        """Reserve an immutable destination before moving. Safe to retry after a crash."""
        author = self.author(author_id)
        user_id = str(profile["user_id"])
        if not user_id.isdigit() or not author:
            raise ValueError("推主身份资料无效")
        handle = normalize_handle(profile["handle"])
        display_name = str(profile["display_name"])
        if author["user_id"] and author["user_id"] != user_id:
            raise ValueError("账号身份发生变化，已暂停以保护原有收藏")
        old_name = author["folder_name"] or author["handle"]
        with self.connect() as db:
            if db.execute("SELECT 1 FROM authors WHERE handle=? COLLATE NOCASE AND id<>?", (handle, author_id)).fetchone():
                raise ValueError("推主的新账号已在列表中，请先处理重复账号")
            if db.execute("SELECT 1 FROM authors WHERE user_id=? AND id<>?", (user_id, author_id)).fetchone():
                raise ValueError("这个推主已在列表中，请移除重复添加的账号")
            existing = db.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
            if existing:
                folder, archive_key = existing["folder_name"], existing["archive_key"]
            else:
                folder = folder_label(display_name, handle)
                if db.execute("SELECT 1 FROM profiles WHERE folder_name=?", (folder,)).fetchone():
                    folder += "_" + user_id
                archive_key = author["archive_key"] or author["handle"].lower()
                db.execute("INSERT INTO profiles VALUES (?,?,?,?,?)", (user_id, folder, archive_key, display_name, handle))
            # This reservation is the migration journal. Keep the source name until the final commit.
            db.execute("UPDATE authors SET user_id=?,folder_name=?,archive_key=? WHERE id=?",
                       (user_id, old_name, archive_key, author_id))
        root = canonical_path(self.get_setting("download_dir"))
        source, target = canonical_path(root / old_name), canonical_path(root / folder)
        if source.parent != root or target.parent != root:
            raise ValueError("推主文件夹必须位于媒体保存目录内")
        if source != target:
            if source.exists() and target.exists():
                raise ValueError("新旧推主目录同时存在，已停止迁移，请先检查目录内容")
            if source.exists():
                if not source.is_dir():
                    raise ValueError("推主保存位置不是文件夹")
                source.rename(target)
            elif not target.exists():
                with self.connect() as db:
                    known = db.execute("SELECT path FROM media WHERE author_id=?", (author_id,)).fetchall()
                if any(canonical_path(r[0]).parent == source for r in known):
                    raise ValueError("原媒体文件夹不可用，已暂停迁移；不会重新下载已删除内容")
                target.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            # Rows for intentional deletions move too; never recreate their files.
            for table in ("media", "exclusions"):
                rows = db.execute(f"SELECT rowid,path FROM {table}").fetchall()
                for row in rows:
                    path = canonical_path(row["path"])
                    if path.parent == source:
                        db.execute(f"UPDATE {table} SET path=? WHERE rowid=?", (str(target / path.name), row["rowid"]))
            for row in db.execute("SELECT rowid,path FROM media").fetchall():
                if canonical_path(row["path"]).parent == target:
                    db.execute("UPDATE media SET author_id=? WHERE rowid=?", (author_id, row["rowid"]))
            db.execute("UPDATE exclusions SET handle=? WHERE handle=? COLLATE NOCASE", (handle, author["handle"]))
            db.execute("UPDATE authors SET handle=?,display_name=?,folder_name=? WHERE id=?", (handle, display_name, folder, author_id))
            db.execute("UPDATE profiles SET display_name=?,handle=? WHERE user_id=?", (display_name, handle, user_id))
        old_avatar = self.root / "avatars" / (author["handle"].lower() + ".img")
        new_avatar = self.root / "avatars" / (user_id + ".img")
        if old_avatar.is_file() and not new_avatar.exists():
            shutil.copyfile(old_avatar, new_avatar)
        return self.author(author_id)

    def authors(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("""
                SELECT a.*,COUNT(m.path) AS files,COALESCE(SUM(m.size),0) AS bytes
                FROM authors a LEFT JOIN media m ON a.id=m.author_id
                  AND NOT EXISTS (SELECT 1 FROM exclusions e WHERE e.tweet_id=m.tweet_id AND e.num=m.num)
                GROUP BY a.id ORDER BY a.created_at,a.id
            """)]

    def update_author(self, author_id, **fields):
        allowed = {"enabled", "status", "last_attempt", "last_success", "next_run", "error", "folder_removed", "retry_full", "retry_count"}
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Invalid author fields")
        with self.connect() as db:
            db.execute("UPDATE authors SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                       (*fields.values(), author_id))

    def add_event(self, run_id, level, message):
        with self.connect() as db:
            db.execute("INSERT INTO events(run_id,level,message,created_at) VALUES (?,?,?,?)",
                       (run_id, level, message[:1500], utcnow()))
            db.execute("DELETE FROM events WHERE id < (SELECT MAX(id)-3000 FROM events)")

    def snapshot(self):
        with self.connect() as db:
            runs = [dict(r) for r in db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 60")]
            events = [dict(r) for r in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 100")]
            recent = [dict(r) for r in db.execute("""SELECT m.rowid AS media_id,m.*,a.handle,a.display_name FROM media m
                JOIN authors a ON a.id=m.author_id WHERE NOT EXISTS
                (SELECT 1 FROM exclusions e WHERE e.tweet_id=m.tweet_id AND e.num=m.num)
                ORDER BY downloaded_at DESC,m.rowid DESC LIMIT 12""")]
            excluded = db.execute("SELECT COUNT(*) FROM exclusions").fetchone()[0]
        authors = self.authors()
        return {"authors": authors, "runs": runs, "events": events, "recent": recent,
                "totals": {"authors": len(authors), "files": sum(a["files"] for a in authors),
                           "bytes": sum(a["bytes"] for a in authors), "excluded": excluded}}

    def media_page(self, author_id=None, excluded=False, offset=0, kind="all", visible_author_ids=None, all_items=False, platform="all"):
        with self.connect() as db:
            if excluded:
                where, args = "1=1", []
                if platform in {'instagram', 'weibo'}:
                    where += " AND handle LIKE ? ESCAPE '\\'"
                    args.append(platform + ':%')
                elif platform == 'twitter':
                    where += " AND handle NOT LIKE 'instagram:%' AND handle NOT LIKE 'weibo:%'"
                if visible_author_ids is not None:
                    placeholders = ','.join('?' for _ in visible_author_ids) or 'NULL'
                    where += f" AND handle COLLATE NOCASE IN (SELECT handle FROM authors WHERE id IN ({placeholders}))"
                    args.extend(visible_author_ids)
                if author_id:
                    author = self.author(author_id)
                    where += " AND handle=? COLLATE NOCASE"
                    args.append(author["handle"] if author else "")
                total = db.execute(f"SELECT COUNT(*) FROM exclusions WHERE {where}", args).fetchone()[0]
                rows = db.execute(f"SELECT * FROM exclusions WHERE {where} ORDER BY created_at DESC,tweet_id DESC,num" + ("" if all_items else " LIMIT 100 OFFSET ?"), args if all_items else (*args, offset))
            else:
                where = "NOT EXISTS (SELECT 1 FROM exclusions e WHERE e.tweet_id=m.tweet_id AND e.num=m.num)"
                args = []
                if platform in {'instagram', 'weibo'}:
                    where += " AND m.author_id IN (SELECT id FROM authors WHERE handle LIKE ?)"
                    args.append(platform + ':%')
                elif platform == 'twitter':
                    where += " AND m.author_id IN (SELECT id FROM authors WHERE handle NOT LIKE 'instagram:%' AND handle NOT LIKE 'weibo:%')"
                if visible_author_ids is not None:
                    placeholders = ','.join('?' for _ in visible_author_ids) or 'NULL'
                    where += f" AND m.author_id IN ({placeholders})"
                    args.extend(visible_author_ids)
                if author_id:
                    where += " AND m.author_id=?"
                    args.append(author_id)
                if kind in {"image", "video"}:
                    where += " AND m.kind=?"
                    args.append(kind)
                total = db.execute(f"SELECT COUNT(*) FROM media m WHERE {where}", args).fetchone()[0]
                rows = db.execute(f"SELECT m.rowid AS media_id,m.*,a.handle,a.display_name FROM media m JOIN authors a ON a.id=m.author_id WHERE {where} ORDER BY published_at DESC,tweet_id DESC,num" + ("" if all_items else " LIMIT 100 OFFSET ?"), args if all_items else (*args, offset))
            return {"items": [dict(r) for r in rows], "total": total, "offset": offset, "limit": 100}

    def author_folder(self, author):
        return canonical_path(self.get_setting("download_dir")) / (author.get("folder_name") or author["handle"])

    def delete_author_files(self, author):
        """Delete only this author's current destination folder; caller holds engine lock."""
        root = canonical_path(self.get_setting('download_dir'))
        if not root.is_dir():
            raise ValueError('保存目录不可用，无法确认文件是否已删除；请先检查磁盘')
        label = author.get('folder_name') or author['handle']
        # A new external account cannot have created a folder until its profile is bound.
        if not author.get('folder_name') and ':' in label and not author.get('user_id'):
            return
        if not label or label in {'.', '..'} or Path(label).name != label or '/' in label or '\\' in label or ':' in label:
            raise ValueError('推主文件夹路径无效，已停止删除')
        folder = root / label
        if folder.is_symlink() or getattr(os.path, 'isjunction', lambda _: False)(folder):
            raise ValueError('推主文件夹是链接，已停止删除，请在资源管理器中检查')
        resolved = canonical_path(folder)
        if resolved.parent != root:
            raise ValueError('推主文件夹不在保存目录中，已停止删除')
        if not folder.exists():
            return
        if not folder.is_dir():
            raise ValueError('推主保存位置不是文件夹，已停止删除')
        shutil.rmtree(folder)

    def gallery_author_ids(self):
        return [a["id"] for a in self.authors() if self.author_folder(a).is_dir() and not a["folder_removed"]]

    def clear_author_catalog(self, author_id, remove=False):
        """Forget visible library/history rows, never the user's files or suppression ledger."""
        with self.connect() as db:
            db.execute("DELETE FROM events WHERE run_id IN (SELECT id FROM runs WHERE author_id=?)", (author_id,))
            db.execute("DELETE FROM runs WHERE author_id=?", (author_id,))
            db.execute("DELETE FROM media WHERE author_id=?", (author_id,))
            if remove:
                db.execute("DELETE FROM authors WHERE id=?", (author_id,))
            else:
                db.execute("""UPDATE authors SET enabled=0,status='idle',folder_removed=1,
                    last_success=NULL,next_run=NULL,error='本地文件夹已删除，媒体记录已清空；自动同步已暂停' WHERE id=?""", (author_id,))

    def prune_catalog(self, busy=()):
        # Old releases left orphan media/history after removing an author.
        with self.connect() as db:
            db.execute("DELETE FROM events WHERE run_id IN (SELECT id FROM runs WHERE author_id NOT IN (SELECT id FROM authors))")
            db.execute("DELETE FROM runs WHERE author_id NOT IN (SELECT id FROM authors)")
            db.execute("DELETE FROM media WHERE author_id NOT IN (SELECT id FROM authors)")
        root = canonical_path(self.get_setting("download_dir"))
        if not root.is_dir():
            return  # An unavailable drive/root is not evidence of an author-folder deletion.
        for author in self.authors():
            if author["id"] in busy:
                continue
            folder = self.author_folder(author)
            if folder.is_dir():
                if author["folder_removed"]:
                    self.update_author(author["id"], folder_removed=0, error="文件夹已恢复，可手动同步或开启自动同步")
                continue
            if author["folder_removed"]:
                continue
            with self.connect() as db:
                paths = db.execute("SELECT path FROM media WHERE author_id=?", (author["id"],)).fetchall()
            # Do not treat changing the download destination or a never-synced author as deletion.
            if any(canonical_path(row["path"]).parent == folder for row in paths):
                self.clear_author_catalog(author["id"])

    def exclude(self, tweet_id, num, handle, path, reason):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO exclusions VALUES (?,?,?,?,?,?)",
                       (str(tweet_id), num, handle, path, reason, utcnow()))

    def reconcile_missing(self, author):
        """Only inspect the current destination; an unavailable folder is not a deletion."""
        folder = Path(self.get_setting("download_dir")) / (author.get("folder_name") or author["handle"])
        with self.connect() as db:
            rows = db.execute("SELECT * FROM media WHERE author_id=?", (author["id"],)).fetchall()
        rows = [r for r in rows if canonical_path(r["path"]).parent == canonical_path(folder)]
        if rows and not folder.is_dir():
            raise ValueError("媒体文件夹不可用，请检查磁盘或路径；未将文件标记为删除")
        count = 0
        for row in rows:
            path = Path(row["path"])
            try:
                path.stat()
            except FileNotFoundError:
                self.exclude(row["tweet_id"], row["num"], author["handle"], row["path"], "external")
                count += 1
        return count
