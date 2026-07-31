import os
import logging
from fastapi import HTTPException, Security
import jwt
from jwt import PyJWKClient
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer()
logger = logging.getLogger("market")
logging.basicConfig(level=logging.INFO)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

if not SUPABASE_URL:
    raise ValueError("SUPABASE_URL is missing in .env file")

JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"

jwks_client = PyJWKClient(
    JWKS_URL,
    headers={"apikey": SUPABASE_ANON_KEY} if SUPABASE_ANON_KEY else None,
)

def verify_user_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials

    if not token or token == "null" or token == "undefined":
        logger.error("🚨 Frontend sent an empty or invalid token string!")
        raise HTTPException(status_code=401, detail="Empty token provided.")

    logger.debug(f"🔍 Frontend se Token aaya: {token[:15]}...[TRUNCATED]")


    payload = None
    jwks_error = None

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        if signing_key.key is None:
            raise ValueError("PyJWKClient returned an empty key")

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            options={"verify_aud": False},
        )
        logger.debug("Token verified via JWKS (asymmetric key).")

    except Exception as e:
        jwks_error = e
        logger.warning(f"JWKS verification failed, falling back to HS256 secret. Reason: {e}")

    if payload is None:
        if not SUPABASE_JWT_SECRET:
            logger.exception("JWKS failed AND SUPABASE_JWT_SECRET is not set.", exc_info=jwks_error)
            raise HTTPException(status_code=401, detail="Authentication failed.")

        try:
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
            logger.debug("Token verified via legacy HS256 shared secret.")
        except Exception as e:
            logger.exception(f"Deep Error Trace (HS256 fallback also failed): {e}")
            raise HTTPException(status_code=401, detail="Authentication failed.")

    user_email = payload.get("email", "Unknown Email")
    logger.debug(f"Token verified successfully for user: {user_email}")
    return payload
