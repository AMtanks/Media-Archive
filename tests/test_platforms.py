from datetime import datetime, timezone
import os
import re

import pytest

from app.platforms import media_metadata, parse_profile_url
from app.secrets import PlatformVault
from app.store import Store
from app import worker
from app.server import RestoreInput
from app.server import create_app
from fastapi.testclient import TestClient


def test_fresh_public_install_starts_without_an_author(tmp_path, monkeypatch):
    monkeypatch.delenv('MEDIA_ARCHIVE_TEST_SEED', raising=False)
    store = Store(tmp_path / 'data')
    assert store.authors() == []


def test_profile_urls_ignore_tracking_parameters_and_reject_post_urls():
    assert parse_profile_url('https://www.instagram.com/taurus_lris?igsh=abc&utm_source=qr') == ('instagram', 'taurus_lris')
    assert parse_profile_url('https://weibo.com/u/1040117277?tabtype=album') == ('weibo', '1040117277')
    with pytest.raises(ValueError):
        parse_profile_url('https://www.instagram.com/p/ABC/')
    with pytest.raises(ValueError):
        parse_profile_url('https://instagram.com.example.com/taurus_lris')


def test_media_keys_are_platform_scoped_and_keep_multi_image_positions():
    date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    instagram = media_metadata('instagram', {'post_id': '123', 'date': date, 'num': 2, 'extension': 'jpg'})
    weibo = media_metadata('weibo', {'status': {'id': '123', 'date': date}, 'num': 2, 'extension': 'jpg'})
    assert instagram['tweet_id'] == 'instagram:123'
    assert weibo['tweet_id'] == 'weibo:123'
    assert instagram['num'] == weibo['num'] == 2
    assert RestoreInput(tweet_id='instagram:123', num=2).tweet_id == 'instagram:123'
    assert RestoreInput(tweet_id='weibo:123', num=2).tweet_id == 'weibo:123'
    with pytest.raises(ValueError):
        media_metadata('instagram', {'post_id': '123', 'date': date})


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI')
def test_platform_credentials_are_separate_and_encrypted(tmp_path):
    instagram = PlatformVault(tmp_path, 'instagram')
    weibo = PlatformVault(tmp_path, 'weibo')
    instagram.save({'sessionid': 'local-test-secret'})
    assert b'local-test-secret' not in instagram.path.read_bytes()
    assert instagram.read() == {'sessionid': 'local-test-secret'}
    assert weibo.read() == {}
    instagram.clear()
    assert instagram.read() == {}


def test_external_profiles_are_namespaced_and_folder_binding_is_stable(tmp_path):
    store = Store(tmp_path / 'data')
    instagram_id = store.add_author('https://www.instagram.com/taurus_lris/?igsh=abc')
    weibo_id = store.add_author('https://weibo.com/u/1040117277?tabtype=album')
    ig = store.bind_external_profile(instagram_id, {'user_id':'123', 'display_name':'Creator'})
    wb = store.bind_external_profile(weibo_id, {'user_id':'123', 'display_name':'Creator'})
    assert ig['user_id'] == 'instagram:123' and wb['user_id'] == 'weibo:123'
    assert ig['folder_name'] != wb['folder_name']
    assert store.bind_external_profile(instagram_id, {'user_id':'123', 'display_name':'Renamed'})['folder_name'] == ig['folder_name']
    with pytest.raises(ValueError):
        store.bind_external_profile(instagram_id, {'user_id':'999', 'display_name':'Different'})


def test_deleted_platform_file_is_ignored_without_affecting_other_platform(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data')
    author_id = store.add_author('https://weibo.com/u/1040117277')
    author = store.bind_external_profile(author_id, {'user_id':'1040117277', 'display_name':'Creator'})
    folder = store.author_folder(author)
    folder.mkdir(parents=True)
    filename = folder / 'post.jpg'
    with store.connect() as db:
        db.execute('INSERT INTO media VALUES (?,?,?,?,?,?,?,?)',
                   (str(filename), author_id, 'weibo:123', 1, '2026-01-01', 10, 'image', '2026-01-01'))
    monkeypatch.setattr(worker, 'PAYLOAD', {'data_dir':str(store.root), 'handle':author['handle'],
        'folder_name':author['folder_name'], 'settings':{'download_dir':store.get_setting('download_dir')}})
    assert worker.excluded({'tweet_id':'weibo:123', 'num':1})
    assert not worker.excluded({'tweet_id':'instagram:123', 'num':1})
    with store.connect() as db:
        assert db.execute('SELECT tweet_id,reason FROM exclusions').fetchone()[:] == ('weibo:123', 'external')


def test_api_adds_platform_profile_and_restores_namespaced_ignore(tmp_path):
    app = create_app(tmp_path / 'data', start_engine=False)
    with TestClient(app) as client:
        token = re.search(r'name="app-token" content="([^"]+)"', client.get('/').text)[1]
        headers = {'X-App-Token': token}
        response = client.post('/api/authors', headers=headers, json={'handle':'https://weibo.com/u/1040117277?tabtype=album'})
        assert response.status_code == 200
        assert app.state.store.author(response.json()['id'])['handle'] == 'weibo:1040117277'
        app.state.store.exclude('weibo:123', 1, 'weibo:1040117277', str(tmp_path / 'missing.jpg'), 'manual')
        assert client.post('/api/media/restore', headers=headers, json={'tweet_id':'weibo:123','num':1}).status_code == 200


def test_language_setting_is_validated_and_persisted(tmp_path):
    app = create_app(tmp_path / 'data', start_engine=False)
    with TestClient(app) as client:
        token = re.search(r'name="app-token" content="([^"]+)"', client.get('/').text)[1]
        headers = {'X-App-Token': token}
        assert client.put('/api/ui-language', headers=headers, json={'language':'en'}).status_code == 200
        assert app.state.store.get_setting('ui_language') == 'en'
        assert client.put('/api/ui-language', headers=headers, json={'language':'other'}).status_code == 400
        assert app.state.store.get_setting('ui_language') == 'en'
