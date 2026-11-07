import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.server import create_app
from app.engine import Engine
from app.secrets import Vault


def add_file(app, author_id, folder, num):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{num}.jpg"
    path.write_bytes(b"original")
    app.state.engine._record_media(author_id, {"path": str(path), "tweet_id": str(1000+num),
        "num": 1, "published_at": "2020-01-01T00:00:00+00:00", "size": 8, "kind": "image"})
    return path


def session(client):
    return {"X-App-Token": re.search('name="app-token" content="([^"]+)"',client.get('/').text)[1]}


def test_platform_filter_for_saved_and_ignored_media(tmp_path):
    app = create_app(tmp_path/'data', start_engine=False)
    store = app.state.store
    ig_id = store.add_author('https://instagram.com/example')
    wb_id = store.add_author('https://weibo.com/u/123456')
    ig = store.bind_external_profile(ig_id, {'user_id':'12', 'display_name':'IG'})
    wb = store.bind_external_profile(wb_id, {'user_id':'123456', 'display_name':'WB'})
    for author_id, author in ((1, store.author(1)), (ig_id, ig), (wb_id, wb)):
        add_file(app, author_id, store.author_folder(author), author_id)
        store.exclude(f'ignored-{author_id}', 1, author['handle'], str(tmp_path / f'gone-{author_id}.jpg'), 'manual')
    with TestClient(app) as client:
        headers = session(client)
        for platform, author_id in [('twitter',1), ('instagram',ig_id), ('weibo',wb_id)]:
            saved = client.get('/api/media', headers=headers, params={'platform':platform}).json()
            ignored = client.get('/api/media', headers=headers, params={'platform':platform,'excluded':'true'}).json()
            assert saved['total'] == 1 and saved['items'][0]['author_id'] == author_id
            assert ignored['total'] == 1 and ignored['items'][0]['tweet_id'] == f'ignored-{author_id}'
        assert client.get('/api/media', headers=headers, params={'platform':'invalid'}).status_code == 400


def test_gallery_100_per_page_and_batch_deletion_only_selected(tmp_path):
    app = create_app(tmp_path/'data', start_engine=False)
    store = app.state.store
    folder = store.author_folder(store.author(1))
    paths = [add_file(app, 1, folder, num) for num in range(105)]
    with TestClient(app) as client:
        headers = session(client)
        page = client.get('/api/media', headers=headers).json()
        assert page['limit'] == 100 and len(page['items']) == 100 and page['total'] == 105
        next_page = client.get('/api/media?offset=100',headers=headers).json()
        assert len(next_page['items']) == 5
        ids = [page['items'][0]['media_id'], page['items'][1]['media_id']]
        result = client.post('/api/media/delete-batch',headers=headers,json={'media_ids': [*ids,ids[0],9999]}).json()
        assert result['deleted'] == ids and result['failed'][0]['media_id'] == 9999
        for item in page['items'][:2]:
            assert not Path(item['path']).exists()
        assert sum(path.exists() for path in paths) == 103
        assert client.get('/api/media',headers=headers).json()['total'] == 103
        assert client.get('/api/media?excluded=true',headers=headers).json()['total'] == 2
        assert client.post('/api/media/delete-batch',headers=headers,json={'media_ids':list(range(101))}).status_code == 422


def test_removed_author_disappears_and_catalog_history_clears_files_untouched(tmp_path):
    app = create_app(tmp_path/'data', start_engine=False)
    store = app.state.store
    path = add_file(app, 1, store.author_folder(store.author(1)), 1)
    with store.connect() as db:
        run_id = db.execute("INSERT INTO runs(author_id,handle,mode,status,started_at) VALUES (1,'Ku1Tetsuya','full','success','2020')").lastrowid
    store.add_event(run_id, 'info', 'old saved file')
    with TestClient(app) as client:
        headers = session(client)
        link = client.get('/api/media',headers=headers).json()['items'][0]['content_url']
        assert client.delete('/api/authors/1',headers=headers).status_code == 200
        assert path.read_bytes() == b'original'
        assert client.get('/api/media',headers=headers).json()['total'] == 0
        state = client.get('/api/state',headers=headers).json()
        assert not state['recent'] and not state['runs'] and not state['events']
        assert client.get(link).status_code == 404


