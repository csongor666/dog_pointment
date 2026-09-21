import smtplib
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import streamlit as st

from cancellation import cancellation_url
from db import get_db

TZ = ZoneInfo("Europe/Budapest")


def _log(booking_id, email_type, recipient, subject, success, error=None):
    try:
        get_db().table("email_logs").insert({
            "booking_id": booking_id,
            "email_type": email_type,
            "recipient": recipient or "nincs megadva",
            "subject": subject,
            "success": success,
            "error_message": str(error)[:2000] if error else None,
        }).execute()
    except Exception as exc:
        print("Email log error:", exc)


def build_confirmation_body(booking):
    """A ténylegesen kiküldött visszaigazoló levél teljes szövege."""
    cancel_link = cancellation_url(booking)
    if not cancel_link.startswith("https://"):
        raise RuntimeError("A lemondási link nem HTTPS címmel kezdődik.")
    return (
        f"Kedves {booking['customer_name']}!\n\n"
        "Foglalásod rögzítettük:\n"
        f"Időpont: {booking['booking_date']} {str(booking['booking_time'])[:5]}\n"
        f"Szolgáltatás: {booking['service']}\n\n"
        "Kutyakozmetika Miskolc\n\n"
        "========================================\n"
        "FOGLALÁS LEMONDÁSA\n"
        "Ha mégsem tudsz eljönni, az alábbi biztonságos linken lemondhatod a foglalást:\n\n"
        f"{cancel_link}\n\n"
        "A lemondás után az időpont azonnal újra foglalhatóvá válik."
    )


def send_confirmation(booking, email_type="confirmation"):
    recipient = (booking.get("email") or "").strip()
    subject = "Foglalás visszaigazolása"
    if not recipient:
        return False, "Nincs e-mail-cím."

    try:
        body = build_confirmation_body(booking)
    except Exception as exc:
        _log(booking.get("id"), email_type, recipient, subject, False, exc)
        return False, f"A lemondási link létrehozása sikertelen: {exc}"

    message = EmailMessage()
    message["From"] = st.secrets["GMAIL_ADDRESS"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body, subtype="plain", charset="utf-8")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(
                st.secrets["GMAIL_ADDRESS"],
                st.secrets["GMAIL_APP_PASSWORD"].replace(" ", ""),
            )
            smtp.send_message(message)

        _log(booking["id"], email_type, recipient, subject, True)
        get_db().table("bookings").update({
            "confirmation_sent_at": datetime.now(TZ).isoformat(),
            "last_email_error": None,
        }).eq("id", booking["id"]).execute()
        return True, None
    except Exception as exc:
        _log(booking["id"], email_type, recipient, subject, False, exc)
        try:
            get_db().table("bookings").update({
                "last_email_error": str(exc)[:2000]
            }).eq("id", booking["id"]).execute()
        except Exception:
            pass
        return False, str(exc)
