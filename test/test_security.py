"""
Security-focused tests for critical vulnerabilities found in the audit.
These are unit tests that don't require MongoDB/Redis running.
"""
import pytest
import secrets
import html
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import os

# =============================================
# OTP Security Tests
# =============================================

class TestOTPSecurity:
    """Test that OTP service is cryptographically secure and validates properly."""

    def test_otp_uses_secrets_module(self):
        """OTP generation must use cryptographically secure random."""
        # Verify the import is 'secrets' not 'random'
        import app.services.otp_service as otp_mod
        import inspect
        source = inspect.getsource(otp_mod)
        assert "secrets.choice" in source, "OTP must use secrets.choice, not random.choices"
        assert "random.choices" not in source, "random.choices is not cryptographically secure"

    def test_otp_no_print_statements(self):
        """No print() calls that could leak OTPs to stdout."""
        import app.services.otp_service as otp_mod
        import inspect
        source = inspect.getsource(otp_mod)
        # Allow print in comments but not in actual code
        lines = [
            line.strip() for line in source.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]
        for line in lines:
            assert not line.startswith("print("), f"Found print statement: {line}"

    def test_otp_generates_6_digits(self):
        """OTP should be exactly 6 digits."""
        from app.services.otp_service import OTPService
        service = OTPService(db=None)
        otp = service.generate_otp()
        assert len(otp) == 6
        assert otp.isdigit()

    def test_otp_generates_different_values(self):
        """OTP should not generate the same value repeatedly."""
        from app.services.otp_service import OTPService
        service = OTPService(db=None)
        otps = {service.generate_otp() for _ in range(100)}
        # With 6-digit OTPs, 100 generations should produce many unique values
        assert len(otps) > 50, "OTP generation appears non-random"

    @pytest.mark.asyncio
    async def test_otp_verify_checks_expiry(self):
        """OTP verification must reject expired OTPs."""
        from app.services.otp_service import OTPService

        # Mock DB that returns an expired OTP
        mock_db = AsyncMock()
        # First call (main query with expires_at check) returns None (expired)
        # Second call (check if OTP exists) returns the expired doc
        mock_db.find_one = AsyncMock(side_effect=[
            None,  # Main query fails (expired OTP filtered by $gt check)
            {  # Fallback query finds unused OTP
                "_id": "test_id",
                "email": "test@test.com",
                "otp": "123456",
                "type": "email_verification",
                "used": False,
                "attempts": 0,
                "expires_at": datetime.utcnow() - timedelta(minutes=1),
            },
        ])
        mock_db.update_one = AsyncMock()

        service = OTPService(db=mock_db)
        result = await service.verify_otp("test@test.com", "123456", "email_verification")
        assert result is False, "Expired OTP should not verify"

    @pytest.mark.asyncio
    async def test_otp_verify_checks_used_flag(self):
        """OTP verification must reject already-used OTPs."""
        from app.services.otp_service import OTPService

        mock_db = AsyncMock()
        # Main query (with used: False) returns None since OTP is used
        mock_db.find_one = AsyncMock(side_effect=[None, None])

        service = OTPService(db=mock_db)
        result = await service.verify_otp("test@test.com", "123456", "email_verification")
        assert result is False, "Used OTP should not verify"


# =============================================
# Order Signature Tests
# =============================================

class TestOrderSignature:
    """Test order signature verification."""

    def test_signature_requires_env_var(self):
        """ORDER_SIGNATURE_SECRET must not have a weak default."""
        import inspect
        import app.utils.order_verification as mod
        source = inspect.getsource(mod)
        assert '"smartbag123"' not in source, "Weak default secret must be removed"

    def test_signature_verification(self):
        """Signature should verify correctly with matching data."""
        with patch.dict(os.environ, {"ORDER_SIGNATURE_SECRET": "test_secret_key_12345"}):
            # Re-import to pick up new env
            import importlib
            import app.utils.order_verification as mod
            importlib.reload(mod)

            sig = mod.generate_order_signature("DRAFT_123", 99.99, "USER_001")
            assert mod.verify_order_signature("DRAFT_123", 99.99, "USER_001", sig)

    def test_signature_rejects_tampered_amount(self):
        """Signature should fail if amount is tampered."""
        with patch.dict(os.environ, {"ORDER_SIGNATURE_SECRET": "test_secret_key_12345"}):
            import importlib
            import app.utils.order_verification as mod
            importlib.reload(mod)

            sig = mod.generate_order_signature("DRAFT_123", 99.99, "USER_001")
            assert not mod.verify_order_signature("DRAFT_123", 1.00, "USER_001", sig)


