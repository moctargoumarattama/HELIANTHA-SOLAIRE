import json
import os
import re
import time
from unittest.mock import Mock

import pytest
import requests

from app import create_app
from app.db import get_db
from app.services import maintenance_service as maintenance


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr('app.db._get_redis_client', lambda: None)
    application = create_app({'TESTING': True, 'DATABASE': str(tmp_path/'maintenance.db')})
    application.instance_path = str(tmp_path/'instance')
    return application


@pytest.fixture
def client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session['admin_user'] = 'direction@heliantha.ma'
    return client


def test_workspace_is_compact_and_reads_do_not_contact_services(client, monkeypatch):
    forbidden = Mock(side_effect=AssertionError('No background network checks'))
    monkeypatch.setattr(maintenance.requests, 'get', forbidden)
    page = client.get('/admin/maintenance')
    assert page.status_code == 200
    assert page.data.count(b'<dialog class="mt-dialog"') == 4
    assert b'admin_maintenance.js' in page.data
    snapshot = client.get('/admin/maintenance/snapshot').get_json()['snapshot']
    assert snapshot['services'] is None
    assert snapshot['integrity'] is None
    assert snapshot['mode']['enabled'] is False
    assert snapshot['ai']['last_run'] is None
    assert snapshot['can_manage'] is True
    forbidden.assert_not_called()


def test_guest_cannot_enter_or_change_maintenance(app):
    client = app.test_client()
    assert client.get('/admin/maintenance').status_code == 302
    response = client.post('/admin/maintenance/actions/mode', json={'confirmed': True, 'enabled': True})
    assert response.status_code in (302, 401)
    with app.app_context():
        assert maintenance.read_state('mode') is None


@pytest.mark.parametrize('action', ['mode', 'cache', 'cleanup'])
def test_actions_require_direction_role(app, client, action):
    with app.app_context(), get_db() as db:
        db.execute("UPDATE users SET role='Commercial' WHERE username='direction@heliantha.ma'")
    response = client.post('/admin/maintenance/actions/'+action, json={'confirmed': True, 'enabled': True})
    assert response.status_code == 403


def test_actions_are_csrf_protected(app, client):
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post('/admin/maintenance/actions/mode', json={'confirmed': True, 'enabled': True}).status_code == 400
    page = client.get('/admin/maintenance').get_data(as_text=True)
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', page).group(1)
    response = client.post('/admin/maintenance/actions/mode', json={'confirmed': True, 'enabled': True}, headers={'X-CSRFToken': token})
    assert response.status_code == 200


@pytest.mark.parametrize('payload', [{}, {'confirmed': 'yes', 'enabled': True}, {'confirmed': True, 'enabled': 'false'}, []])
def test_invalid_mode_payload_is_rejected(client, payload):
    assert client.post('/admin/maintenance/actions/mode', json=payload).status_code == 400
    assert client.get('/health').status_code == 200


def test_mode_persists_and_admin_can_disable_it(app, client):
    assert client.post('/admin/maintenance/actions/mode', json={'confirmed': True, 'enabled': True}).status_code == 200
    for path in ['/api/calculate', '/api/assistant/chat', '/api/assistant/chat/stream']:
        response = app.test_client().post(path, json={})
        assert response.status_code == 503
        assert response.get_json()['maintenance'] is True
        assert response.headers['Retry-After'] == '60'
    assert client.get('/health').status_code == 200
    assert client.get('/admin/login').status_code == 200
    assert client.get('/admin/maintenance').status_code == 200
    second = create_app({'TESTING': True, 'DATABASE': app.config['DATABASE']})
    assert second.test_client().post('/api/calculate', json={}).status_code == 503
    assert client.post('/admin/maintenance/actions/mode', json={'confirmed': True, 'enabled': False}).status_code == 200
    assert app.test_client().post('/api/calculate', json={}).status_code != 503
    events = client.get('/admin/maintenance/snapshot').get_json()['snapshot']['events']
    assert len(events) == 2 and events[0]['actor'] == 'direction@heliantha.ma'


def test_connection_checks_validate_each_service(client, monkeypatch):
    from app.services.ai_service import OLLAMA_MODEL
    def get(url, **kwargs):
        assert kwargs['allow_redirects'] is False
        assert kwargs['timeout'] == (2, 4)
        data = {'models': [{'name': OLLAMA_MODEL+':latest'}]} if url.endswith('/api/tags') else (
            {'connected': True} if url.endswith('/status') else {'success': True, 'data': {'status': 'ok'}})
        return Mock(status_code=200, json=lambda: data, raise_for_status=lambda: None)
    monkeypatch.setattr(maintenance.requests, 'get', get)
    response = client.post('/admin/maintenance/checks/services', json={})
    assert response.status_code == 200
    services = response.get_json()['snapshot']['services']
    assert len(services['items']) == 5
    assert all(s['status']=='ok' for s in services['items'])


