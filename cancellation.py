import hashlib
import hmac
import urllib.parse

import streamlit as st


def _secret(name, default=""):
    try:
        return str(st.secrets.get(name, default)).strip()
    except Exception:
        return str(default).strip()


def cancellation_token(booking_id, email):
    signing_secret = _secret("CANCELLATION_SECRET").encode("utf-8")
    if not signing_secret:
        raise RuntimeError("A CANCELLATION_SECRET nincs beállítva a Streamlit Secrets között.")
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        raise RuntimeError("A foglaláshoz nem tartozik e-mail-cím.")
    message = f"{booking_id}|{normalized_email}".encode("utf-8")
    return hmac.new(signing_secret, message, hashlib.sha256).hexdigest()


def cancellation_url(booking):
    base_url = _secret("PUBLIC_APP_URL").rstrip("/")
    if not base_url:
        raise RuntimeError("A PUBLIC_APP_URL nincs beállítva a Streamlit Secrets között.")
    if not base_url.startswith("https://"):
        raise RuntimeError("A PUBLIC_APP_URL értékének https:// címmel kell kezdődnie.")
    booking_id = str(booking.get("id") or "").strip()
    if not booking_id:
        raise RuntimeError("A foglalás azonosítója hiányzik.")
    email = (booking.get("email") or "").strip().lower()
    token = cancellation_token(booking_id, email)
    query = urllib.parse.urlencode({
        "cancel_booking": booking_id,
        "email": email,
        "token": token,
    })
    return f"{base_url}/?{query}"


def verify_cancellation_token(booking_id, email, supplied_token):
    expected = cancellation_token(booking_id, email)
    return hmac.compare_digest(str(supplied_token), expected)


def append_cancellation_footer(body, booking):
    return (
        body.rstrip()
        + "\n\n========================================\n"
        + "FOGLALÁS LEMONDÁSA\n"
        + "Ha mégsem tudsz eljönni, az alábbi biztonságos linken lemondhatod a foglalást:\n\n"
        + cancellation_url(booking)
        + "\n\nA lemondás után az időpont azonnal újra foglalhatóvá válik."
    )
