"""Download pipeline tests use a local HTTP server and real gallery-dl jobs."""
import collections
import json
import os
import re
import threading
import shutil
import subprocess
import functools
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from gallery_dl import config
from gallery_dl.extractor.common import Extractor, Message
from gallery_dl.extractor.twitter import TwitterExtractor

from app import worker
from app.engine import Engine, incremental_cutoff
from app.secrets import Vault
from app.server import create_app
from app.store import Store, normalize_handle


@pytest.fixture
def payload(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return {"handle": "SampleUser", "credentials": {"auth_token": "test-only-token"},
            "data_dir": str(data), "cutoff": None, "proxy": None,
            "settings": {"download_dir": str(tmp_path / "media"), "include_replies": True,
                         "include_retweets": False, "include_quotes": False}}


@pytest.fixture
def local_media():
    hits = collections.Counter()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits[self.path] += 1
            content = b"original-content:" + self.path.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", hits
    server.shutdown()


class FixtureExtractor(Extractor):
    category = "twitter"
    subcategory = "timeline"
    archive_fmt = "{tweet_id}_{num}"
    root = "https://x.com"
    filename_fmt = "{tweet_id}_{num}.{extension}"
    directory_fmt = ("{category}",)
    url = "https://x.com/SampleUser/timeline"

    def __init__(self, base):
        super().__init__(re.match(r".*", self.url))
        self.base = base

    def items(self):
        for tweet_id, posted, count in [("12345", datetime(2020, 2, 3, 4, 5, 6), 4),
                                        ("12346", datetime(2020, 2, 4, 4, 5, 6), 1)]:
            meta = {"author": {"name": "SampleUser"}, "user": {"name": "SampleUser"},
                    "date": posted, "tweet_id": tweet_id, "count": count}
            yield Message.Directory, "", meta
            for num in range(1, count + 1):
                extension = "mp4" if num == 4 else "jpg"
                yield Message.Url, f"{self.base}/{tweet_id}/{num}.{extension}", dict(meta, num=num, extension=extension)


def setup_job(payload, base, monkeypatch):
    monkeypatch.setattr(worker, "PAYLOAD", payload)
    monkeypatch.setattr(worker, "SUMMARY", {"downloaded": 0, "skipped": 0, "seen": 0})
    config.clear()
    for key, value in worker.build_config(payload).items():
        config.set((), key, value)
    config.set(("extractor", "twitter"), "sleep-request", 0)
    config.set(("extractor", "twitter"), "sleep", 0)
    return worker.ArchiveJob(FixtureExtractor(base))


def test_real_download_multi_media_dates_and_idempotence(payload, local_media, monkeypatch, capsys):
    base, hits = local_media
    assert setup_job(payload, base, monkeypatch).run() == 0
    files = sorted(Path(payload["settings"]["download_dir"]).rglob("*.*"))
    assert len(files) == 5  # All 4 assets on the first tweet, plus the next tweet.
    assert files[0].name == "2020-02-03_040506Z_12345_01.jpg"
    assert files[3].name == "2020-02-03_040506Z_12345_04.mp4"
    assert files[0].read_bytes() == b"original-content:/12345/1.jpg"
    assert files[0].stat().st_mtime == datetime(2020, 2, 3, 4, 5, 6, tzinfo=timezone.utc).timestamp()
    before = sum(hits.values())
    assert setup_job(payload, base, monkeypatch).run() == 0
    assert sum(hits.values()) == before  # Archive prevents second network download.
    assert worker.SUMMARY["skipped"] == 5
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{')]
    assert sum(e["event"] == "saved" for e in events) == 5
    assert sum(e["event"] == "skipped" for e in events) == 5
    files[0].unlink()  # A full history check can restore a manually deleted file.
    assert setup_job(payload, base, monkeypatch).run() == 0
    assert sum(hits.values()) == before + 1
    assert worker.SUMMARY["downloaded"] == 1


def test_incremental_keeps_eligible_tweet_whole(payload, local_media, monkeypatch):
    payload["cutoff"] = "2020-02-03T00:00:00+00:00"
    base, _ = local_media
    assert setup_job(payload, base, monkeypatch).run() == 0
    assert worker.SUMMARY["downloaded"] == 5


def test_incremental_skips_old_tweet(payload, local_media, monkeypatch):
    payload["cutoff"] = "2020-02-04T00:00:00+00:00"
    base, _ = local_media
    assert setup_job(payload, base, monkeypatch).run() == 0
    assert worker.SUMMARY["downloaded"] == 1


def test_destination_has_independent_archive(payload):
    first = worker.build_config(payload)["extractor"]["twitter"]["archive"]
    payload["settings"]["download_dir"] += "-different"
    assert first != worker.build_config(payload)["extractor"]["twitter"]["archive"]


def test_twitter_extractor_selects_original_and_highest_video():
    from gallery_dl import extractor as registry
    extractor = registry.find("https://x.com/SampleUser/status/12345")
    extractor.videos_ytdl = False
    extractor.videos_files = True
    extractor.videos_previews = False
    extractor.unavailable = False
    extractor.cards = False
    extractor.articles = False
    extractor.twitpic = False
    extractor._article_media = False
    extractor._article_cover = False
    extractor._init_sizes()
    tweet = {"id_str": "12345", "extended_entities": {"media": [
        {"type":"photo", "media_url_https":"https://pbs.twimg.com/media/sample.jpg", "original_info":{"width":4000,"height":3000}},
        {"type":"video", "original_info":{"width":1920,"height":1080}, "video_info":{"variants":[
            {"bitrate":256000,"url":"https://video.twimg.com/low.mp4"},
            {"bitrate":2176000,"url":"https://video.twimg.com/high.mp4"},
            {"url":"https://video.twimg.com/stream.m3u8"}
        ]}}
    ]}}
    files = extractor._extract_files(tweet, {})
    assert "name=orig" in files[0]["url"]
    assert files[1]["url"] == "https://video.twimg.com/high.mp4"


def test_watermark_overlap_and_first_run():
    settings = {"overlap_days": 3}
    assert incremental_cutoff({}, settings) is None
    author = {"last_success":"2026-11-07T10:00:00+00:00"}
    assert incremental_cutoff(author, settings) == "2026-11-04T10:00:00+00:00"
    assert incremental_cutoff(author, settings, full=True) is None


def test_handle_validation():
    assert normalize_handle("https://x.com/Ku1Tetsuya/media") == "Ku1Tetsuya"
    assert normalize_handle(" @sample_user ") == "sample_user"
    for value in ["https://evil.example/a", "../data", "home", "a;rm -rf", "中文"]:
        with pytest.raises(ValueError):
            normalize_handle(value)


def test_api_persistence_security_and_scope_reset(tmp_path):
    app = create_app(tmp_path / "app-data", start_engine=False)
    with TestClient(app) as client:
        html = client.get("/").text
        token = re.search('name="app-token" content="([^"]+)"', html)[1]
        headers = {"X-App-Token":token}
        assert client.get("/api/state").status_code == 403
        assert client.get("/api/state", headers={**headers,"Origin":"https://evil.example"}).status_code == 403
        assert client.get("/api/state", headers={**headers,"Host":"evil.example"}).status_code == 400
        assert client.post("/api/authors",headers=headers,json={"handle":"@SecondUser"}).status_code == 200
        assert client.post("/api/authors",headers=headers,json={"handle":"seconduser"}).status_code == 400
        settings = client.get("/api/state",headers=headers).json()["settings"]
        app.state.store.update_author(1, last_success="2026-11-07T10:00:00+00:00")
        settings["include_quotes"] = True
        assert client.put("/api/settings",headers=headers,json=settings).status_code == 200
        assert app.state.store.author(1)["last_success"] is None
        settings["download_dir"] = "relative/path"
        assert client.put("/api/settings",headers=headers,json=settings).status_code == 400
        assert client.post("/api/authors/1/sync",headers=headers,json={}).status_code == 400
    reopened = Store(tmp_path / "app-data")
    assert len(reopened.authors()) == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_credentials_encrypted_and_never_returned(tmp_path):
    app = create_app(tmp_path / "data", start_engine=False)
    with TestClient(app) as client:
        token = re.search('name="app-token" content="([^"]+)"',client.get("/").text)[1]
        headers = {"X-App-Token":token}
        fake = "secret-test-token-that-must-not-leak"
        assert client.put("/api/credentials",headers=headers,json={"auth_token":fake}).status_code == 200
        assert fake.encode() not in app.state.vault.path.read_bytes()
        response = client.get("/api/state",headers=headers)
        assert response.json()["credentials_saved"] is True
        assert fake not in response.text
        assert app.state.vault.read()["auth_token"] == fake


def test_media_record_reindexes_existing_file(tmp_path):
    store = Store(tmp_path / "data")
    engine = Engine(store, Vault(store.root))
    media = {"path":"G:/downloads/example.jpg","tweet_id":"1","num":1,
             "published_at":"2020-01-01T00:00:00+00:00","size":42,"kind":"image"}
    engine._record_media(1, media)
    engine._record_media(1, media)
    assert store.snapshot()["totals"]["files"] == 1


def test_cancel_and_requeue_has_distinct_tickets(tmp_path):
    class TestVault:
        def read(self):
            return {"auth_token":"fake-token"}
    store = Store(tmp_path / "data")
    engine = Engine(store, TestVault())
    engine.enqueue(1)
    first = engine.pending[1]
    engine.cancel(1)
    engine.enqueue(1)
    assert first != engine.pending[1]
    assert store.author(1)["status"] == "queued"


@pytest.mark.parametrize("return_code,completed,level", [(0,True,None),(1,True,"error"),(0,False,None),(0,True,"warning")])
def test_engine_advances_watermark_only_on_confirmed_success(tmp_path, monkeypatch, return_code, completed, level):
    import io
    import app.engine as engine_module

    class FakeVault:
        def read(self):
            return {"auth_token":"sensitive-test-token"}

    class FakeProcess:
        def __init__(self, args, **kwargs):
            assert "sensitive-test-token" not in str(args)
            self.stdin = io.StringIO()
            events = []
            if level:
                events.append({"event":"log", "level":level, "message":"sensitive-test-token request failed"})
            if completed:
                events.append({"event":"done", "status":return_code, "seen":4})
            self.stdout = io.StringIO("\n".join(json.dumps(e) for e in events))

        def wait(self, **kwargs):
            return return_code

        def poll(self):
            return return_code

    monkeypatch.setattr(engine_module.subprocess, "Popen", FakeProcess)
    store = Store(tmp_path / "data")
    previous = "2026-01-01T00:00:00+00:00"
    store.update_author(1, last_success=previous)
    engine = Engine(store, FakeVault())
    engine._run(1, False)
    success = return_code == 0 and completed and level is None
    assert (store.author(1)["last_success"] != previous) is success
    assert store.snapshot()["runs"][0]["status"] == ("success" if success else "error")
    assert "sensitive-test-token" not in json.dumps(store.snapshot())


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is needed for HLS stream assembly")
def test_hls_video_is_saved_as_playable_video_not_manifest(payload, tmp_path, monkeypatch):
    source = tmp_path / "hls-source"
    source.mkdir()
    subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=gray:s=64x64:r=5", "-t", "1", "-an", "-c:v", "libx264",
                    "-f", "hls", "-hls_time", "1", "-hls_segment_filename", str(source / "segment%02d.ts"),
                    str(source / "playlist.m3u8")], check=True, capture_output=True)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(source)))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    class HlsExtractor(FixtureExtractor):
        def items(self):
            meta = {"author":{"name":"SampleUser"},"date":datetime(2020,2,3,4,5,6),"tweet_id":"789", "count":1}
            yield Message.Directory, "", meta
            yield Message.Url, f"{self.base}/playlist.m3u8", dict(meta, num=1, extension="m3u8")

    try:
        base = f"http://127.0.0.1:{server.server_port}"
        setup_job(payload, base, monkeypatch)
        assert worker.ArchiveJob(HlsExtractor(base)).run() == 0
        video = Path(payload["settings"]["download_dir"]) / "SampleUser" / "2020-02-03_040506Z_789_01.mp4"
        assert video.is_file()
        assert b"#EXTM3U" not in video.read_bytes()[:100]
        if shutil.which("ffprobe"):
            result = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries",
                                     "stream=codec_name,width,height", "-of", "json", str(video)],
                                    check=True,capture_output=True,text=True)
            stream = json.loads(result.stdout)["streams"][0]
            assert stream["codec_name"] == "h264" and stream["width"] == 64
    finally:
        server.shutdown()