def test_service_failure_is_safe_and_does_not_claim_all_online(client, monkeypatch):
    monkeypatch.setattr(maintenance.requests, 'get', Mock(side_effect=requests.Timeout('token=secret host=private')))
    response = client.post('/admin/maintenance/checks/services', json={})
    assert response.status_code == 200
    data = response.get_json()['snapshot']['services']
    assert sum(s['status']=='error' for s in data['items']) == 3
    assert b'secret' not in response.data and b'private' not in response.data


def test_missing_model_and_disconnected_whatsapp_are_warnings(client, monkeypatch):
    monkeypatch.setattr(maintenance.requests, 'get', lambda *a, **k: Mock(status_code=200, json=lambda: {'models': [], 'connected': False}, raise_for_status=lambda: None))
    items = client.post('/admin/maintenance/checks/services', json={}).get_json()['snapshot']['services']['items']
    assert next(s for s in items if s['key']=='ollama')['status']=='warning'
    assert next(s for s in items if s['key']=='whatsapp')['status']=='warning'
    assert next(s for s in items if s['key']=='mobile')['status']=='error'


def test_ai_test_and_real_calls_record_observations(app, client, monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs)
        return Mock(json=lambda: {'message': {'content': 'Bonjour.'}}, raise_for_status=lambda: None)
    monkeypatch.setattr(maintenance.requests, 'post', post)
    response = client.post('/admin/maintenance/checks/ai', json={})
    ai = response.get_json()['snapshot']['ai']
    assert ai['last_run']['success'] is True and ai['last_run']['source']=='test'
    assert calls[0]['json']['keep_alive']==-1
    from app.services.ai_service import chat_with_ollama
    with app.app_context():
        assert chat_with_ollama([{'role': 'user', 'content': 'Bonjour'}], products=[])['content']
        assert maintenance.read_state('ai_last_run')['source']=='assistant'
    monkeypatch.setattr(maintenance.requests, 'post', Mock(side_effect=requests.Timeout('secret')))
    response = client.post('/admin/maintenance/checks/ai', json={})
    ai = response.get_json()['snapshot']['ai']
    assert ai['last_run']['success'] is False
    assert ai['last_success'] and ai['last_incident']
    assert b'secret' not in response.data


def test_integrity_reports_without_mutating_products_or_quotes(app, client):
    with app.app_context(), get_db() as db:
        db.execute("INSERT INTO products(reference,category,sale_price,power_w,active) VALUES ('AUDIT-PV','panels',0,0,1)")
        db.execute("INSERT INTO products(reference,category,sale_price,power_w,active) VALUES (' audit-pv ','panels',700,700,0)")
        for number, ttc in [('MAINT-VALID', 110), ('MAINT-BAD', 115)]:
            financial = json.dumps({'total_ht':100,'vat':10,'total_ttc':ttc})
            db.execute("INSERT INTO quote_requests(quote_number,project,request_json,result_json,financial_breakdown_json,amount_ht,amount_ttc) VALUES (?,'pumping','{}','{}',?,100,?)", (number, financial, ttc))
        before = [tuple(r) for r in db.execute("SELECT * FROM products ORDER BY id")]
    response = client.post('/admin/maintenance/checks/integrity', json={})
    assert response.status_code == 200
    groups = {g['key']:g for g in response.get_json()['snapshot']['integrity']['groups']}
    assert any(i['label']=='AUDIT-PV' for i in groups['prices']['items'])
    assert any(i['label']=='AUDIT-PV' for i in groups['power']['items'])
    assert any(i['label']=='audit-pv' for i in groups['duplicates']['items'])
    assert [i['label'] for i in groups['quotes']['items']] == ['MAINT-BAD']
    with app.app_context():
        assert before == [tuple(r) for r in get_db().execute("SELECT * FROM products ORDER BY id")]
        assert get_db().execute("SELECT amount_ttc FROM quote_requests WHERE quote_number='MAINT-BAD'").fetchone()[0]==115


