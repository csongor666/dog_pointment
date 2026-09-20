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
            f"Hiányzó GitHub Actions secret vagy környezeti változó: {name}"
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

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465,
        timeout=30,
    ) as smtp:
        smtp.login(
            gmail_address,
            gmail_app_password,
        )
        smtp.send_message(message)


def main() -> int:
    print("[INFO] Emlékeztető folyamat indítása")

    supabase_url = required_environment_variable(
        "SUPABASE_URL"
    )
    supabase_secret_key = required_environment_variable(
        "SUPABASE_SECRET_KEY"
    )
    gmail_address = required_environment_variable(
        "GMAIL_ADDRESS"
    )
    gmail_app_password = required_environment_variable(
        "GMAIL_APP_PASSWORD"
    )

    print("[OK] A szükséges környezeti változók rendelkezésre állnak")

    supabase = create_client(
        supabase_url,
        supabase_secret_key,
    )

    now = datetime.now(TIMEZONE)
    target_date = now.date() + timedelta(days=1)

    print(f"[INFO] Aktuális idő: {now.isoformat()}")
    print(f"[INFO] Keresett foglalási nap: {target_date.isoformat()}")

    try:
        response = (
            supabase
            .table("bookings")
            .select(
                "id,"
                "booking_date,"
                "booking_time,"
                "service,"
                "customer_name,"
                "email,"
                "reminder_sent_at"
            )
            .eq(
                "booking_date",
                target_date.isoformat(),
            )
            .eq(
                "status",
                "active",
            )
            .is_(
                "reminder_sent_at",
                "null",
            )
            .execute()
        )

    except Exception as exc:
        print(
            "[ERROR] A Supabase lekérdezés sikertelen.",
            file=sys.stderr,
        )
        print(
            f"[ERROR] {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    bookings = response.data or []

    print(
        f"[INFO] Kiküldendő emlékeztetők száma: "
        f"{len(bookings)}"
    )

    sent_count = 0
    failed_count = 0

    for booking in bookings:
        booking_id = booking.get("id")
        recipient = str(
            booking.get("email") or ""
        ).strip()

        if not recipient:
            failed_count += 1
            print(
                f"[WARNING] Nincs e-mail-cím, kihagyva. "
                f"Foglalásazonosító: {booking_id}"
            )
            continue

        subject = (
            "Emlékeztető a holnapi "
            "kutyakozmetikai időpontról"
        )

        body = (
            f"Kedves {booking['customer_name']}!\n\n"
            f"Emlékeztetünk, hogy holnap, "
            f"{booking['booking_date']} napján "
            f"{booking['booking_time']} órakor várunk.\n\n"
            f"Szolgáltatás: {booking['service']}\n\n"
            f"Ha nem tudsz eljönni, kérjük, "
            f"jelezd időben.\n\n"
            f"Kutyakozmetika Miskolc"
        )

        try:
            send_email(
                gmail_address=gmail_address,
                gmail_app_password=gmail_app_password,
                recipient=recipient,
                subject=subject,
                body=body,
            )

            sent_at = datetime
