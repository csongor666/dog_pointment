import hashlib
import html
import os
import secrets
import smtplib
import sys
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from supabase import create_client

TZ = ZoneInfo("Europe/Budapest")


def env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Hiányzó secret: {name}")
    return value


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def main():
    try:
        url, key, address, password = [env(x) for x in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")]
        app_url = os.environ.get("APP_URL", "https://dog-pointment.streamlit.app").rstrip("/")
        database = create_client(url, key)
        target = (datetime.now(TZ).date() + timedelta(days=1)).isoformat()
        rows = database.table("bookings").select(
            "id,booking_date,booking_time,service,status,is_demo,owner:owners!bookings_owner_id_fkey(id,full_name,email)"
        ).eq("booking_date", target).eq("status", "active").eq("is_demo", False).is_("reminder_sent_at", "null").execute().data or []
        print(f"[INFO] Küldendő emlékeztetők: {len(rows)}")
        failed = 0
        for booking in rows:
            try:
                owner = booking["owner"]
                token = secrets.token_urlsafe(9)
                database.table("action_tokens").insert({
                    "token_hash": token_hash(token), "action": "cancel_booking",
                    "owner_id": owner["id"], "booking_id": booking["id"],
                    "expires_at": (datetime.now(TZ) + timedelta(days=7)).isoformat(),
                }).execute()
                cancel_url = f"{app_url}/?action=cancel_booking&t={token}"
                message = EmailMessage(); message["From"] = address; message["To"] = owner["email"]
                message["Subject"] = "Emlékeztető a holnapi időpontról"
                message.set_content(
                    f"Kedves {owner['full_name']}!\n\nHolnap {booking['booking_time']}-kor várunk. "
                    f"Szolgáltatás: {booking['service']}.\n\nFoglalás lemondása: {cancel_url}"
                )
                message.add_alternative(
                    f"<p>Kedves {html.escape(owner['full_name'])}!</p>"
                    f"<p>Holnap <strong>{booking['booking_time']}</strong>-kor várunk. "
                    f"Szolgáltatás: {html.escape(booking['service'])}.</p>"
                    f'<p><a href="{html.escape(cancel_url, quote=True)}" style="display:inline-block;padding:12px 18px;'
                    f'background:#b91c1c;color:white;text-decoration:none;border-radius:8px;font-weight:bold">Foglalás lemondása</a></p>',
                    subtype="html",
                )
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
                    smtp.login(address, password); smtp.send_message(message)
                database.table("bookings").update({"reminder_sent_at": datetime.now(TZ).isoformat()}).eq("id", booking["id"]).execute()
                print(f"[OK] {booking['id']}")
            except Exception as exc:
                failed += 1
                print(f"[ERROR] {booking['id']}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1 if failed else 0
    except Exception as exc:
        print(f"[FATAL] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
