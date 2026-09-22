import html
import os
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from supabase import create_client
from token_links import button_html, create_action_link

TZ = ZoneInfo("Europe/Budapest")
db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
target = (datetime.now(TZ).date() + timedelta(days=1)).isoformat()
rows = db.table("bookings").select("id,booking_date,booking_time,service,customer_name,email").eq("booking_date", target).eq("status", "active").is_("reminder_sent_at", "null").execute().data or []
failed = 0
for booking in rows:
    try:
        cancel_link = create_action_link(
            db, os.environ["PUBLIC_APP_URL"], "cancel_booking",
            booking_id=booking["id"], email=booking["email"], valid_days=7,
        )
        text_body = (
            f"Kedves {booking['customer_name']}!\n\nHolnap {str(booking['booking_time'])[:5]}-kor várunk.\n"
            f"{booking['service']}\n\nFoglalás lemondása: {cancel_link}"
        )
        html_body = (
            f"<p>Kedves {html.escape(booking['customer_name'])}!</p>"
            f"<p>Holnap <strong>{str(booking['booking_time'])[:5]}</strong>-kor várunk.<br>"
            f"{html.escape(booking['service'])}</p>"
            f"<p>{button_html(cancel_link, 'Foglalás lemondása', '#b91c1c')}</p>"
        )
        message = EmailMessage()
        message["From"] = os.environ["GMAIL_ADDRESS"]
        message["To"] = booking["email"]
        message["Subject"] = "Emlékeztető a holnapi időpontról"
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"].replace(" ", ""))
            smtp.send_message(message)
        db.table("bookings").update({"reminder_sent_at": datetime.now(TZ).isoformat(), "last_email_error": None}).eq("id", booking["id"]).execute()
        db.table("email_logs").insert({"booking_id": booking["id"], "email_type": "reminder", "recipient": booking["email"], "subject": message["Subject"], "success": True}).execute()
    except Exception as exc:
        failed += 1
        print(exc)
print(f"sent={len(rows)-failed}, failed={failed}")
raise SystemExit(1 if failed else 0)
