import hashlib
import html
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Budapest")


def token_hash(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_action_link(database, base_url, action, booking_id=None, email=None, valid_days=365):
    raw_token = secrets.token_urlsafe(9)
    database.table("action_tokens").insert({
        "token_hash": token_hash(raw_token),
        "action": action,
        "booking_id": booking_id,
        "email": (email or "").strip().lower() or None,
        "expires_at": (datetime.now(TZ) + timedelta(days=valid_days)).isoformat(),
    }).execute()
    return f"{base_url.rstrip('/')}/?action={action}&t={raw_token}"


def button_html(url, label, color="#166534"):
    return (
        f'<a href="{html.escape(url, quote=True)}" '
        f'style="display:inline-block;padding:12px 18px;background:{color};color:white;'
        f'text-decoration:none;border-radius:8px;font-weight:700">{html.escape(label)}</a>'
    )
