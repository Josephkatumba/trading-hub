"""Auth0-compatible OIDC authorization code + PKCE; server-owned entitlements and journals."""
import asyncio
import json
import os
import secrets
import time
from datetime import datetime, timezone
from functools import lru_cache
from collections import OrderedDict
from urllib.parse import urlsplit
from authlib.integrations.starlette_client import OAuth, OAuthError
from joserfc.errors import JoseError
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from commercial_store import CommercialStore, Conflict

router = APIRouter()
COOKIE = "tradeden_session"
FREE_SYMBOLS = frozenset({"XAUUSD", "EURUSD", "GBPUSD"})
PRO_PRICE_USD = 19
KINDS = {"trade", "account", "review"}
_LOGIN_ATTEMPTS = OrderedDict()


@lru_cache(maxsize=1)
def store():
    url = os.getenv("TRADING_HUB_DATABASE_URL")
    if not url:
        raise HTTPException(503, "User storage is not configured")
    return CommercialStore(url)


def policy(user):
    return {"plan": user["plan"], "price_usd": PRO_PRICE_USD, "history_days": 90 if user["plan"] == "pro" else 7,
            "symbols": None if user["plan"] == "pro" else sorted(FREE_SYMBOLS), "exports": user["plan"] == "pro"}


def require_user(request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Sign in required")
    return user


def require_write(request):
    user = require_user(request)
    token = request.headers.get("x-csrf-token", "")
    if not token or not secrets.compare_digest(token, user["csrf"]):
        raise HTTPException(403, "CSRF token required")
    return user


def scope_payload(value, user, inherited_symbol=None):
    """Fail-closed shared-market scope. Never used to scope private journals."""
    symbols = None if user["plan"] == "pro" else FREE_SYMBOLS
    cutoff = time.time() - (90 if user["plan"] == "pro" else 7) * 86400
    if isinstance(value, list):
        return [scoped for row in value if (scoped := scope_payload(row, user, inherited_symbol)) is not None]
    if not isinstance(value, dict):
        return value
    symbol = value.get("symbol") or inherited_symbol
    if all(k in value for k in ("time", "open", "high", "low", "close")) and value["time"] < cutoff:
        return None
    if symbols is not None and symbol and symbol not in symbols:
        return None
    if value.get("setup_id") and not symbol:
        return None
    if value.get("record_type") or value.get("setup_id"):
        for key in ("observed_at", "confirmed_at", "occurred_at", "resolved_at", "timestamp"):
            if value.get(key):
                try:
                    stamp = datetime.fromisoformat(str(value[key]).replace("Z", "+00:00"))
                    if stamp.tzinfo is None or stamp.timestamp() < cutoff:
                        return None
                except ValueError:
                    return None
                break
    return {k: scope_payload(v, user, symbol) for k, v in value.items() if k != "trade_outcomes"}


def install(app):
    mode = os.getenv("TRADING_HUB_AUTH_MODE", "private")
    if mode not in {"private", "oidc"}:
        raise RuntimeError("Unknown authentication mode")
    enabled = mode == "oidc"
    oauth = OAuth()
    if enabled:
        issuer = os.getenv("TRADING_HUB_OIDC_ISSUER", "").rstrip("/") + "/"
        origin = os.getenv("TRADING_HUB_PUBLIC_ORIGIN", "")
        secret = os.getenv("TRADING_HUB_SESSION_SECRET", "")
        if (not issuer.startswith("https://") or len(secret) < 32 or not origin.startswith("https://")
                or not os.getenv("TRADING_HUB_OIDC_CLIENT_ID") or not os.getenv("TRADING_HUB_OIDC_CLIENT_SECRET")
                or not os.getenv("TRADING_HUB_DATABASE_URL", "").startswith("postgresql+psycopg://")):
            raise RuntimeError("Commercial mode requires HTTPS OIDC/origin, 32+ character session secret and PostgreSQL")
        oauth.register("identity", client_id=os.environ["TRADING_HUB_OIDC_CLIENT_ID"],
            client_secret=os.environ["TRADING_HUB_OIDC_CLIENT_SECRET"],
            server_metadata_url=issuer + ".well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"})
        app.add_middleware(SessionMiddleware, secret_key=secret, session_cookie="tradeden_oidc_state",
                           max_age=600, same_site="lax", https_only=True)
    app.state.oidc = oauth

    @app.middleware("http")
    async def account_guard(request, call_next):
        request.state.user = None
        token = request.cookies.get(COOKIE)
        if token:
            try:
                request.state.user = await asyncio.to_thread(store().identity, token)
            except Exception:
                return JSONResponse({"detail": "User storage unavailable"}, 503)
        path = request.url.path
        if path == "/api/auth/login":
            address = request.client.host if request.client else "unknown"
            now = time.monotonic()
            while _LOGIN_ATTEMPTS and next(iter(_LOGIN_ATTEMPTS.values()))[0] < now - 60:
                _LOGIN_ATTEMPTS.popitem(last=False)
            start, count = _LOGIN_ATTEMPTS.get(address, (now, 0))
            if count >= 30 or len(_LOGIN_ATTEMPTS) >= 1024:
                return JSONResponse({"detail": "Try sign in again later"}, 429)
            _LOGIN_ATTEMPTS[address] = (start, count + 1)
        if enabled and (path.startswith("/api/") and not path.startswith("/api/auth/")
                        and path not in {"/api/health", "/api/ready"}):
            if not request.state.user:
                return JSONResponse({"detail": "Sign in required"}, 401)
            if path == "/api/market/chart" and request.state.user["plan"] != "pro" and request.query_params.get("symbol", "XAUUSD") not in FREE_SYMBOLS:
                return JSONResponse({"detail": "Instrument requires Pro"}, 403)
            allowed = {"/api/market/radar", "/api/market/strategies", "/api/market/setup-episodes",
                       "/api/market/outcomes", "/api/market/candles", "/api/market/chart", "/api/market/performance"}
            parts = path.split("/")
            setup_read = request.method in {"GET", "HEAD"} and len(parts) in {5, 6} and parts[:4] == ["", "api", "market", "setups"] and (len(parts) == 5 or parts[5] in {"history", "lifecycle"})
            if setup_read:
                from observations import setup_history
                rows = await asyncio.to_thread(setup_history, parts[4])
                if not rows:
                    return JSONResponse({"detail": "Setup not found"}, 404)
                latest = rows[-1]
                if scope_payload(latest, request.state.user) is None:
                    return JSONResponse({"detail": "Setup outside entitlement"}, 403)
                request.state.market_symbol = latest.get("symbol")
            if not setup_read and not path.startswith(("/api/journal/", "/api/billing/")) and path not in allowed:
                return JSONResponse({"detail": "This research administration route is private"}, 403)
            if request.method not in {"GET", "HEAD", "OPTIONS"} and not path.startswith(("/api/journal/", "/api/billing/")):
                return JSONResponse({"detail": "Research is read only"}, 403)
        if path.startswith("/api/journal/") and request.method == "PUT":
            length = request.headers.get("content-length", "")
            if not length.isdigit() or int(length) > 96 * 1024:
                return JSONResponse({"detail": "A bounded journal request body is required"}, 413)
        response = await call_next(request)
        if enabled and request.state.user:
            response.headers["Cache-Control"] = "private, no-store"
        if enabled and request.state.user and path.startswith("/api/market/") and response.status_code == 200:
            if path != "/api/market/performance":
                body = b"".join([chunk async for chunk in response.body_iterator])
                return JSONResponse(scope_payload(json.loads(body), request.state.user, getattr(request.state, "market_symbol", None)), headers={"Cache-Control": "private, no-store"})
        if path.startswith(("/api/auth/", "/api/journal/")):
            response.headers["Cache-Control"] = "no-store"
        if enabled and path == "/api/health" and response.status_code == 200:
            body = b"".join([chunk async for chunk in response.body_iterator])
            data = json.loads(body)
            return JSONResponse({"ok": data.get("ok"), "status": data.get("status"), "service": data.get("service")})
        return response
    app.include_router(router)


