# -*- coding: utf-8 -*-
"""
Unit tests for the (real) Razorpay payment flow wired into create-order,
plus webhook/refund hardening:

  - /payments/create-order switches mock <-> real via _use_mock_mode(),
    takes the amount from the order document (never the client body),
    persists the Razorpay order id mapping, and surfaces Razorpay API
    failures as HTTP errors instead of silently falling back to mock
  - /payments/verify only marks existing orders as paid and only after a
    valid Razorpay signature (order_id|payment_id, HMAC-SHA256)
  - /payments/webhook validates the raw-body signature, rejects unknown
    orders, rejects amount mismatches, and is idempotent on duplicates
  - /payments/refund covers mock + real paths, including API failure
  - history still requires a valid token

Run with:  python -m pytest backend/tests -v
"""
import hashlib
import hmac
import json
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

TEST_KEY_ID = 'rzp_test_key123'
TEST_KEY_SECRET = 'test-key-secret'
TEST_WEBHOOK_SECRET = 'test-webhook-secret'


class FakeOrders:
    def __init__(self, docs):
        self.docs = {d['_id']: dict(d) for d in docs}
        self.update_count = 0

    def find_one(self, filter_, projection=None, **kwargs):
        filter_ = filter_ or {}
        doc = self.docs.get(filter_.get('_id'))
        if doc is None:
            for key, value in filter_.items():
                doc = next((d for d in self.docs.values() if d.get(key) == value), None)
                if doc is not None:
                    break
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
    """Start every test with no real Razorpay credentials and no forced mode."""
    monkeypatch.delenv('PAYMENT_MOCK_MODE', raising=False)
    for attr in ('RAZORPAY_KEY_ID', 'RAZORPAY_KEY_SECRET', 'RAZORPAY_WEBHOOK_SECRET'):
        monkeypatch.setenv(attr, '')
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
    monkeypatch.setattr(payments, 'RAZORPAY_KEY_ID', TEST_KEY_ID)
    monkeypatch.setattr(payments, 'RAZORPAY_KEY_SECRET', TEST_KEY_SECRET)
    monkeypatch.setattr(payments, 'RAZORPAY_WEBHOOK_SECRET', TEST_WEBHOOK_SECRET)


