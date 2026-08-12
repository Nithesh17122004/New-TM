# -*- coding: utf-8 -*-
"""
Unit tests for the (real) Instamojo payment flow wired into create-order,
plus webhook/refund hardening:

  - /payments/create-order switches mock <-> real via _use_mock_mode(),
    takes the amount from the order document (never the client body),
    and surfaces Instamojo failures as HTTP errors instead of silently
    falling back to mock
  - /payments/verify only marks existing orders as paid
  - /payments/webhook validates the HMAC signature, rejects unknown
    orders, rejects amount mismatches, and is idempotent on duplicates
  - /payments/refund covers mock + real paths, including API failure
  - history still requires a valid token

Run with:  python -m pytest backend/tests -v
"""
import hashlib
import hmac
import os
import time

import jwt
import pytest

import app as flask_app_module
from api.v1 import payments


def make_token(payload: dict) -> str:
    payload = dict(payload)
    payload.setdefault('exp', int(time.time()) + 3600)
    payload.setdefault('iat', int(time.time()))
    return jwt.encode(payload, os.environ['JWT_SECRET'], algorithm='HS256')


AUTH = {'Authorization': 'Bearer ' + make_token({
    'id': 'u1', 'role': 'customer', 'phone': '9999999999', 'email': 'c@example.com'
})}


class FakeOrders:
    def __init__(self, docs):
        self.docs = {d['_id']: dict(d) for d in docs}
        self.update_count = 0

    def find_one(self, filter_, projection=None, **kwargs):
        doc = self.docs.get((filter_ or {}).get('_id'))
        if doc is None:
            return None
        if projection:
            return {k: doc.get(k) for k in projection}
        return dict(doc)

    def update_one(self, filter_, update, **kwargs):
        self.update_count += 1
        order = self.docs.get((filter_ or {}).get('_id'))
        if order is not None:
            order.update(update.get('$set', {}))


class FakeDb:
    def __init__(self, docs):
        self.orders = FakeOrders(docs)


class FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


@pytest.fixture()
def client():
    return flask_app_module.app.test_client()


@pytest.fixture(autouse=True)
def _clean_payment_config(monkeypatch):
    """Start every test with no real Instamojo credentials and no forced mode."""
    monkeypatch.delenv('PAYMENT_MOCK_MODE', raising=False)
    for attr, name in [
        ('INSTAMOJO_API_KEY', 'INSTAMOJO_API_KEY'),
        ('INSTAMOJO_AUTH_TOKEN', 'INSTAMOJO_AUTH_TOKEN'),
        ('INSTAMOJO_SALT', 'INSTAMOJO_SALT'),
        ('INSTAMOJO_WEBHOOK_SECRET', 'INSTAMOJO_WEBHOOK_SECRET'),
    ]:
        monkeypatch.setenv(name, '')
        monkeypatch.setattr(payments, attr, '')
    payments.PAYMENT_MOCK_MODE = False
    yield


@pytest.fixture()
def fake_db(monkeypatch):
    installed = []

    def _make(docs=None):
        db = FakeDb(docs or [])
        flask_app_module.app.extensions['mongo_db'] = db
        installed.append(db)
        return db

    yield _make
    flask_app_module.app.extensions['mongo_db'] = None


def _enable_real_keys(monkeypatch):
    monkeypatch.setattr(payments, 'INSTAMOJO_API_KEY', 'test-api-key')
    monkeypatch.setattr(payments, 'INSTAMOJO_AUTH_TOKEN', 'test-auth-token')
    monkeypatch.setattr(payments, 'INSTAMOJO_SALT', 'test-salt')


def _signed_webhook(data: dict, salt: str = 'test-salt') -> dict:
    fields = [
        'payment_id', 'payment_request_id', 'buyer_name', 'buyer_phone',
        'buyer_email', 'currency', 'amount', 'purpose', 'status',
    ]
    mac_string = '|'.join(str(data.get(f, '')) for f in fields)
    signed = dict(data)
    signed['mac'] = hmac.new(salt.encode(), mac_string.encode(), hashlib.sha1).hexdigest()
    return signed


# --------------------------------------------------------------------------
# create-order: mock <-> real switching
# --------------------------------------------------------------------------

def test_create_order_returns_mock_by_default(client):
    r = client.post('/api/v1/payments/create-order',
                    json={'order_id': 'TM-1', 'amount': 100}, headers=AUTH)
    assert r.status_code == 200
    d = r.get_json()['data']
    assert d['mock_mode'] is True
    assert d['payment_request_id'].startswith('mock_pr_')


def test_create_order_forced_mock_even_with_keys(client, monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '1')
    _enable_real_keys(monkeypatch)
    r = client.post('/api/v1/payments/create-order',
                    json={'order_id': 'TM-1', 'amount': 100}, headers=AUTH)
    assert r.status_code == 200
    assert r.get_json()['data']['mock_mode'] is True


