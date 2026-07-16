
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from .config import get_supabase_auth_read_client, settings
from .models import AuthResponse, LoginRequest, SignupRequest

router = APIRouter(prefix="/auth", tags=["auth"])


def _one_shot_auth_client():

    from supabase import create_client
    from supabase.lib.client_options import ClientOptions

    return create_client(
        settings.supabase_url,
        settings.supabase_service_key,
        options=ClientOptions(auto_refresh_token=False),
    )


@router.post("/signup", response_model=AuthResponse)
def signup(req: SignupRequest):
    sb = _one_shot_auth_client()

    try:
        res = sb.auth.sign_up({
            "email": req.email,
            "password": req.password,
        })
    except Exception as e:
        raise HTTPException(400, f"Signup failed: {e}")

    if not res.user:
        raise HTTPException(400, "Signup failed")

    session = res.session
    if session is None:
      
        try:
            res2 = sb.auth.sign_in_with_password({"email": req.email, "password": req.password})
            session = res2.session
        except Exception:
            session = None

    if session is None:
        raise HTTPException(
            400,
            "Account created, but a session couldn't be started — your Supabase "
            "project requires confirming your email first. Please check your "
            "inbox, confirm, then log in.",
        )

    return AuthResponse(
        access_token=session.access_token,
        user_id=res.user.id,
        email=req.email,
    )


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest):
    sb = _one_shot_auth_client()
    try:
        res = sb.auth.sign_in_with_password({"email": req.email, "password": req.password})
    except Exception as e:
        raise HTTPException(401, f"Invalid credentials: {e}")
    return AuthResponse(
        access_token=res.session.access_token, user_id=res.user.id, email=req.email
    )


def _verify_locally(token: str) -> str | None:
    
    if not settings.jwt_secret or settings.jwt_secret == "dev-secret":
        return None
    try:
        import jwt as pyjwt

        payload = pyjwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_aud": True},
        )
        return payload.get("sub")
    except Exception:
        return None


def get_current_user(authorization: str = Header(default="")) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization token")

    token = authorization.split(" ", 1)[1]

    user_id = _verify_locally(token)
    if user_id:
        return user_id

    
    try:
        sb = get_supabase_auth_read_client()
        user = sb.auth.get_user(token)
        if user and user.user:
            return user.user.id
    except Exception:
        pass

    raise HTTPException(status_code=401, detail="Invalid or expired token")
