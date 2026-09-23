"""Google sign-in, restricted to one email domain.

The browser gets a Google ID token from Google Identity Services (the
"Sign in with Google" button on login.html) and posts it to the server.
This module verifies that token's signature, audience, and expiry against
Google's public keys, then checks that the account belongs to the allowed
Google Workspace domain. Only then does the server start a session — the
domain check never trusts anything the browser claims on its own.
"""
import logging
import os

from dotenv import load_dotenv
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

load_dotenv()

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
ALLOWED_DOMAIN = os.environ.get("ALLOWED_EMAIL_DOMAIN", "flame.edu.in").strip().lower()

_default_logger = logging.getLogger(__name__)


class SignInError(Exception):
    """A sign-in failure with a user-facing message and HTTP status."""

    def __init__(self, message, status=401):
        super().__init__(message)
        self.status = status


def verify_google_credential(credential, logger=None):
    """Verify a Google ID token and return the signed-in user as a dict
    (email, name, picture). Raises SignInError on any failure."""
    log = logger or _default_logger
    if not GOOGLE_CLIENT_ID:
        raise SignInError("Google sign-in isn't configured on this server (GOOGLE_CLIENT_ID is not set).", 500)
    if not credential:
        raise SignInError("No Google sign-in credential was received. Please try again.")

    try:
        claims = id_token.verify_oauth2_token(credential, google_requests.Request(), GOOGLE_CLIENT_ID)
    except ValueError as exc:
        log.warning("rejected google credential: %s", exc)
        raise SignInError("Google sign-in couldn't be verified. Please try again.") from exc

    return user_from_claims(claims)


def user_from_claims(claims):
    """Apply the domain rules to verified token claims. Split out from
    verify_google_credential so the rules can be tested without a real token.

    `hd` (hosted domain) is only present for Google Workspace accounts, so
    requiring it to match — and the email to be verified and end in the same
    domain — rejects personal Gmail accounts and every other organization."""
    email = (claims.get("email") or "").strip().lower()
    hosted_domain = (claims.get("hd") or "").strip().lower()
    if not claims.get("email_verified") or not email:
        raise SignInError("Your Google account's email address isn't verified.", 403)
    if hosted_domain != ALLOWED_DOMAIN or not email.endswith("@" + ALLOWED_DOMAIN):
        raise SignInError(
            f"This app is only open to @{ALLOWED_DOMAIN} accounts. You signed in as {email} — "
            f"sign in with your @{ALLOWED_DOMAIN} Google account instead.",
            403,
        )
    return {"email": email, "name": claims.get("name") or email, "picture": claims.get("picture") or ""}
