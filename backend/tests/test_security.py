# -*- coding: utf-8 -*-
"""
Unit tests for the security hardening:

  - app boots and serves /health with the required env vars set
  - admin fallback requires FALLBACK_ADMIN_EMAIL / FALLBACK_ADMIN_PASSWORD
    (no hardcoded credentials) and rejects the old hardcoded pair
  - /my-orders requires a JWT and derives the phone from it (never ?phone=)
  - riders can only report their own location
  - call push endpoints (call-rider / call-customer / call-declined) reject
    callers who are not a participant of the order
  - payment mock mode is env-driven (mock only while no real keys are set)
  - JWT_SECRET fails fast at startup when unset

Run with:  python -m pytest backend/tests -v
"""
import importlib
import os
import time

import jwt
import pytest

import app as flask_app_module
from api.v1 import payments
from services import jwt_config


def make_token(payload: dict) -> str:
    payload = dict(payload)
    payload.setdefault('exp', int(time.time()) + 3600)
    payload.setdefault('iat', int(time.time()))
    return jwt.encode(payload, os.environ['JWT_SECRET'], algorithm='HS256')


class FakeOrders:
    def find(self, *a, **k):
        class Cursor:
            def sort(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

            def __iter__(self):
                return iter([])
        return Cursor()

    def find_one(self, *a, **k):
        return None


class FakeCustomers:
    def __init__(self, phone=None):
        self.phone = phone

    def find_one(self, *a, **k):
        return {'phone': self.phone} if self.phone else None


class FakeRiders:
    def update_one(self, *a, **k):
        pass


class FakeDb:
    def __init__(self, customer_phone=None):
        self.orders = FakeOrders()
        self.customers = FakeCustomers(customer_phone)
        self.delivery_partners = FakeRiders()


@pytest.fixture()
def client():
    return flask_app_module.app.test_client()


@pytest.fixture()
def fake_db(monkeypatch):
    db = FakeDb()
    flask_app_module.app.extensions['mongo_db'] = db
    yield db
    flask_app_module.app.extensions['mongo_db'] = None


# --------------------------------------------------------------------------
# App boots with required env vars
# --------------------------------------------------------------------------

def test_health_endpoint(client):
    r = client.get('/health')
    assert r.status_code == 200
    body = r.get_json()
    assert body['data']['service'] == 'Thooku Madurai API'
    assert 'database' in body['data']


# --------------------------------------------------------------------------
# Admin fallback: env-only, never hardcoded
# --------------------------------------------------------------------------

def test_admin_fallback_rejects_old_hardcoded_creds(client, monkeypatch):
    monkeypatch.delenv('FALLBACK_ADMIN_EMAIL', raising=False)
    monkeypatch.delenv('FALLBACK_ADMIN_PASSWORD', raising=False)
    r = client.post('/api/v1/auth/admin-login', json={
        'email': 'admin@thooku.com', 'password': 'admin123'
    })
    assert r.status_code == 401


def test_admin_fallback_works_with_env_creds(client, monkeypatch):
    monkeypatch.setenv('FALLBACK_ADMIN_EMAIL', 'recovery@thookumadurai.in')
    monkeypatch.setenv('FALLBACK_ADMIN_PASSWORD', 'RecoverySecret123!')
    r = client.post('/api/v1/auth/admin-login', json={
        'email': 'recovery@thookumadurai.in', 'password': 'RecoverySecret123!'
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body['success'] is True
    assert body['user']['role'] == 'superadmin'
    assert body['token']


# --------------------------------------------------------------------------
# /my-orders: authenticated, phone from JWT
# --------------------------------------------------------------------------

def test_my_orders_requires_token(client):
    r = client.get('/api/v1/orders/my-orders?phone=9876543210')
    assert r.status_code == 401


def test_my_orders_rejects_invalid_token(client):
    r = client.get(
        '/api/v1/orders/my-orders',
        headers={'Authorization': 'Bearer not-a-jwt'},
    )
    assert r.status_code == 401


def test_my_orders_uses_phone_from_jwt(client, fake_db):
    token = make_token({'role': 'customer', 'id': 'c1', 'phone': '9876543210'})
    r = client.get(
        '/api/v1/orders/my-orders?phone=1111111111',  # query param must be ignored
        headers={'Authorization': f'Bearer {token}'},
    )
    assert r.status_code == 200
    assert r.get_json()['data'] == []


def test_my_orders_google_login_email_fallback(client, monkeypatch):
    db = FakeDb(customer_phone='9876543210')
    flask_app_module.app.extensions['mongo_db'] = db
    token = make_token({'role': 'customer', 'id': 'c1', 'email': 'user@gmail.com'})
    r = client.get(
        '/api/v1/orders/my-orders',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert r.status_code == 200
    flask_app_module.app.extensions['mongo_db'] = None


# --------------------------------------------------------------------------
# Rider location: no spoofing
# --------------------------------------------------------------------------

def test_rider_location_forbidden_for_customer(client):
    token = make_token({'role': 'customer', 'id': 'c1', 'phone': '9876543210'})
    r = client.post(
        '/api/v1/tracking/rider/rider_1/location',
        json={'lat': 9.9, 'lng': 78.1},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert r.status_code == 403


def test_rider_location_forbidden_for_other_rider(client):
    token = make_token({'role': 'rider', 'user_id': 'rider_2', 'rider_id': 'rider_2'})
    r = client.post(
        '/api/v1/tracking/rider/rider_1/location',
        json={'lat': 9.9, 'lng': 78.1},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert r.status_code == 403


def test_rider_location_allowed_for_self(client, fake_db):
    token = make_token({'role': 'rider', 'user_id': 'rider_1', 'rider_id': 'rider_1'})
    r = client.post(
        '/api/v1/tracking/rider/rider_1/location',
        json={'lat': 9.9, 'lng': 78.1, 'order_id': 'o1'},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert r.status_code == 200
    assert r.get_json()['success'] is True


# --------------------------------------------------------------------------
# Call push endpoints: participant-only
# --------------------------------------------------------------------------

def test_call_declined_requires_token(client):
    r = client.post('/api/v1/push/call-declined', json={'callId': 'x', 'orderId': 'o1'})
    assert r.status_code == 401


def test_call_declined_forbidden_for_non_participant(client, fake_db):
    token = make_token({'role': 'customer', 'id': 'c1', 'phone': '9999999999'})
    r = client.post(
        '/api/v1/push/call-declined',
        json={'callId': 'x', 'orderId': 'o1'},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert r.status_code == 403


def test_call_rider_forbidden_for_non_participant(client, fake_db):
    token = make_token({'role': 'customer', 'id': 'c1', 'phone': '9999999999'})
    r = client.post(
        '/api/v1/push/call-rider',
        json={'riderId': 'r1', 'callId': 'x', 'orderId': 'o1', 'callerName': 'X'},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Payments: mock mode is env-driven
# --------------------------------------------------------------------------

def test_payment_mock_defaults_to_mock_without_keys(monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '')
    payments.RAZORPAY_KEY_ID = ''
    payments.RAZORPAY_KEY_SECRET = ''
    assert payments._use_mock_mode() is True


def test_payment_mock_disabled_when_keys_present(monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '')
    payments.RAZORPAY_KEY_ID = 'k'
    payments.RAZORPAY_KEY_SECRET = 's'
    assert payments._use_mock_mode() is False


def test_payment_mock_forced_on(monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '1')
    payments.RAZORPAY_KEY_ID = 'k'
    payments.RAZORPAY_KEY_SECRET = 's'
    assert payments._use_mock_mode() is True


def test_payment_mock_forced_off_even_without_keys(monkeypatch):
    monkeypatch.setenv('PAYMENT_MOCK_MODE', '0')
    payments.RAZORPAY_KEY_ID = ''
    payments.RAZORPAY_KEY_SECRET = ''
    assert payments._use_mock_mode() is False


# --------------------------------------------------------------------------
# JWT_SECRET fails fast when unset
# --------------------------------------------------------------------------

def test_jwt_config_fails_fast_when_unset(monkeypatch):
    saved = os.environ.get('JWT_SECRET', '')
    monkeypatch.delenv('JWT_SECRET', raising=False)
    with pytest.raises(RuntimeError):
        importlib.reload(jwt_config)
    # Restore for any later imports.
    monkeypatch.setenv('JWT_SECRET', saved)
    importlib.reload(jwt_config)
    assert jwt_config.JWT_SECRET == saved
