from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import create_app
from app.db import list_whatsapp_outbox
from app.services.anti_abuse import (
    ASSISTANT_WAIT_MESSAGE,
    AssistantQuota,
    PhoneCooldown,
)
from app.services.whatsapp_service import notify_quote_created, process_outbox


@pytest.fixture
def protected_app(tmp_path, monkeypatch):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "guard.db")})
    # create_app initialized the schema. Keep real SQLite operations while avoiding
    # unrelated password rehashing in the repeated migration checks.
    monkeypatch.setattr("app.db.ensure_schema", lambda _: None)
    now = [1000.0]
    app.extensions["assistant_quota"] = AssistantQuota(clock=lambda: now[0])
    app.extensions["whatsapp_cooldown"] = PhoneCooldown(clock=lambda: now[0])
    monkeypatch.setattr(
        "app.services.whatsapp_service.get_gateway_status",
        lambda *_: {"connected": True},
    )
    monkeypatch.setattr("app.services.whatsapp_service.time.sleep", lambda *_: None)
    return app, now


def test_assistant_shares_30_message_quota_between_routes_and_expires(protected_app, monkeypatch):
    app, now = protected_app
    monkeypatch.setattr(
        "app.routes.assistant_devis_manager.handle",
        Mock(return_value=SimpleNamespace(handled=False)),
    )
    reply = Mock(return_value={"role": "assistant", "content": "Conseil solaire."})
    monkeypatch.setattr("app.routes.quick_assistant_response", reply)
    client = app.test_client()
    payload = {"messages": [{"role": "user", "content": "Bonjour"}]}
    routes = ["/api/assistant/chat", "/api/assistant/chat/stream"]
    for index in range(30):
        assert client.post(routes[index % 2], json=payload).status_code == 200
    assert reply.call_count == 30
    for route in routes:
        response = client.post(route, json=payload)
        assert response.status_code == 429
        assert response.get_json()["content"] == ASSISTANT_WAIT_MESSAGE
        assert response.headers["Retry-After"] == "600"
    assert reply.call_count == 30

    # A different client remains free to talk; arbitrary forwarding headers cannot evade the quota.
    assert client.post(
        routes[0], json=payload, environ_overrides={"REMOTE_ADDR": "192.0.2.10"}
    ).status_code == 200
    assert client.post(
        routes[0], json=payload, headers={"X-Forwarded-For": "192.0.2.11"}
    ).status_code == 429
    now[0] += 599.9
    assert client.post(routes[0], json=payload).headers["Retry-After"] == "1"
    now[0] += 0.1
    assert client.post(routes[0], json=payload).status_code == 200


def test_exhausted_assistant_quota_leaves_quote_calculations_unlimited(protected_app):
    app, _ = protected_app
    quota = app.extensions["assistant_quota"]
    for _ in range(30):
        assert quota.retry_after("127.0.0.1") == 0
    assert quota.retry_after("127.0.0.1") == 600
    client = app.test_client()
    for _ in range(2):
        response = client.post("/api/calculate", json={
            "project": "photovoltaic",
            "project_type": "photovoltaic",
            "data": {"meter_type": "numerique", "phase": "monophase",
                     "monthly_consumption_kwh": 1000},
            "contact": {"name": "Client Test", "phone": "0711111111"},
        })
        assert response.status_code == 200
        assert response.get_json()["quote_number"]


def test_assistant_window_is_sliding_and_denials_do_not_extend_it():
    now = [0.0]
    quota = AssistantQuota(clock=lambda: now[0])
    assert [quota.retry_after("client") for _ in range(15)] == [0] * 15
    now[0] = 200
    assert [quota.retry_after("client") for _ in range(15)] == [0] * 15
    assert quota.retry_after("client") == 400
    now[0] = 600
    assert [quota.retry_after("client") for _ in range(15)] == [0] * 15
    assert quota.retry_after("client") == 200


def test_trusted_proxy_uses_client_ips_for_independent_quotas(tmp_path, monkeypatch):
    app = create_app({
        "TESTING": True, "DATABASE": str(tmp_path / "proxy.db"),
        "TRUSTED_PROXY_HOPS": 1,
    })
    monkeypatch.setattr(
        "app.routes.assistant_devis_manager.handle",
        Mock(return_value=SimpleNamespace(handled=False)),
    )
    monkeypatch.setattr(
        "app.routes.quick_assistant_response",
        lambda _: {"role": "assistant", "content": "Bonjour"},
    )
    client = app.test_client()
    payload = {"messages": [{"role": "user", "content": "Bonjour"}]}
    for _ in range(30):
        assert client.post(
            "/api/assistant/chat", json=payload,
            headers={"X-Forwarded-For": "192.0.2.10"},
        ).status_code == 200
    assert client.post(
        "/api/assistant/chat", json=payload,
        headers={"X-Forwarded-For": "192.0.2.10"},
    ).status_code == 429
    assert client.post(
        "/api/assistant/chat", json=payload,
        headers={"X-Forwarded-For": "192.0.2.11"},
    ).status_code == 200


def test_guards_are_atomic_with_concurrent_requests():
    quota = AssistantQuota(clock=lambda: 1000.0)
    cooldown = PhoneCooldown(clock=lambda: 1000.0)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: quota.retry_after("192.0.2.10"), range(60)))
        pushes = list(pool.map(lambda _: cooldown.claim("0711111111"), range(60)))
    assert results.count(0) == 30
    assert sum(pushes) == 1