# =============================================
# Email HTML Injection Tests
# =============================================

class TestEmailSecurity:
    """Test that email templates escape user input."""

    def test_escape_function_exists(self):
        """Email service must have HTML escaping."""
        from app.services.email_service import _escape
        malicious = '<script>alert("xss")</script>'
        escaped = _escape(malicious)
        assert "<script>" not in escaped
        assert "&lt;script&gt;" in escaped

    def test_email_service_not_blocking(self):
        """Email _send_email must use asyncio.to_thread, not direct smtplib."""
        import inspect
        from app.services.email_service import EmailService
        source = inspect.getsource(EmailService._send_email)
        assert "asyncio.to_thread" in source, "_send_email must use asyncio.to_thread"


# =============================================
# Input Validation Tests
# =============================================

class TestInputValidation:
    """Test input validators against injection attacks."""

    def test_nosql_injection_blocked(self):
        """MongoDB operators should be stripped from search queries."""
        from app.utils.validators import InputValidator
        malicious = '{"$gt": ""}'
        result = InputValidator.sanitize_search_query(malicious)
        assert "$gt" not in result

    def test_html_sanitization(self):
        """HTML tags should be stripped from user input."""
        from app.utils.validators import InputValidator
        malicious = '<script>alert(1)</script>Hello'
        result = InputValidator.sanitize_string(malicious)
        assert "<script>" not in result
        assert "Hello" in result

    def test_email_validation(self):
        """Email validator should reject invalid formats."""
        from app.utils.validators import InputValidator
        assert InputValidator.validate_email("user@example.com") is True
        assert InputValidator.validate_email("not-an-email") is False
        assert InputValidator.validate_email("") is False

    def test_phone_validation(self):
        """Phone validator should accept valid formats."""
        from app.utils.validators import InputValidator
        assert InputValidator.validate_phone("+1234567890") is True
        assert InputValidator.validate_phone("abc") is False


# =============================================
# Payment Validation Tests
# =============================================

class TestPaymentValidation:
    """Test payment amount validation."""

    def test_payment_amount_must_be_positive(self):
        """PaymentInitiateRequest must reject negative amounts."""
        from app.routes.payment import PaymentInitiateRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PaymentInitiateRequest(order_id="ORD001", amount=-100)

    def test_payment_amount_must_not_exceed_limit(self):
        """PaymentInitiateRequest must reject amounts over 1M."""
        from app.routes.payment import PaymentInitiateRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PaymentInitiateRequest(order_id="ORD001", amount=2000000)

    def test_payment_amount_valid(self):
        """PaymentInitiateRequest should accept valid amounts."""
        from app.routes.payment import PaymentInitiateRequest
        req = PaymentInitiateRequest(order_id="ORD001", amount=500.50)
        assert req.amount == 500.50


# =============================================
# CSP Header Tests
# =============================================

class TestSecurityHeaders:
    """Test security header configuration."""

    def test_csp_no_unsafe_inline(self):
        """CSP must not include unsafe-inline or unsafe-eval."""
        import inspect
        from app.middleware.security_headers import SecurityHeadersMiddleware
        source = inspect.getsource(SecurityHeadersMiddleware)
        assert "unsafe-inline" not in source, "CSP must not allow unsafe-inline"
        assert "unsafe-eval" not in source, "CSP must not allow unsafe-eval"


# =============================================
# Rate Limiter Tests
# =============================================

class TestRateLimiter:
    """Test rate limiter configuration."""

    def test_global_rate_limiter_not_bypassed_in_dev(self):
        """Global rate limiter should only bypass in Testing, not Development."""
        import inspect
        from app.middleware.rate_limiter import GlobalRateLimitMiddleware
        source = inspect.getsource(GlobalRateLimitMiddleware.__call__)
        assert "'Testing'" in source, "Should bypass in Testing environment"
        assert "'Development'" not in source, "Should NOT bypass in Development"


# =============================================
# Database Connection Tests
# =============================================

class TestDatabaseConnection:
    """Test database connection configuration."""

    def test_connection_pool_settings(self):
        """DB connection must configure pool size and timeouts."""
        import inspect
        import db.db_connection as mod
        source = inspect.getsource(mod)
        assert "maxPoolSize" in source, "Must configure maxPoolSize"
        assert "serverSelectionTimeoutMS" in source, "Must configure server selection timeout"
        assert "connectTimeoutMS" in source, "Must configure connect timeout"