def test_downloads_really_overlap_and_duplicate_messages_are_coalesced(payload, monkeypatch):
    import time
    lock = threading.Lock()
    activity = {"active": 0, "peak": 0, "hits": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with lock:
                activity["active"] += 1
                activity["hits"] += 1
                activity["peak"] = max(activity["peak"], activity["active"])
            time.sleep(.15)
            self.send_response(200)
            self.send_header("Content-Length", "4")
            self.end_headers()
            self.wfile.write(b"data")
            with lock:
                activity["active"] -= 1
        def log_message(self, *args):
            pass

    class Duplicated(FixtureExtractor):
        def items(self):
            for message in super().items():
                yield message
                if message[0] == Message.Url:
                    yield message

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        setup_job(payload, base, monkeypatch)
        assert worker.ArchiveJob(Duplicated(base)).run() == 0
        assert 2 <= activity["peak"] <= 4
        assert activity["hits"] == 5
        assert worker.SUMMARY["downloaded"] == 5
    finally:
        server.shutdown()


def test_deleted_media_is_not_redownloaded_and_can_be_restored(payload, local_media, monkeypatch, tmp_path):
    base, hits = local_media
    store = Store(payload["data_dir"])
    store.save_settings({"download_dir": payload["settings"]["download_dir"]})
    author_id = store.add_author(payload["handle"])
    assert setup_job(payload, base, monkeypatch).run() == 0
    engine = Engine(store, Vault(store.root))
    folder = Path(payload["settings"]["download_dir"]) / payload["handle"]
    for path in folder.glob("*.*"):
        parts = path.stem.split("_")
        engine._record_media(author_id, {"path":str(path),"tweet_id":parts[-2],"num":int(parts[-1]),
            "published_at":"2020-02-03T04:05:06+00:00","size":path.stat().st_size,
            "kind":"video" if path.suffix == ".mp4" else "image"})
    removed = folder / "2020-02-03_040506Z_12345_02.jpg"
    removed.unlink()
    assert store.reconcile_missing(store.author(author_id)) == 1
    assert setup_job(payload, base, monkeypatch).run() == 0
    assert not removed.exists() and sum(hits.values()) == 5
    assert store.snapshot()["totals"]["excluded"] == 1
    assert store.snapshot()["totals"]["files"] == 4
    # Scope changes and removing/readding authors do not clear the exclusion.
    payload["settings"]["download_dir"] += "-new"
    assert setup_job(payload, base, monkeypatch).run() == 0
    assert sum(hits.values()) == 9
    payload["settings"]["download_dir"] = str(folder.parent)
    app = create_app(store.root, start_engine=False)
    with TestClient(app) as client:
        token = re.search('name="app-token" content="([^"]+)"', client.get("/").text)[1]
        headers = {"X-App-Token":token}
        assert client.post("/api/media/restore", headers=headers, json={"tweet_id":"12345","num":2}).status_code == 200
    store.reconcile_missing(store.author(author_id))
    assert setup_job(payload, base, monkeypatch).run() == 0
    assert removed.exists() and sum(hits.values()) == 10


def test_api_delete_excludes_only_chosen_asset_and_keeps_tombstone(tmp_path):
    app = create_app(tmp_path / "data", start_engine=False)
    store = app.state.store
    folder = Path(store.get_setting("download_dir")) / "Ku1Tetsuya"
    folder.mkdir(parents=True)
    engine = app.state.engine
    for num in (1,2):
        file = folder / f"2020-01-01_000000Z_12345_{num:02}.jpg"
        file.write_bytes(b"image-content")
        engine._record_media(1, {"path":str(file),"tweet_id":"12345","num":num,
                               "published_at":"2020-01-01T00:00:00+00:00","size":13,"kind":"image"})
    with TestClient(app) as client:
        token = re.search('name="app-token" content="([^"]+)"', client.get("/").text)[1]
        headers = {"X-App-Token":token}
        path = str(folder / "2020-01-01_000000Z_12345_01.jpg")
        assert client.post("/api/media/delete", headers=headers,json={"path":path}).status_code == 200
        assert not Path(path).exists()
        assert (folder / "2020-01-01_000000Z_12345_02.jpg").exists()
        assert client.get("/api/media?excluded=true", headers=headers).json()["total"] == 1
        assert client.get("/api/media", headers=headers).json()["total"] == 1
        assert client.post("/api/media/delete", headers=headers,json={"path":str(tmp_path/'untracked')}).status_code == 404
        assert client.delete("/api/authors/1", headers=headers).status_code == 200
        assert client.post("/api/authors",headers=headers,json={"handle":"Ku1Tetsuya"}).status_code == 200
        assert client.get("/api/media?excluded=true", headers=headers).json()["total"] == 1
    assert Store(store.root).snapshot()["totals"]["excluded"] == 1


def test_unavailable_folder_is_not_recorded_as_mass_deletion(tmp_path):
    store = Store(tmp_path / "data")
    engine = Engine(store, Vault(store.root))
    missing = Path(store.get_setting("download_dir")) / "Ku1Tetsuya" / "missing.jpg"
    engine._record_media(1, {"path":str(missing),"tweet_id":"12345","num":1,
                           "published_at":"2020-01-01T00:00:00+00:00","size":13,"kind":"image"})
    with pytest.raises(ValueError, match="媒体文件夹不可用"):
        store.reconcile_missing(store.author(1))
    assert store.snapshot()["totals"]["excluded"] == 0


def test_twitter_generator_metadata_is_not_shared_between_downloads():
    original={"tweet_id":"42","num":1,"date":datetime(2020,1,1),"extension":"jpg",
              "author":{"name":"SampleUser"}, "_fallback":iter(["lower-quality-url"]),
              "files":[{"_fallback":iter(["nested-generator"])}]}
    copied=worker.asset_metadata(original)
    copied["author"]["name"]="Changed"
    assert original["author"]["name"] == "SampleUser"
    assert "_fallback" not in copied and "files" not in copied


def test_explorer_deletion_after_preflight_is_still_ignored(payload, local_media, monkeypatch):
    base,hits=local_media
    store=Store(payload["data_dir"])
    store.save_settings({"download_dir":payload["settings"]["download_dir"]})
    author_id=store.add_author(payload["handle"])
    assert setup_job(payload,base,monkeypatch).run() == 0
    path=Path(payload["settings"]["download_dir"]) / payload["handle"] / "2020-02-03_040506Z_12345_01.jpg"
    Engine(store,Vault(store.root))._record_media(author_id,{"path":str(path),"tweet_id":"12345","num":1,
        "published_at":"2020-02-03T04:05:06+00:00","size":path.stat().st_size,"kind":"image"})
    assert store.reconcile_missing(store.author(author_id)) == 0
    path.unlink()  # simulate deletion during the scan, after reconciliation
    assert setup_job(payload,base,monkeypatch).run() == 0
    assert not path.exists() and sum(hits.values()) == 5
    assert store.snapshot()["totals"]["excluded"] == 1


def test_inflight_deleted_asset_is_removed_after_download(payload, local_media, monkeypatch):
    base,hits=local_media
    store=Store(payload["data_dir"])
    job=setup_job(payload,base,monkeypatch)
    original=worker.AssetJob.download
    def download_then_exclude(self,url):
        result=original(self,url)
        if self.pathfmt.kwdict["tweet_id"] == "12345" and self.pathfmt.kwdict["num"] == 2:
            store.exclude("12345",2,"SampleUser",self.pathfmt.realpath,"manual")
        return result
    monkeypatch.setattr(worker.AssetJob,"download",download_then_exclude)
    assert job.run() == 0
    files=list(Path(payload["settings"]["download_dir"]).rglob("*.*"))
    assert len(files) == 4
    assert not any(p.name.endswith("12345_02.jpg") for p in files)
    assert worker.SUMMARY["downloaded"] == 4 and worker.SUMMARY["skipped"] == 1


def test_zero_byte_archive_file_is_repaired_not_excluded(payload,local_media,monkeypatch):
    base,hits=local_media
    assert setup_job(payload,base,monkeypatch).run() == 0
    path=Path(payload["settings"]["download_dir"]) / payload["handle"] / "2020-02-03_040506Z_12345_01.jpg"
    path.write_bytes(b"")
    assert setup_job(payload,base,monkeypatch).run() == 0
    assert path.stat().st_size > 0 and sum(hits.values()) == 6


def test_avatar_saved_locally_without_resizing(payload,monkeypatch):
    from PIL import Image
    from io import BytesIO
    import requests
    content=BytesIO()
    Image.new("RGB",(320,320),"gray").save(content,format="PNG")
    original=content.getvalue()
    class Session:
        proxies={}
        def get(self,url,**kwargs):
            assert url == "https://pbs.twimg.com/profile_images/sample.png"
            class Response:
                content=original
                def raise_for_status(self):pass
            return Response()
        def close(self):pass
    monkeypatch.setattr(requests,"Session",Session)
    monkeypatch.setattr(worker,"PAYLOAD",payload)
    worker.save_avatar("https://pbs.twimg.com/profile_images/sample.png")
    assert (Path(payload["data_dir"])/"avatars"/"sampleuser.img").read_bytes() == original
    assert (Path(payload["settings"]["download_dir"])/"SampleUser"/"avatar.png").read_bytes() == original


def test_migrated_folder_and_account_rename_do_not_download_again(payload,local_media,monkeypatch):
    base,hits=local_media
    store=Store(payload['data_dir']);store.save_settings({'download_dir':payload['settings']['download_dir']})
    author_id=store.add_author(payload['handle'])
    assert setup_job(payload,base,monkeypatch).run()==0
    folder=Path(payload['settings']['download_dir'])/payload['handle']
    engine=Engine(store,Vault(store.root))
    for path in folder.glob('*.*'):
        parts=path.stem.split('_')
        engine._record_media(author_id,{'path':str(path),'tweet_id':parts[-2],'num':int(parts[-1]),
          'published_at':'2020-02-03T04:05:06+00:00','size':path.stat().st_size,'kind':'image'})
    author=store.bind_profile(author_id,{'user_id':'123','handle':'SampleUser','display_name':'つた'})
    author=store.bind_profile(author_id,{'user_id':'123','handle':'ChangedHandle','display_name':'別名'})
    payload.update({key:author[key] for key in ('handle','user_id','folder_name','archive_key')})
    original_items=FixtureExtractor.items
    def identified_items(self):
        for message,url,meta in original_items(self):
            meta['author']['id']=123
            yield message,url,meta
    monkeypatch.setattr(FixtureExtractor,'items',identified_items)
    assert setup_job(payload,base,monkeypatch).run()==0
    assert sum(hits.values())==5 and worker.SUMMARY['skipped']==5
    assert not folder.exists()
    assert len(list((folder.parent/'つた@SampleUser').glob('*.*')))==5
