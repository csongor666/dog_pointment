import html
import smtplib
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import streamlit as st

from db import get_db
from token_links import button_html, create_action_link

TZ = ZoneInfo("Europe/Budapest")


def _log(booking_id, email_type, recipient, subject, success, error=None):
    try:
        get_db().table("email_logs").insert({
            "booking_id": booking_id, "email_type": email_type,
            "recipient": recipient or "nincs megadva", "subject": subject,
            "success": success, "error_message": str(error)[:2000] if error else None,
        }).execute()
    except Exception as exc:
        print("Email log error:", exc)


def send_confirmation(booking, email_type="confirmation"):
    recipient = (booking.get("email") or "").strip()
    subject = "Foglalás visszaigazolása"
    if not recipient:
        return False, "Nincs e-mail-cím."
    try:
        cancel_link = create_action_link(
            get_db(), str(st.secrets["PUBLIC_APP_URL"]),
            "cancel_booking", booking_id=booking["id"], email=recipient, valid_days=365,
        )
        text_body = (
            f"Kedves {booking['customer_name']}!\n\n"
            f"Foglalásod rögzítettük:\nIdőpont: {booking['booking_date']} {str(booking['booking_time'])[:5]}\n"
            f"Szolgáltatás: {booking['service']}\n\nFoglalás lemondása: {cancel_link}"
        )
        html_body = (
            f"<p>Kedves {html.escape(booking['customer_name'])}!</p>"
            f"<p>Foglalásod rögzítettük:</p>"
            f"<p><strong>Időpont:</strong> {booking['booking_date']} {str(booking['booking_time'])[:5]}<br>"
            f"<strong>Szolgáltatás:</strong> {html.escape(booking['service'])}</p>"
            f"<p>{button_html(cancel_link, 'Foglalás lemondása', '#b91c1c')}</p>"
        )
    except Exception as exc:
        _log(booking.get("id"), email_type, recipient, subject, False, exc)
        return False, f"A rövid lemondási link létrehozása sikertelen: {exc}"
    message = EmailMessage()
    message["From"] = st.secrets["GMAIL_ADDRESS"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text_body, subtype="plain", charset="utf-8")
    message.add_alternative(html_body, subtype="html")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(st.secrets["GMAIL_ADDRESS"], st.secrets["GMAIL_APP_PASSWORD"].replace(" ", ""))
            smtp.send_message(message)
        _log(booking["id"], email_type, recipient, subject, True)
        get_db().table("bookings").update({
            "confirmation_sent_at": datetime.now(TZ).isoformat(), "last_email_error": None,
        }).eq("id", booking["id"]).execute()
        return True, None
    except Exception as exc:
        _log(booking["id"], email_type, recipient, subject, False, exc)
        try:
            get_db().table("bookings").update({"last_email_error": str(exc)[:2000]}).eq("id", booking["id"]).execute()
        except Exception:
            pass
        return False, str(exc)