def test_remove_author_and_delete_only_its_folder(tmp_path):
    app = create_app(tmp_path/'data', start_engine=False)
    store = app.state.store
    folder = store.author_folder(store.author(1))
    path = add_file(app, 1, folder, 1)
    (folder/'avatar.jpg').write_bytes(b'avatar')
    (folder/'other.txt').write_text('other')
    other_id = store.add_author('OtherAccount')
    other = add_file(app, other_id, store.author_folder(store.author(other_id)), 2)
    store.exclude('old-ignore', 1, store.author(1)['handle'], str(folder/'old.jpg'), 'manual')
    with TestClient(app) as client:
        response = client.delete('/api/authors/1?delete_files=true', headers=session(client))
        assert response.status_code == 200
        assert not folder.exists() and not path.exists()
        assert other.exists() and store.author(other_id)
        assert store.author(1) is None
        with store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM exclusions WHERE tweet_id='old-ignore'").fetchone()[0] == 1


def test_remove_and_delete_failure_keeps_author_and_records(tmp_path, monkeypatch):
    app = create_app(tmp_path/'data', start_engine=False)
    store = app.state.store
    path = add_file(app, 1, store.author_folder(store.author(1)), 1)
    def fail(_):
        raise PermissionError('file in use')
    monkeypatch.setattr('app.store.shutil.rmtree', fail)
    with TestClient(app) as client:
        assert client.delete('/api/authors/1?delete_files=true', headers=session(client)).status_code == 409
        assert store.author(1) and path.exists()
        with store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM media WHERE author_id=1').fetchone()[0] == 1


def test_remove_and_delete_rejects_paths_outside_root_and_busy_author(tmp_path):
    app = create_app(tmp_path/'data', start_engine=False)
    store = app.state.store
    outside = tmp_path/'protected'
    outside.mkdir()
    (outside/'keep.txt').write_text('safe')
    with store.connect() as db:
        db.execute("UPDATE authors SET folder_name='../protected' WHERE id=1")
    with TestClient(app) as client:
        headers = session(client)
        assert client.delete('/api/authors/1?delete_files=true', headers=headers).status_code == 409
        assert store.author(1) and (outside/'keep.txt').exists()
        app.state.engine.pending[1] = 'test'
        assert client.delete('/api/authors/1?delete_files=true', headers=headers).status_code == 409
        app.state.engine.pending.clear()


def test_deleted_author_folder_clears_catalog_and_pauses_without_mass_ignore(tmp_path):
    app = create_app(tmp_path/'data', start_engine=False)
    store = app.state.store
    folder = store.author_folder(store.author(1))
    path = add_file(app, 1, folder, 1)
    path.unlink(); folder.rmdir()
    with TestClient(app) as client:
        headers = session(client)
        state = client.get('/api/state',headers=headers).json()
        assert len(state['authors']) == 1
        author = state['authors'][0]
        assert not author['enabled'] and author['folder_removed'] and not author['gallery_available']
        assert state['totals']['files'] == 0 and not state['recent']
        assert client.get('/api/media',headers=headers).json()['total'] == 0
        assert '先恢复文件夹' in client.post('/api/authors/1/sync',headers=headers,json={}).json()['detail']
        assert not folder.exists()
        with store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM media').fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM exclusions').fetchone()[0] == 0
        folder.mkdir()
        assert client.get('/api/state',headers=headers).json()['authors'][0]['folder_removed'] == 0
        assert not store.author(1)['enabled']


def test_unavailable_root_and_destination_change_do_not_purge(tmp_path):
    app = create_app(tmp_path/'data', start_engine=False)
    store = app.state.store
    folder = store.author_folder(store.author(1))
    path = add_file(app, 1, folder, 1)
    root = folder.parent
    moved = root.with_name('disconnected')
    root.rename(moved)
    app.state.engine.maintain_catalog()
    assert store.author(1)['enabled'] and not store.author(1)['folder_removed']
    assert store.snapshot()['totals']['files'] == 1
    moved.rename(root)
    other = tmp_path/'new-destination'; other.mkdir()
    store.save_settings({'download_dir':str(other)})
    app.state.engine.maintain_catalog()
    assert store.snapshot()['totals']['files'] == 1 and path.exists()


