import hashlib
import io
import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.store import Store, folder_label, canonical_path
from app.engine import Engine
from app.secrets import Vault
from app.server import create_app
from app.previews import PreviewCache
from app import worker


def record(store,path,num=1):
    Engine(store,Vault(store.root))._record_media(1,{"path":str(path),"tweet_id":"12345","num":num,
        "published_at":"2020-01-01T00:00:00+00:00","size":12,"kind":"image"})


def test_fixed_folder_migration_preserves_files_indices_and_deleted_items(tmp_path):
    store=Store(tmp_path/"data")
    source=Path(store.get_setting("download_dir"))/"Ku1Tetsuya"
    source.mkdir(parents=True)
    file=source/"2020-01-01_000000Z_12345_01.jpg"
    file.write_bytes(b"original-data")
    removed=source/"2020-01-01_000000Z_12345_02.jpg"
    record(store,file);record(store,removed,2)
    store.exclude("12345",2,"Ku1Tetsuya",str(removed),"external")
    before=store.snapshot()["recent"][0]["media_id"]
    author=store.bind_profile(1,{"user_id":"123","handle":"Ku1Tetsuya","display_name":"つた"})
    target=source.parent/"つた@Ku1Tetsuya"
    assert author["folder_name"] == "つた@Ku1Tetsuya"
    assert not source.exists() and (target/file.name).read_bytes() == b"original-data"
    assert not (target/removed.name).exists()
    assert store.snapshot()["recent"][0]["media_id"] == before
    assert canonical_path(store.snapshot()["recent"][0]["path"]).parent == target
    assert store.reconcile_missing(author) == 1
    assert store.media_page(excluded=True)["total"] == 1
    # Both display name and screen name may change, while the directory/archive stay fixed.
    renamed=store.bind_profile(1,{"user_id":"123","handle":"NewHandle","display_name":"新しい名前"})
    assert renamed["handle"] == "NewHandle" and renamed["display_name"] == "新しい名前"
    assert renamed["folder_name"] == author["folder_name"] and renamed["archive_key"] == "ku1tetsuya"
    assert (target/file.name).exists() and not (source.parent/"新しい名前@NewHandle").exists()
    # Removing/readding the author retains the persistent identity binding.
    with store.connect() as db:db.execute("DELETE FROM authors WHERE id=1")
    next_id=store.add_author("NewHandle")
    rebound=store.bind_profile(next_id,{"user_id":"123","handle":"NewHandle","display_name":"再改名"})
    assert rebound["folder_name"] == author["folder_name"]
    assert store.authors()[0]["files"] == 1
    assert store.media_page(next_id,excluded=True)["total"] == 1


def test_folder_migration_recovers_after_move_before_database_commit(tmp_path):
    store=Store(tmp_path/"data")
    root=Path(store.get_setting("download_dir"));old=root/"Ku1Tetsuya";old.mkdir(parents=True)
    path=old/"one.jpg";path.write_bytes(b"data");record(store,path)
    with store.connect() as db:
        db.execute("INSERT INTO profiles VALUES ('123','つた@Ku1Tetsuya','ku1tetsuya','つた','Ku1Tetsuya')")
        db.execute("UPDATE authors SET user_id='123',folder_name='Ku1Tetsuya' WHERE id=1")
    old.rename(root/"つた@Ku1Tetsuya")  # process died here, before rewriting media paths
    author=store.bind_profile(1,{"user_id":"123","handle":"Changed","display_name":"Changed"})
    assert author["folder_name"] == "つた@Ku1Tetsuya"
    assert Path(store.snapshot()["recent"][0]["path"]).read_bytes() == b"data"


def test_folder_conflicts_and_identity_reuse_cannot_overwrite_files(tmp_path):
    store=Store(tmp_path/"data")
    root=Path(store.get_setting("download_dir"));old=root/"Ku1Tetsuya";old.mkdir(parents=True)
    (old/"one.jpg").write_bytes(b"old")
    target=root/"つた@Ku1Tetsuya";target.mkdir();(target/"one.jpg").write_bytes(b"other")
    with pytest.raises(ValueError,match="同时存在"):
        store.bind_profile(1,{"user_id":"123","handle":"Ku1Tetsuya","display_name":"つた"})
    assert (old/"one.jpg").read_bytes()==b"old" and (target/"one.jpg").read_bytes()==b"other"
    with pytest.raises(ValueError,match="身份发生变化"):
        store.bind_profile(1,{"user_id":"999","handle":"Ku1Tetsuya","display_name":"Other"})


def test_folder_label_windows_safe_and_stays_in_root():
    label=folder_label('../x:<bad>|?*' + '🐈'*200,'SampleUser')
    assert not any(c in label for c in '<>:"/\\|?*')
    assert label.endswith('@SampleUser') and len(label.encode('utf-16-le'))<=184
    assert folder_label('つた','tutamaru__')=='つた@tutamaru__'