def test_create_order_forced_real_without_keys_fails_loudly(client, monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '0')
    r = client.post('/api/v1/payments/create-order',
                    json={'order_id': 'TM-1', 'amount': 100}, headers=AUTH)
    assert r.status_code == 502


def test_create_order_real_calls_instamojo(client, monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '0')
    _enable_real_keys(monkeypatch)
    calls = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        calls['url'] = url
        calls['headers'] = headers
        calls['data'] = data
        return FakeResp(201, {
            'success': True,
            'payment_request': {
                'id': 'pr_live_1234', 'longurl': 'https://pay.example/x',
                'shorturl': 'https://s.example/y', 'status': 'Pending',
            },
        })

    monkeypatch.setattr(payments.req, 'post', fake_post)
    r = client.post('/api/v1/payments/create-order',
                    json={'order_id': 'TM-1', 'amount': 100}, headers=AUTH)
    assert r.status_code == 200
    d = r.get_json()['data']
    assert d['mock_mode'] is False
    assert d['payment_request_id'] == 'pr_live_1234'
    assert d['longurl'] == 'https://pay.example/x'
    assert 'payment-requests' in calls['url']
    assert calls['data']['amount'] == '100.00'
    assert calls['headers']['X-Api-Key'] == 'test-api-key'


def test_create_order_real_instamojo_failure_returns_502(client, monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '0')
    _enable_real_keys(monkeypatch)
    monkeypatch.setattr(
        payments.req, 'post',
        lambda *a, **k: FakeResp(500, {'success': False, 'message': 'Bad credentials'}),
    )
    r = client.post('/api/v1/payments/create-order',
                    json={'order_id': 'TM-1', 'amount': 100}, headers=AUTH)
    assert r.status_code == 502


def test_create_order_rejects_unknown_order(client, fake_db):
    fake_db([])
    r = client.post('/api/v1/payments/create-order',
                    json={'order_id': 'TM-NOPE', 'amount': 100}, headers=AUTH)
    assert r.status_code == 404


def test_create_order_uses_server_side_amount(client, fake_db, monkeypatch):
    fake_db([{'_id': 'TM-5', 'total': 250.0, 'customer_phone': '9999999999'}])
    r = client.post('/api/v1/payments/create-order',
                    json={'order_id': 'TM-5', 'amount': 1}, headers=AUTH)
    assert r.status_code == 200
    assert r.get_json()['data']['amount'] == 250.0


def test_create_order_missing_order_id(client):
    r = client.post('/api/v1/payments/create-order', json={'amount': 100}, headers=AUTH)
    assert r.status_code == 400


def test_create_order_requires_auth(client):
    r = client.post('/api/v1/payments/create-order', json={'order_id': 'TM-1', 'amount': 10})
    assert r.status_code == 401


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def test_verify_mock_marks_paid(client):
    r = client.post('/api/v1/payments/verify', json={
        'order_id': 'TM-1', 'payment_request_id': 'mock_pr_x',
        'payment_id': 'pay_mock_1', 'mock_mode': True, 'status': 'paid',
    }, headers=AUTH)
    assert r.status_code == 200
    assert r.get_json()['data']['status'] == 'paid'


def test_verify_mock_rejects_unknown_order(client, fake_db):
    fake_db([])
    r = client.post('/api/v1/payments/verify', json={
        'order_id': 'TM-NOPE', 'payment_request_id': 'mock_pr_x', 'mock_mode': True,
    }, headers=AUTH)
    assert r.status_code == 404


def test_verify_requires_auth(client):
    r = client.post('/api/v1/payments/verify', json={'order_id': 'TM-1'})
    assert r.status_code == 401


# --------------------------------------------------------------------------
# webhook
# --------------------------------------------------------------------------

@pytest.fixture()
def webhook_salt(monkeypatch):
    """Install the salt the test webhook payloads are signed with."""
    monkeypatch.setattr(payments, 'INSTAMOJO_SALT', 'test-salt')


def test_webhook_rejects_invalid_signature(client):
    r = client.post('/api/v1/payments/webhook', json={
        'payment_id': 'p1', 'status': 'Credit', 'amount': '100.00', 'mac': 'wrong',
    })
    assert r.status_code == 400


def test_webhook_valid_credit_marks_order_paid(client, fake_db, webhook_salt):
    db = fake_db([{'_id': 'TM-7', 'total': 150.0, 'payment_status': 'pending'}])
    data = _signed_webhook({
        'payment_id': 'pay_7', 'payment_request_id': 'pr_7', 'buyer_name': 'A',
        'buyer_phone': '9999999999', 'buyer_email': 'a@b.c', 'currency': 'INR',
        'amount': '150.00', 'purpose': 'Thooku Madurai Order TM-7', 'status': 'Credit',
    })
    r = client.post('/api/v1/payments/webhook', data=data)
    assert r.status_code == 200
    assert db.orders.docs['TM-7']['payment_status'] == 'paid'
    assert db.orders.docs['TM-7']['instamojo_payment_id'] == 'pay_7'


