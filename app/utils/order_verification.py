import os
import hmac
import hashlib

ORDER_SIGNATURE_SECRET = os.getenv("ORDER_SIGNATURE_SECRET")
if not ORDER_SIGNATURE_SECRET:
    raise RuntimeError("ORDER_SIGNATURE_SECRET environment variable is required")

def generate_order_signature(draft_order_id: str, total_amount: float, user_id: str) -> str:
    """Generate HMAC signature for order verification"""
    message = f"{draft_order_id}:{total_amount}:{user_id}"
    signature = hmac.new(
        ORDER_SIGNATURE_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature

def verify_order_signature(draft_order_id: str, total_amount: float, user_id: str, signature: str) -> bool:
    """Verify order signature"""
    expected = generate_order_signature(draft_order_id, total_amount, user_id)
    return hmac.compare_digest(expected, signature)