import base64
import hashlib
import hmac
import time

import pytest

from app.core.security import WebhookSignatureError, verify_detectif_webhook_signature


def make_signature(secret: str, message_id: str, timestamp: str, body: bytes) -> str:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = f"{message_id}.{timestamp}.".encode() + body
    signature = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return f"v1,{signature}"


def test_valid_detectif_signature_passes():
    secret = "whsec_" + base64.b64encode(b"test-webhook-secret").decode()
    body = b'{"type":"webhook.test"}'
    timestamp = str(int(time.time()))
    message_id = "msg_test_123"
    headers = {
        "webhook-id": message_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": make_signature(secret, message_id, timestamp, body),
    }
    verify_detectif_webhook_signature(secret=secret, headers=headers, raw_body=body)


def test_tampered_body_is_rejected():
    secret = "whsec_" + base64.b64encode(b"test-webhook-secret").decode()
    original = b'{"type":"webhook.test"}'
    timestamp = str(int(time.time()))
    message_id = "msg_test_123"
    headers = {
        "webhook-id": message_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": make_signature(secret, message_id, timestamp, original),
    }
    with pytest.raises(WebhookSignatureError):
        verify_detectif_webhook_signature(secret=secret, headers=headers, raw_body=b'{"type":"tampered"}')


def test_stale_timestamp_is_rejected():
    secret = "whsec_" + base64.b64encode(b"test-webhook-secret").decode()
    body = b'{"type":"webhook.test"}'
    timestamp = str(int(time.time()) - 600)
    message_id = "msg_test_123"
    headers = {
        "webhook-id": message_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": make_signature(secret, message_id, timestamp, body),
    }
    with pytest.raises(WebhookSignatureError):
        verify_detectif_webhook_signature(secret=secret, headers=headers, raw_body=body)