def test_webhook_rejects_amount_mismatch(client, fake_db, webhook_salt):
    db = fake_db([{'_id': 'TM-8', 'total': 150.0, 'payment_status': 'pending'}])
    data = _signed_webhook({
        'payment_id': 'pay_8', 'payment_request_id': 'pr_8', 'buyer_name': 'A',
        'buyer_phone': '9999999999', 'buyer_email': '', 'currency': 'INR',
        'amount': '1500.00', 'purpose': 'Thooku Madurai Order TM-8', 'status': 'Credit',
    })
    r = client.post('/api/v1/payments/webhook', data=data)
    assert r.status_code == 400
    assert db.orders.docs['TM-8']['payment_status'] == 'pending'


def test_webhook_duplicate_is_idempotent(client, fake_db, webhook_salt):
    db = fake_db([{
        '_id': 'TM-9', 'total': 100.0, 'payment_status': 'paid',
        'instamojo_payment_id': 'pay_9',
    }])
    data = _signed_webhook({
        'payment_id': 'pay_9', 'payment_request_id': 'pr_9', 'buyer_name': 'A',
        'buyer_phone': '9999999999', 'buyer_email': '', 'currency': 'INR',
        'amount': '100.00', 'purpose': 'Thooku Madurai Order TM-9', 'status': 'Credit',
    })
    before = db.orders.update_count
    r = client.post('/api/v1/payments/webhook', data=data)
    assert r.status_code == 200
    assert db.orders.update_count == before  # never re-processed


def test_webhook_rejects_unknown_order(client, fake_db, webhook_salt):
    fake_db([])
    data = _signed_webhook({
        'payment_id': 'pay_x', 'payment_request_id': 'pr_x', 'buyer_name': 'A',
        'buyer_phone': '9999999999', 'buyer_email': '', 'currency': 'INR',
        'amount': '50.00', 'purpose': 'Thooku Madurai Order TM-999', 'status': 'Credit',
    })
    r = client.post('/api/v1/payments/webhook', data=data)
    assert r.status_code == 400


def test_webhook_failed_status_marks_order_failed(client, fake_db, webhook_salt):
    db = fake_db([{'_id': 'TM-10', 'total': 50.0, 'payment_status': 'pending'}])
    data = _signed_webhook({
        'payment_id': 'pay_10', 'payment_request_id': 'pr_10', 'buyer_name': 'A',
        'buyer_phone': '9999999999', 'buyer_email': '', 'currency': 'INR',
        'amount': '50.00', 'purpose': 'Thooku Madurai Order TM-10', 'status': 'Failed',
    })
    r = client.post('/api/v1/payments/webhook', data=data)
    assert r.status_code == 200
    assert db.orders.docs['TM-10']['payment_status'] == 'failed'


# --------------------------------------------------------------------------
# refund
# --------------------------------------------------------------------------

def test_refund_mock_path(client):
    r = client.post('/api/v1/payments/refund',
                    json={'payment_id': 'pay_mock_xyz', 'amount': 100}, headers=AUTH)
    assert r.status_code == 200
    body = r.get_json()
    assert body['success'] is True
    assert body['data']['refund_id'].startswith('refund_mock_')


def test_refund_real_success(client, monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '0')
    _enable_real_keys(monkeypatch)
    calls = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        calls['url'] = url
        calls['data'] = data
        return FakeResp(201, {'refund': {'id': 'RF-123'}})

    monkeypatch.setattr(payments.req, 'post', fake_post)
    r = client.post('/api/v1/payments/refund',
                    json={'payment_id': 'pay_real_1', 'amount': 100, 'reason': 'test'},
                    headers=AUTH)
    assert r.status_code == 200
    assert r.get_json()['data']['refund_id'] == 'RF-123'
    assert 'refunds' in calls['url']


def test_refund_real_api_failure_returns_500(client, monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '0')
    _enable_real_keys(monkeypatch)

    def boom(*a, **k):
        raise Exception('Instamojo unreachable')

    monkeypatch.setattr(payments.req, 'post', boom)
    r = client.post('/api/v1/payments/refund',
                    json={'payment_id': 'pay_real_2', 'amount': 100}, headers=AUTH)
    assert r.status_code == 500


def test_refund_requires_auth(client):
    r = client.post('/api/v1/payments/refund', json={'payment_id': 'p1', 'amount': 10})
    assert r.status_code == 401


# --------------------------------------------------------------------------
# history
# --------------------------------------------------------------------------

def test_payment_history_requires_auth(client):
    r = client.get('/api/v1/payments/history')
    assert r.status_code == 401