def test_phone_cooldown_matches_formats_and_cleans_expired_records():
    now = [0.0]
    cooldown = PhoneCooldown(clock=lambda: now[0])
    assert cooldown.claim("07 11 11 11 11")
    assert not cooldown.claim("+212711111111")
    assert not cooldown.claim("00212-711111111")
    assert cooldown.claim("0722222222")
    now[0] = 19.999
    assert not cooldown.claim("0711111111")
    now[0] = 20
    assert cooldown.claim("0711111111")
    now[0] = 80
    assert cooldown.claim("0733333333")
    assert set(cooldown._last_push) == {"212733333333"}


def _quote(number=1, phone="0711111111"):
    return {
        "client_name": "Client Test",
        "client_phone": phone,
        "admin_whatsapp": "0722222222",
        "project_type": "Pompage",
        "total_ttc": "35000 DH",
        "pdf_url": f"https://example.test/devis/{number}/pdf",
        "pdf_filename": f"Devis_{number}.pdf",
    }


def test_recalculations_keep_latest_pending_quote_without_redundant_push(
    protected_app, monkeypatch, caplog
):
    app, now = protected_app
    send = Mock(return_value=True)
    monkeypatch.setattr("app.services.whatsapp_service.send_whatsapp_document", send)
    with app.app_context(), caplog.at_level("INFO"):
        notify_quote_created(_quote())
        assert send.call_count == 2
        for number in range(2, 8):
            notify_quote_created(_quote(number, "+212 711 11 11 11"))
        assert send.call_count == 2
        pending = list_whatsapp_outbox("PENDING")
        assert len(pending) == 2
        assert all(row["filename"] == "Devis_7.pdf" for row in pending)
        assert all(row["attempts"] == 0 for row in pending)
        assert "WhatsApp throttle active for" in caplog.text
        now[0] += 19.999
        assert process_outbox()["processed"] == 0
        now[0] += 0.001
        assert process_outbox()["sent"] == 2
        assert send.call_count == 4
        assert all(call.args[2] == "Devis_7.pdf" for call in send.call_args_list[2:])
        assert list_whatsapp_outbox("PENDING") == []


def test_offline_queue_coalesces_before_first_delivery(protected_app, monkeypatch):
    app, _ = protected_app
    send = Mock(return_value=True)
    monkeypatch.setattr("app.services.whatsapp_service.send_whatsapp_document", send)
    monkeypatch.setattr(
        "app.services.whatsapp_service.get_gateway_status", lambda *_: {"connected": False}
    )
    with app.app_context():
        for number in range(1, 8):
            notify_quote_created(_quote(number))
        assert send.call_count == 0
        assert len(list_whatsapp_outbox("PENDING")) == 2
        monkeypatch.setattr(
            "app.services.whatsapp_service.get_gateway_status", lambda *_: {"connected": True}
        )
        assert process_outbox()["sent"] == 2
        assert all(call.args[2] == "Devis_7.pdf" for call in send.call_args_list)


def test_admin_queue_keeps_distinct_clients_when_coalescing_recalculations(
    protected_app, monkeypatch
):
    app, _ = protected_app
    monkeypatch.setattr(
        "app.services.whatsapp_service.get_gateway_status", lambda *_: {"connected": False}
    )
    with app.app_context():
        notify_quote_created(_quote(1))
        notify_quote_created(_quote(2, "0733333333"))
        notify_quote_created(_quote(3, "+212 711 11 11 11"))
        pending = list_whatsapp_outbox("PENDING")
        assert len(pending) == 4
        admin_items = [row for row in pending if row["phone"] == "0722222222"]
        assert len(admin_items) == 2
        assert {row["filename"] for row in admin_items} == {"Devis_2.pdf", "Devis_3.pdf"}


@pytest.mark.parametrize("succeeds", [True, False])
def test_replacing_quote_during_delivery_preserves_new_pending_payload(
    protected_app, monkeypatch, succeeds
):
    app, now = protected_app
    monkeypatch.setattr("app.services.whatsapp_service.ADMIN_PHONE", "")
    nested_results = []

    def send(*args, **kwargs):
        replacement = _quote(2)
        replacement["admin_whatsapp"] = ""
        notify_quote_created(replacement)
        nested_results.append(process_outbox())
        return succeeds

    monkeypatch.setattr("app.services.whatsapp_service.send_whatsapp_document", send)
    original = _quote()
    original["admin_whatsapp"] = ""
    with app.app_context():
        notify_quote_created(original)
        assert all(result["processed"] == 0 for result in nested_results)
        pending = list_whatsapp_outbox("PENDING")
        assert len(pending) == 1
        assert pending[0]["filename"] == "Devis_2.pdf"
        assert pending[0]["attempts"] == 0
        now[0] += 20
        resumed = Mock(return_value=True)
        monkeypatch.setattr("app.services.whatsapp_service.send_whatsapp_document", resumed)
        assert process_outbox()["sent"] == 1
        assert resumed.call_args.args[2] == "Devis_2.pdf"


def test_quote_notification_returns_while_background_delivery_is_pending(
    protected_app, monkeypatch
):
    app, _ = protected_app
    started, release, completed = Event(), Event(), Event()

    def deliver(**kwargs):
        started.set()
        release.wait(timeout=5)
        completed.set()

    monkeypatch.setattr("app.services.whatsapp_service.process_outbox", deliver)
    try:
        with app.app_context():
            notify_quote_created(_quote(), dispatch_immediately=False)
            assert started.wait(timeout=2)
            assert not completed.is_set()
            assert len(list_whatsapp_outbox("PENDING")) == 2
    finally:
        release.set()
        assert completed.wait(timeout=2)