def test_old_orphan_catalog_pruned_and_ignored_rules_remain_hidden(tmp_path):
    app = create_app(tmp_path/'data', start_engine=False)
    store = app.state.store
    path = add_file(app, 1, store.author_folder(store.author(1)), 1)
    store.exclude('1001',1,'Ku1Tetsuya',str(path),'manual')
    with store.connect() as db:
        db.execute('DELETE FROM authors WHERE id=1')
    with TestClient(app) as client:
        headers = session(client)
        assert client.get('/api/media',headers=headers).json()['total'] == 0
        assert client.get('/api/media?excluded=true',headers=headers).json()['total'] == 0
        assert client.get('/api/state',headers=headers).json()['totals']['excluded'] == 0
        with store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM media').fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM exclusions').fetchone()[0] == 1


def test_batch_file_busy_reports_failure_and_remains_excluded(tmp_path,monkeypatch):
    app = create_app(tmp_path/'data', start_engine=False)
    store = app.state.store
    path = add_file(app, 1, store.author_folder(store.author(1)), 1)
    original_unlink = Path.unlink
    def busy(self,*args,**kwargs):
        if self == path: raise PermissionError('file in use')
        return original_unlink(self,*args,**kwargs)
    with TestClient(app) as client:
        headers = session(client)
        media_id = client.get('/api/media',headers=headers).json()['items'][0]['media_id']
        monkeypatch.setattr(Path,'unlink',busy)
        result = client.post('/api/media/delete-batch',headers=headers,json={'media_ids':[media_id]}).json()
        assert not result['deleted'] and result['failed'][0]['media_id'] == media_id
        assert path.exists() and client.get('/api/media',headers=headers).json()['total'] == 0
        assert client.get('/api/media?excluded=true',headers=headers).json()['total'] == 1


def test_slow_thumbnails_do_not_block_delete(tmp_path, monkeypatch):
    import concurrent.futures
    import threading
    import time
    from app.previews import PreviewCache

    app = create_app(tmp_path/'data', start_engine=False)
    folder = app.state.store.author_folder(app.state.store.author(1))
    add_file(app, 1, folder, 1)
    entered, release = threading.Event(), threading.Event()
    def slow_thumbnail(self, path):
        entered.set()
        release.wait(10)
        return path
    monkeypatch.setattr(PreviewCache, 'thumbnail', slow_thumbnail)
    with TestClient(app) as client, concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
        headers = session(client)
        item = client.get('/api/media', headers=headers).json()['items'][0]
        pending = [pool.submit(client.get, item['thumbnail_url']) for _ in range(45)]
        try:
            assert entered.wait(3)
            time.sleep(.3)  # Allow requests to queue behind the two slow thumbnail workers.
            deletion = pool.submit(client.post, '/api/media/delete-batch', headers=headers,
                                   json={'media_ids':[item['media_id']]})
            assert deletion.result(timeout=3).json()['deleted'] == [item['media_id']]
        finally:
            release.set()
            concurrent.futures.wait(pending, timeout=10)


def test_thumbnails_are_cacheable_but_api_is_not(tmp_path):
    from PIL import Image
    app = create_app(tmp_path/'data', start_engine=False)
    store = app.state.store
    path = add_file(app, 1, store.author_folder(store.author(1)), 1)
    Image.new("RGB", (8, 8), "gray").save(path, "JPEG")
    with TestClient(app) as client:
        headers = session(client)
        response = client.get('/api/media', headers=headers)
        assert response.headers['cache-control'] == 'no-store'
        item = response.json()['items'][0]
        thumb = client.get(item['thumbnail_url'])
        assert thumb.status_code == 200 and thumb.headers['cache-control'] == 'private, max-age=86400'
        assert client.get(item['content_url']).headers['cache-control'] == 'private, max-age=86400'


def test_activate_brings_running_window_forward(tmp_path):
    app = create_app(tmp_path/'data', start_engine=False)
    calls = []
    with TestClient(app) as client:
        assert client.post('/activate', headers={'X-Activate': '1'}).status_code == 409
        app.state.activate_callback = lambda: calls.append(1)
        assert client.post('/activate').status_code == 403
        assert client.post('/activate', headers={'X-Activate': '1'}).status_code == 204 and calls == [1]
        app.state.activate_callback = lambda: False
        assert client.post('/activate', headers={'X-Activate': '1'}).status_code == 409