@router.get("/api/auth/login")
async def login(request: Request):
    client = request.app.state.oidc.create_client("identity")
    if client is None:
        raise HTTPException(503, "OIDC is not configured")
    return await client.authorize_redirect(request, os.environ["TRADING_HUB_PUBLIC_ORIGIN"].rstrip("/") + "/api/auth/callback", prompt="login")


@router.get("/api/auth/callback")
async def callback(request: Request):
    client = request.app.state.oidc.create_client("identity")
    if client is None:
        raise HTTPException(503, "OIDC is not configured")
    try:
        token = await client.authorize_access_token(request)
        identity = token.get("userinfo")
        if (not token.get("id_token") or not identity or identity.get("iss") != os.environ["TRADING_HUB_OIDC_ISSUER"].rstrip("/") + "/"
                or not identity.get("sub") or not identity.get("nonce") or identity.get("nonce_supported") is False
                or identity.get("exp", 0) <= time.time()):
            raise HTTPException(401, "Invalid identity claims")
        opaque, _ = await asyncio.to_thread(store().login, identity["iss"], identity["sub"])
    except (OAuthError, JoseError, ValueError):
        raise HTTPException(401, "Identity verification failed")
    request.session.clear()
    response = RedirectResponse(os.environ["TRADING_HUB_PUBLIC_ORIGIN"], status_code=303)
    response.set_cookie(COOKIE, opaque, max_age=8 * 3600, secure=True, httponly=True, samesite="lax", path="/")
    return response