def _payment_signature(order_id: str, payment_id: str) -> str:
    return hmac.new(
        TEST_KEY_SECRET.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _webhook_signature(raw_body: bytes) -> str:
    return hmac.new(
        TEST_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()


def _payment_body(order_id: str, rzp_order_id: str, amount_paise: int,
                  event: str = 'payment.captured', status: str = 'captured') -> dict:
    return {
        'event': event,
        'payload': {
            'payment': {
                'entity': {
                    'id': f'pay_{rzp_order_id}',
                    'order_id': rzp_order_id,
                    'amount': amount_paise,
                    'currency': 'INR',
                    'status': status,
                    'notes': {'order_id': order_id},
                }
            }
        }
    }


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


def test_create_order_real_calls_razorpay(client, monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '0')
    _enable_real_keys(monkeypatch)
    calls = {}

    def fake_post(url, auth=None, data=None, timeout=None):
        calls['url'] = url
        calls['auth'] = auth
        calls['data'] = data
        return FakeResp(200, {
            'id': 'order_O1', 'amount': 10000, 'currency': 'INR',
            'status': 'created', 'receipt': 'TM-1',
        })

    monkeypatch.setattr(payments.req, 'post', fake_post)
    r = client.post('/api/v1/payments/create-order',
                    json={'order_id': 'TM-1', 'amount': 100}, headers=AUTH)
    assert r.status_code == 200
    d = r.get_json()['data']
    assert d['mock_mode'] is False
    assert d['razorpay_order_id'] == 'order_O1'
    assert d['razorpay_key_id'] == TEST_KEY_ID
    assert d['amount_paise'] == 10000
    assert calls['url'] == 'https://api.razorpay.com/v1/orders'
    assert calls['auth'] == (TEST_KEY_ID, TEST_KEY_SECRET)
    assert calls['data']['amount'] == '10000'


def test_create_order_real_persists_razorpay_order_mapping(client, fake_db, monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '0')
    _enable_real_keys(monkeypatch)
    db = fake_db([{'_id': 'TM-4', 'total': 99.0, 'customer_phone': '9999999999'}])
    monkeypatch.setattr(
        payments.req, 'post',
        lambda *a, **k: FakeResp(200, {'id': 'order_O4', 'amount': 9900, 'currency': 'INR', 'status': 'created'}),
    )
    r = client.post('/api/v1/payments/create-order',
                    json={'order_id': 'TM-4', 'amount': 99}, headers=AUTH)
    assert r.status_code == 200
    assert db.orders.docs['TM-4']['razorpay_order_id'] == 'order_O4'


def test_create_order_real_razorpay_failure_returns_502(client, monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '0')
    _enable_real_keys(monkeypatch)
    monkeypatch.setattr(
        payments.req, 'post',
        lambda *a, **k: FakeResp(400, {'error': {'description': 'Bad credentials'}}),
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
# verify (Razorpay Checkout signature)
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


def test_verify_real_accepts_valid_signature_marks_paid(client, fake_db, monkeypatch):
    _enable_real_keys(monkeypatch)
    db = fake_db([{'_id': 'TM-6', 'total': 120.0, 'payment_status': 'pending'}])
    sig = _payment_signature('order_O6', 'pay_P6')
    r = client.post('/api/v1/payments/verify', json={
        'order_id': 'TM-6',
        'razorpay_order_id': 'order_O6',
        'razorpay_payment_id': 'pay_P6',
        'razorpay_signature': sig,
    }, headers=AUTH)
    assert r.status_code == 200
    assert db.orders.docs['TM-6']['payment_status'] == 'paid'
    assert db.orders.docs['TM-6']['razorpay_payment_id'] == 'pay_P6'


def test_verify_real_rejects_invalid_signature(client, fake_db, monkeypatch):
    _enable_real_keys(monkeypatch)
    db = fake_db([{'_id': 'TM-6', 'total': 120.0, 'payment_status': 'pending'}])
    r = client.post('/api/v1/payments/verify', json={
        'order_id': 'TM-6',
        'razorpay_order_id': 'order_O6',
        'razorpay_payment_id': 'pay_P6',
        'razorpay_signature': 'deadbeef',
    }, headers=AUTH)
    assert r.status_code == 400
    assert db.orders.docs['TM-6']['payment_status'] == 'pending'


def test_verify_real_requires_signature_fields(client, monkeypatch):
    _enable_real_keys(monkeypatch)
    r = client.post('/api/v1/payments/verify', json={
        'order_id': 'TM-6',
        'razorpay_order_id': 'order_O6',
    }, headers=AUTH)
    assert r.status_code == 400


def test_verify_requires_auth(client):
    r = client.post('/api/v1/payments/verify', json={'order_id': 'TM-1'})
    assert r.status_code == 401


# --------------------------------------------------------------------------
# webhook
# --------------------------------------------------------------------------

def _post_webhook(client, body: dict, secret: str = TEST_WEBHOOK_SECRET,
                  tampered: bool = False):
    raw = json.dumps(body).encode()
    if tampered:
        raw = raw + b'x'
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        '/api/v1/payments/webhook',
        data=raw,
        content_type='application/json',
        headers={'X-Razorpay-Signature': sig},
    )


def test_webhook_rejects_invalid_signature(client, _clean_payment_config):
    r = _post_webhook(client, _payment_body('TM-7', 'order_O7', 15000), tampered=True)
    assert r.status_code == 400


def test_webhook_valid_credit_marks_order_paid(client, fake_db, monkeypatch):
    _enable_real_keys(monkeypatch)
    db = fake_db([{
        '_id': 'TM-7', 'total': 150.0, 'payment_status': 'pending',
        'razorpay_order_id': 'order_O7',
    }])
    body = _payment_body('TM-7', 'order_O7', 15000)
    r = _post_webhook(client, body)
    assert r.status_code == 200
    assert db.orders.docs['TM-7']['payment_status'] == 'paid'
    assert db.orders.docs['TM-7']['razorpay_payment_id'] == f'pay_order_O7'


def test_webhook_rejects_amount_mismatch(client, fake_db, monkeypatch):
    _enable_real_keys(monkeypatch)
    db = fake_db([{
        '_id': 'TM-8', 'total': 150.0, 'payment_status': 'pending',
        'razorpay_order_id': 'order_O8',
    }])
    body = _payment_body('TM-8', 'order_O8', 150000)  # ₹1,500 paid vs ₹150 order
    r = _post_webhook(client, body)
    assert r.status_code == 400
    assert db.orders.docs['TM-8']['payment_status'] == 'pending'


def test_webhook_duplicate_is_idempotent(client, fake_db, monkeypatch):
    _enable_real_keys(monkeypatch)
    db = fake_db([{
        '_id': 'TM-9', 'total': 100.0, 'payment_status': 'paid',
        'razorpay_payment_id': 'pay_order_O9', 'razorpay_order_id': 'order_O9',
    }])
    body = _payment_body('TM-9', 'order_O9', 10000)
    before = db.orders.update_count
    r = _post_webhook(client, body)
    assert r.status_code == 200
    assert db.orders.update_count == before  # never re-processed


def test_webhook_rejects_unknown_order(client, fake_db, monkeypatch):
    _enable_real_keys(monkeypatch)
    fake_db([])
    body = _payment_body('TM-999', 'order_O999', 5000)
    r = _post_webhook(client, body)
    assert r.status_code == 400


def test_webhook_failed_event_marks_order_failed(client, fake_db, monkeypatch):
    _enable_real_keys(monkeypatch)
    db = fake_db([{
        '_id': 'TM-10', 'total': 50.0, 'payment_status': 'pending',
        'razorpay_order_id': 'order_O10',
    }])
    body = _payment_body('TM-10', 'order_O10', 5000,
                         event='payment.failed', status='failed')
    r = _post_webhook(client, body)
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

    def fake_post(url, auth=None, data=None, timeout=None):
        calls['url'] = url
        calls['auth'] = auth
        calls['data'] = data
        return FakeResp(200, {'id': 'rfnd_R1', 'status': 'processed'})

    monkeypatch.setattr(payments.req, 'post', fake_post)
    r = client.post('/api/v1/payments/refund',
                    json={'payment_id': 'pay_real_1', 'amount': 100, 'reason': 'test'},
                    headers=AUTH)
    assert r.status_code == 200
    assert r.get_json()['data']['refund_id'] == 'rfnd_R1'
    assert calls['url'] == 'https://api.razorpay.com/v1/payments/pay_real_1/refund'
    assert calls['auth'] == (TEST_KEY_ID, TEST_KEY_SECRET)
    assert calls['data']['amount'] == '10000'


def test_refund_real_api_failure_returns_500(client, monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '0')
    _enable_real_keys(monkeypatch)

    def boom(*a, **k):
        raise Exception('Razorpay unreachable')

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