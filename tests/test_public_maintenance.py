import pytest

from app import create_app
from app.db import get_db
from app.services.maintenance_service import write_state


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr('app.db._get_redis_client', lambda: None)
    app = create_app({'TESTING': True, 'DATABASE': str(tmp_path/'public-maintenance.db')})
    with app.app_context(), get_db():
        write_state('mode', {'enabled': True, 'actor': 'private-admin@example.test',
                             'updated_at': '2099-01-01T00:00:00',
                             'deployment': 'internal-server:8012'})
    return app


@pytest.mark.parametrize('path', ['/', '/devis/1', '/devis/1/document.pdf', '/simulation/ABC', '/politique-confidentialite'])
def test_public_pages_show_maintenance(app, path):
    response = app.test_client().get(path)
    assert response.status_code == 503
    assert 'Une pause pour mieux vous accompagner' in response.get_data(as_text=True)
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'wa.me/212661575128' in response.get_data(as_text=True)
    assert '/admin' not in response.get_data(as_text=True)
    assert 'Accès administration' not in response.get_data(as_text=True)
    assert 'private-admin' not in response.get_data(as_text=True)


def test_status_public_private_noncacheable_and_no_internal_data(app):
    guest = app.test_client()
    response = guest.get('/api/maintenance/status')
    assert response.status_code == 200
    assert response.json['maintenance'] is True
    assert set(response.json) == {'maintenance','message'}
    assert 'no-store' in response.headers['Cache-Control']
    assert 'Cookie' in response.headers['Vary']
    assert guest.get('/health').status_code == 200
    assert guest.get('/admin/login').status_code == 200
    blocked = guest.post('/api/calculate', json={})
    assert set(blocked.json) == {'maintenance', 'message', 'error', 'error_code'}
    assert 'private-admin' not in blocked.get_data(as_text=True)
    assert guest.get('/admin/maintenance/snapshot').status_code in (302, 401)


def test_only_valid_active_admin_session_can_bypass(app):
    admin = app.test_client()
    with admin.session_transaction() as session:
        session['admin_user'] = 'direction@heliantha.ma'
    assert admin.get('/api/maintenance/status').json['maintenance'] is False
    assert admin.get('/').status_code == 200
    assert admin.post('/api/calculate', json={}).status_code != 503
    guest = app.test_client()
    assert guest.get('/', headers={'X-Admin': 'true', 'Authorization':'Bearer fake-admin'}).status_code == 503
    with admin.session_transaction() as session:
        session['admin_user'] = 'does-not-exist'
    assert admin.get('/').status_code == 503
    with admin.session_transaction() as session:
        session['admin_user'] = 'direction@heliantha.ma'
    with app.app_context(), get_db() as db:
        db.execute("UPDATE users SET active=0 WHERE username='direction@heliantha.ma'")
    assert admin.get('/').status_code == 503


def test_reopen_is_immediate_without_process_restart(app):
    client = app.test_client()
    assert client.get('/').status_code == 503
    with app.app_context(), get_db():
        write_state('mode', {'enabled': False})
    assert client.get('/api/maintenance/status').json['maintenance'] is False
    assert client.get('/').status_code == 200


def test_template_javascript_contains_no_jinja_syntax(app):
    from pathlib import Path
    import re
    template = (Path(app.root_path).parent/'templates'/'maintenance.html').read_text(encoding='utf-8')
    script = re.search(r'<script>(.*?)</script>', template, re.S).group(1)
    assert '{{' not in script and '{%' not in script
    html = app.test_client().get('/').get_data(as_text=True)
    assert 'data-status-url="/api/maintenance/status"' in html
