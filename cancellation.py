import hashlib
import hmac
import urllib.parse
import streamlit as st


def _secret(name, default=""):
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return str(default)


def cancellation_token(booking_id, email):
    signing_secret = _secret("CANCELLATION_SECRET").encode("utf-8")
    if not signing_secret:
        raise RuntimeError("A CANCELLATION_SECRET nincs beállítva.")
    message = f"{booking_id}|{(email or '').strip().lower()}".encode("utf-8")
    return hmac.new(signing_secret, message, hashlib.sha256).hexdigest()


def cancellation_url(booking):
    base_url = _secret("PUBLIC_APP_URL").rstrip("/")
    if not base_url:
        raise RuntimeError("A PUBLIC_APP_URL nincs beállítva.")
    booking_id = str(booking["id"])
    email = (booking.get("email") or "").strip().lower()
    token = cancellation_token(booking_id, email)
    return (
        f"{base_url}/?cancel_booking={urllib.parse.quote(booking_id)}"
        f"&email={urllib.parse.quote(email)}&token={token}"
    )


def verify_cancellation_token(booking_id, email, supplied_token):
    expected = cancellation_token(booking_id, email)
    return hmac.compare_digest(str(supplied_token), expected)


def append_cancellation_footer(body, booking):
    link = cancellation_url(booking)
    return (
        body.rstrip()
        + "\n\n----------------------------------------\n"
        + "Ha mégsem tudsz eljönni, az alábbi biztonságos linken lemondhatod a foglalást:\n"
        + link
        + "\n\nA lemondás után az időpont azonnal újra foglalhatóvá válik."
    )
