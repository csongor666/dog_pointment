import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from supabase import create_client


TIMEZONE = ZoneInfo("Europe/Budapest")


def required_environment_variable(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Hianyzó GitHub Actions secret vagy kornyezeti valtozo: {name}"
        )
    return value


def send_email(
    gmail_address: str,
    gmail_app_password: str,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    message = EmailMessage()
    message["From"] = gmail_address
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(gmail_address, gmail_app_password)
        smtp.send_message(message)


def main() -> int:
    print("[INFO] Emlekezteto folyamat inditasa")

    try:
        supabase_url = required_environment_variable("SUPABASE_URL")
        supabase_secret_key = required_environment_variable("SUPABASE_SECRET_KEY")
        gmail_address = required_environment_variable("GMAIL_ADDRESS")
        gmail_app_password = required_environment_variable("GMAIL_APP_PASSWORD")
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print("[OK] A szukseges kornyezeti valtozok elerhetok")

    supabase = create_client(supabase_url, supabase_secret_key)
    now = datetime.now(TIMEZONE)
    target_date = now.date() + timedelta(days=1)

    print(f"[INFO] Aktualis ido: {now.isoformat()}")
    print(f"[INFO] Keresett foglalasi nap: {target_date.isoformat()}")

    try:
        response = (
            supabase.table("bookings")
            .select(
                "id,booking_date,booking_time,service,"
                "customer_name,email,reminder_sent_at"
            )
            .eq("booking_date", target_date.isoformat())
            .eq("status", "active")
            .is_("reminder_sent_at", "null")
            .execute()
        )
    except Exception as exc:
        print("[ERROR] A Supabase lekerdezes sikertelen.", file=sys.stderr)
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    bookings = response.data or []
    print(f"[INFO] Kikuldendo emlekeztetok szama: {len(bookings)}")

    sent_count = 0
    failed_count = 0

    for booking in bookings:
        booking_id = booking.get("id")
        recipient = str(booking.get("email") or "").strip()

        if not recipient:
            failed_count += 1
            print(
                f"[WARNING] Nincs e-mail-cim, kihagyva. Foglalas: {booking_id}"
            )
            continue

        subject = "Emlekezteto a holnapi kutyakozmetikai idopontrol"
        body = (
            f"Kedves {booking.get('customer_name', 'Gazdi')}!\n\n"
            f"Emlekeztetunk, hogy holnap, {booking['booking_date']} napjan "
            f"{booking['booking_time']} orakor varunk.\n\n"
            f"Szolgaltatas: {booking['service']}\n\n"
            "Ha nem tudsz eljonni, kerjuk, jelezd idoben.\n\n"
            "Kutyakozmetika Miskolc"
        )

        try:
            send_email(
                gmail_address=gmail_address,
                gmail_app_password=gmail_app_password,
                recipient=recipient,
                subject=subject,
                body=body,
            )

            sent_at = datetime.now(TIMEZONE).isoformat()
            (
                supabase.table("bookings")
                .update({"reminder_sent_at": sent_at})
                .eq("id", booking_id)
                .execute()
            )

            sent_count += 1
            print(f"[OK] Emlekezteto elkuldve. Foglalas: {booking_id}")

        except smtplib.SMTPAuthenticationError as exc:
            print(
                "[ERROR] A Gmail elutasitotta a belepest. Ellenorizd a "
                "GMAIL_ADDRESS es GMAIL_APP_PASSWORD ertekeket.",
                file=sys.stderr,
            )
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1

        except Exception as exc:
            failed_count += 1
            print(
                f"[ERROR] Sikertelen emlekezteto. Foglalas: {booking_id}",
                file=sys.stderr,
            )
            print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"[SUMMARY] Elkuldve: {sent_count}; hibas vagy kihagyott: {failed_count}")
    return 1 if failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