def test_archive_identity_survives_display_and_handle_changes(tmp_path,monkeypatch):
    payload={"handle":"OldHandle","data_dir":str(tmp_path/"data"),"credentials":{},"settings":{
      "download_dir":str(tmp_path/"media"),"include_replies":True,"include_quotes":False,"include_retweets":False}}
    original=worker.build_config(payload)["extractor"]["twitter"]["archive"]
    payload.update(handle="NewHandle",folder_name="初名@OldHandle",user_id="123",archive_key="oldhandle")
    changed=worker.build_config(payload)["extractor"]["twitter"]
    assert changed["archive"]==original and changed["directory"]==["初名@OldHandle"]
    monkeypatch.setattr(worker,'PAYLOAD',payload)
    assert worker.is_target({"id":123,"name":"RenamedAgain"})
    assert not worker.is_target({"id":999,"name":"NewHandle"})


def test_signed_local_previews_thumbnail_original_range_and_exclusion(tmp_path):
    app=create_app(tmp_path/"data",start_engine=False);store=app.state.store
    folder=Path(store.get_setting('download_dir'))/'Ku1Tetsuya';folder.mkdir(parents=True)
    path=folder/'photo.png';Image.new('RGB',(1200,1600),'gray').save(path)
    original=path.read_bytes();record(store,path)
    with TestClient(app) as client:
        token=re.search('name="app-token" content="([^"]+)"',client.get('/').text)[1]
        item=client.get('/api/media',headers={'X-App-Token':token}).json()['items'][0]
        assert token not in item['content_url']
        assert client.get('/preview/1/content').status_code==403
        assert client.get(item['content_url'].replace('/content?','/thumb?')).status_code==403
        image=client.get(item['thumbnail_url'])
        assert image.status_code==200 and image.headers['content-type']=='image/jpeg'
        with Image.open(io.BytesIO(image.content)) as thumb:assert thumb.size==(640,853)
        assert client.get(item['content_url']).content==original
        partial=client.get(item['content_url'],headers={'Range':'bytes=0-9'})
        assert partial.status_code==206 and partial.content==original[:10]
        client.post('/api/media/delete',headers={'X-App-Token':token},json={'path':str(path)})
        assert client.get(item['content_url']).status_code==404
        assert client.get(item['thumbnail_url']).status_code==404


def test_thumbnail_does_not_modify_source_and_cache_is_reused(tmp_path):
    path=tmp_path/'image.png';Image.new('RGB',(800,400),'gray').save(path)
    original=hashlib.sha256(path.read_bytes()).digest();cache=PreviewCache(tmp_path/'data')
    preview=cache.thumbnail(path);mtime=preview.stat().st_mtime_ns
    assert cache.thumbnail(path)==preview and preview.stat().st_mtime_ns==mtime
    assert hashlib.sha256(path.read_bytes()).digest()==original


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_video_poster_is_image_and_original_video_untouched(tmp_path):
    path=tmp_path/'video.mp4'
    subprocess.run([shutil.which('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=gray:s=160x90:r=5',
        '-t','1','-c:v','libx264',str(path)],check=True,capture_output=True)
    original=hashlib.sha256(path.read_bytes()).digest()
    thumb=PreviewCache(tmp_path/'data').thumbnail(path)
    with Image.open(thumb) as image:assert image.size==(640,360) and image.format=='JPEG'
    assert hashlib.sha256(path.read_bytes()).digest()==original


def test_windows_extended_path_events_and_migration_keep_one_record(tmp_path):
    store=Store(tmp_path/'data');path=Path(store.get_setting('download_dir'))/'Ku1Tetsuya'/'one.jpg'
    path.parent.mkdir(parents=True);path.write_bytes(b'data')
    record(store,path)
    extended='\\\\?\\'+str(path)
    record(store,extended)
    assert store.snapshot()['totals']['files']==1
    with store.connect() as db:
        row=db.execute('SELECT * FROM media').fetchone()
        db.execute('INSERT INTO media VALUES (?,?,?,?,?,?,?,?)',(extended,*list(row)[1:]))
    assert store.snapshot()['totals']['files']==2
    reopened=Store(store.root)
    assert reopened.snapshot()['totals']['files']==1


def test_profile_handshake_waits_for_fixed_destination_before_download(tmp_path,monkeypatch):
    import app.engine as module
    saved=[]
    class Input(io.StringIO):
        def close(self):
            saved.append(self.getvalue())
            super().close()
    class Vault:
        def read(self):return {'auth_token':'test-sensitive-token'}
    class Process:
        def __init__(self,*args,**kwargs):
            self.stdin=Input()
            self.stdout=io.StringIO(json.dumps({'event':'profile','user_id':'123','handle':'Ku1Tetsuya','display_name':'つた'})+'\n'+json.dumps({'event':'done','seen':1,'status':0}))
        def wait(self,**kwargs):return 0
        def poll(self):return 0
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    store=Store(tmp_path/'data')
    Engine(store,Vault())._run(1,False)
    messages=[json.loads(line) for line in saved[0].splitlines()]
    assert messages[1]['folder_name']=='つた@Ku1Tetsuya'
    assert messages[1]['user_id']=='123' and 'credentials' not in messages[1]
    assert store.author(1)['last_success'] is not None