@router.get("/api/auth/me")
def me(request: Request):
    user = require_user(request)
    return {"user": {"id": user["id"]}, "csrf": user["csrf"], "entitlements": policy(user)}


@router.post("/api/auth/logout")
def logout(request: Request):
    require_write(request)
    store().logout(request.cookies[COOKIE])
    response = JSONResponse({"logged_out": True})
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


def kind_check(kind):
    if kind not in KINDS:
        raise HTTPException(422, "Unknown journal record type")


@router.get("/api/journal/export")
def export(request: Request):
    user = require_user(request)
    if user["plan"] != "pro":
        raise HTTPException(403, "Pro entitlement required")
    # Bounded export page; clients use the journal pagination for larger exports.
    return {kind: store().records(user["id"], kind) for kind in sorted(KINDS)}


@router.get("/api/journal/{kind}")
def list_journal(request: Request, kind: str, cursor: str = Query("", max_length=160), limit: int = Query(200, ge=1, le=200)):
    user = require_user(request)
    kind_check(kind)
    return store().records(user["id"], kind, cursor, limit)


class JournalWrite(BaseModel):
    payload: dict
    version: int = Field(ge=0)


@router.put("/api/journal/{kind}/{record_id}")
def put_journal(request: Request, kind: str, record_id: str, body: JournalWrite):
    user = require_write(request)
    kind_check(kind)
    if not record_id or len(record_id) > 160 or len(json.dumps(body.payload)) > 65536:
        raise HTTPException(422, "Journal record exceeds limits")
    if kind == "trade" and (body.payload.get("side") not in {"BUY", "SELL"} or str(body.payload.get("id")) != record_id):
        raise HTTPException(422, "Trade requires matching ID and BUY/SELL side")
    try:
        return store().put(user["id"], kind, record_id, body.payload, body.version)
    except Conflict as exc:
        raise HTTPException(409, str(exc))


@router.delete("/api/journal/{kind}/{record_id}")
def delete_journal(request: Request, kind: str, record_id: str, version: int = Query(ge=1)):
    user = require_write(request)
    kind_check(kind)
    try:
        store().remove(user["id"], kind, record_id, version)
    except Conflict as exc:
        raise HTTPException(409, str(exc))
    return {"deleted": True}


@router.post("/api/billing/checkout")
def checkout(request: Request):
    require_write(request)
    raise HTTPException(503, "Billing is not activated")


@router.post("/api/billing/webhook")
def webhook():
    # No grant can originate from an unsigned client webhook or inactive billing provider.
    raise HTTPException(503, "Billing is not activated")