def test_temporary_cleanup_is_scoped_and_keeps_recent_files_and_documents(app, client, tmp_path):
    folder = tmp_path/'instance'/'tmp'
    folder.mkdir(parents=True)
    for name in ['old.tmp', 'recent.tmp', 'quote.pdf', 'heliantha.db', '.env']:
        path = folder/name
        path.write_text('preserve or clean', encoding='utf-8')
        if name != 'recent.tmp': os.utime(path, (time.time()-172800,)*2)
    outside = tmp_path/'outside.tmp'
    outside.write_text('keep')
    os.utime(outside, (time.time()-172800,)*2)
    assert client.get('/admin/maintenance/temporary-files').get_json()['count']==1
    assert client.post('/admin/maintenance/actions/cleanup', json={}).status_code==400
    assert (folder/'old.tmp').exists()
    assert client.post('/admin/maintenance/actions/cleanup', json={'confirmed': True}).status_code==200
    assert not (folder/'old.tmp').exists()
    assert all((folder/name).exists() for name in ['recent.tmp','quote.pdf','heliantha.db','.env'])
    assert outside.exists()


def test_cache_action_and_overlap_guard(app, client, monkeypatch):
    clear = Mock()
    monkeypatch.setattr(maintenance, 'invalidate_calculation_context', clear)
    assert client.post('/admin/maintenance/actions/cache', json={'confirmed': True}).status_code==200
    clear.assert_called_once()
    lock = app.extensions['maintenance_lock']
    with lock:
        assert client.post('/admin/maintenance/actions/cache', json={'confirmed': True}).status_code==409
        assert client.post('/admin/maintenance/checks/services', json={}).status_code==409
    assert client.get('/admin/maintenance/actions/cleanup').status_code==405


def test_production_checks_use_server_config_not_browser_host(app, client, monkeypatch):
    from app.services import ai_service
    app.config['MOBILE_API_BASE_URL'] = 'http://mobile-api:8000/'
    monkeypatch.setattr(ai_service, 'OLLAMA_HOST', 'http://ollama:11434')
    monkeypatch.setattr(ai_service, 'OLLAMA_MODEL', 'production-ai')
    monkeypatch.setattr(maintenance.socket, 'gethostname', lambda: 'server-production')
    with app.app_context(), get_db() as db:
        db.execute("UPDATE company_settings SET value='http://whatsapp:3001/send-message' WHERE key='whatsapp_gateway_url'")
    urls = []
    def get(url, **kwargs):
        urls.append(url)
        payload = {'models': [{'name': 'production-ai'}], 'connected': True, 'success': True, 'data': {'status': 'ok'}}
        return Mock(status_code=200, json=lambda: payload, raise_for_status=lambda: None)
    monkeypatch.setattr(maintenance.requests, 'get', get)
    response = client.post('/admin/maintenance/checks/services', json={}, headers={'X-Forwarded-Host':'untrusted.example', 'X-Forwarded-Proto':'https'})
    assert response.status_code == 200
    assert set(urls) == {'http://mobile-api:8000/health', 'http://ollama:11434/api/tags', 'http://whatsapp:3001/status'}
    snapshot = response.get_json()['snapshot']
    assert snapshot['deployment']['host'] == 'server-production'
    assert snapshot['ai']['model'] == 'production-ai'
    assert b'mobile-api:8000' not in response.data


@pytest.mark.parametrize('change', ['server', 'configuration'])
def test_observations_are_invalidated_when_deployment_changes(app, client, monkeypatch, change):
    monkeypatch.setattr(maintenance.socket, 'gethostname', lambda: 'dev-pc')
    with app.app_context():
        maintenance.save_check('services', {'items': [], 'checked_at': maintenance.now()})
        maintenance.save_check('integrity', {'groups': [], 'count': 0})
        maintenance.record_ai_observation(False, time.perf_counter())
    before = client.get('/admin/maintenance/snapshot').get_json()['snapshot']
    assert before['services'] is not None and before['ai']['last_incident']
    if change == 'server':
        monkeypatch.setattr(maintenance.socket, 'gethostname', lambda: 'production-server')
    else:
        app.config['MOBILE_API_BASE_URL'] = 'http://new-api:9000'
    after = client.get('/admin/maintenance/snapshot').get_json()['snapshot']
    assert after['services'] is None and after['integrity'] is None
    assert after['ai']['last_run'] is None and after['ai']['last_incident'] is None


def test_blank_optional_mobile_url_uses_api_on_same_server(tmp_path, monkeypatch):
    monkeypatch.setenv('MOBILE_API_BASE_URL', '  ')
    application = create_app({'TESTING': True, 'DATABASE': str(tmp_path/'same-server.db')})
    assert application.config['MOBILE_API_BASE_URL'] == 'http://127.0.0.1:8011'
