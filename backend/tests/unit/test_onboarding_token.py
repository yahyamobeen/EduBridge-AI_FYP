"""
Unit tests for onboarding token scoping.

Tests that onboarding-scoped access tokens (type="onboarding") are rejected
by the default decode_access_token() call, which expects type="access".

This is the enforcement mechanism for tdd.md §3.1: the email/verify endpoint
issues an onboarding token that cannot call /auth/me or any business endpoint.
"""

from uuid import uuid4

import pytest

from app.auth.security import (
    create_access_token,
    create_onboarding_token,
    decode_access_token,
)


class TestOnboardingToken:
    def test_roundtrip_with_expected_type(self):
        user_id = uuid4()
        token, expires_in = create_onboarding_token(user_id)
        decoded = decode_access_token(token, expected_type="onboarding")
        assert decoded == user_id
        assert expires_in > 0

    def test_rejected_by_default_decode(self):
        """Default decode expects type='access', so onboarding tokens fail."""
        user_id = uuid4()
        token, _ = create_onboarding_token(user_id)
        with pytest.raises(ValueError, match="not an access token"):
            decode_access_token(token)

    def test_access_token_rejected_by_onboarding_decode(self):
        """Access tokens (type='access') are rejected when expecting onboarding."""
        user_id = uuid4()
        token, _ = create_access_token(user_id)
        with pytest.raises(ValueError, match="not an access token"):
            decode_access_token(token, expected_type="onboarding")

    def test_onboarding_token_has_correct_type(self):
        """Verify the token payload has type='onboarding'."""
        user_id = uuid4()
        token, _ = create_onboarding_token(user_id)
        # Decode with the correct expected type should work
        decoded = decode_access_token(token, expected_type="onboarding")
        assert decoded == user_id

    def test_different_token_types_are_distinct(self):
        """Two tokens for the same user with different types are not interchangeable."""
        user_id = uuid4()
        access_token, _ = create_access_token(user_id)
        onboarding_token, _ = create_onboarding_token(user_id)

        # Access token works with default decode
        assert decode_access_token(access_token) == user_id

        # Onboarding token fails with default decode
        with pytest.raises(ValueError):
            decode_access_token(onboarding_token)

        # Onboarding token works with onboarding decode
        assert decode_access_token(onboarding_token, expected_type="onboarding") == user_id

        # Access token fails with onboarding decode
        with pytest.raises(ValueError):
            decode_access_token(access_token, expected_type="onboarding")
