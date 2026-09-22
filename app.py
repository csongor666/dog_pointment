import hmac
import re
import smtplib
import hashlib
import html
import urllib.parse
from email.message import EmailMessage
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
from db import get_db
from email_service import send_confirmation
from cancellation import append_cancellation_footer, verify_cancellation_token

st.set_page_config(page_title="Kutyakozmetika Miskolc", page_icon="🐶", layout="wide")
DB = get_db()
TZ = ZoneInfo("Europe/Budapest")

SERVICES = {
    "Kistestű nyírás": 90,
    "Nagytestű nyírás": 120,
    "Fürdetés": 60,
    "Karomvágás": 30,
}
STATUS = {
    "active": "Aktív",
    "completed": "Teljesítve",
    "cancelled": "Lemondva",
    "no_show": "Nem jelent meg",
}
SERVICE_COLORS = {
    "Kistestű nyírás": "#2563eb",
    "Nagytestű nyírás": "#7c3aed",
    "Fürdetés": "#0891b2",
    "Karomvágás": "#ea580c",
}
STATUS_COLORS = {
    "active": "#eab308",
    "completed": "#3b82f6",
    "cancelled": "#64748b",
    "no_show": "#dc2626",
}
PHONE_RE = re.compile(r"^[+0-9][0-9 ()/-]{6,24}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DAY_NAMES = ["H", "K", "Sze", "Cs", "P", "Szo", "V"]

st.markdown(
    """
    <style>
    .block-container { max-width: 1450px; }
    .legend { display:inline-block; width:14px; height:14px; border-radius:3px; margin-right:5px; }
    .slot-card { padding:7px 5px; border-radius:7px; margin:3px 0; font-size:.82rem; text-align:center; font-weight:600; }
    .slot-free { background:#22c55e; color:white; }
    .slot-busy { background:#eab308; color:#422006; }
    .slot-closed { background:#9ca3af; color:white; }
    .day-head { text-align:center; font-weight:700; padding:8px 3px; background:#f1f5f9; border-radius:8px; margin-bottom:4px; min-height:66px; display:flex; align-items:center; justify-content:center; }
    .admin-calendar-grid { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:8px; align-items:stretch; }
    .admin-day-card { border:1px solid #dbe3ec; border-radius:10px; background:#ffffff; padding:7px; min-height:720px; display:flex; flex-direction:column; }
    .admin-day-slots { display:flex; flex-direction:column; gap:5px; flex:1; }
    .admin-slot-card { height:58px; min-height:58px; max-height:58px; padding:7px 5px; border-radius:7px; font-size:.80rem; text-align:center; font-weight:700; display:flex; align-items:center; justify-content:center; line-height:1.2; overflow:hidden; }
    .admin-empty-fill { flex:1; min-height:54px; border-radius:7px; background:repeating-linear-gradient(135deg,#f8fafc,#f8fafc 8px,#f1f5f9 8px,#f1f5f9 16px); }
    .admin-hour-line { height:0; border-top:1px dashed #94a3b8; margin:7px 0 6px 0; position:relative; opacity:.85; }
    .admin-hour-line span { position:absolute; top:-9px; right:4px; padding:0 4px; background:#fff; color:#64748b; font-size:.65rem; font-weight:700; }
    .admin-legend-row { display:flex; flex-wrap:wrap; gap:8px 14px; margin:8px 0 14px 0; }
    .admin-legend-item { display:inline-flex; align-items:center; gap:5px; font-size:.80rem; font-weight:600; }
    .admin-legend-dot { width:14px; height:14px; border-radius:3px; display:inline-block; }
    .admin-timeline-head { min-height:66px; }
    .admin-timeline-spacer { width:100%; }
    .admin-timeline-closed { height:40px; min-height:40px; max-height:40px; margin:1px 0; }
    div[data-testid="stHorizontalBlock"]:has(.admin-timeline-head) { position:relative; overflow:visible; }
    div[data-testid="stHorizontalBlock"]:has(.admin-timeline-head)::before {
        content:"";
        position:absolute;
        left:0;
        right:0;
        top:74px;
        bottom:0;
        pointer-events:none;
        z-index:19;
        background:repeating-linear-gradient(
            to bottom,
            transparent 0,
            transparent 42px,
            rgba(148,163,184,.22) 42px,
            rgba(148,163,184,.22) 43px
        );
    }
    div[data-testid="stHorizontalBlock"]:has(.admin-timeline-head)::after {
        content:"";
        position:absolute;
        left:0;
        right:0;
        top:74px;
        bottom:0;
        pointer-events:none;
        z-index:20;
        background:repeating-linear-gradient(
            to bottom,
            transparent 0,
            transparent 84px,
            rgba(107,114,128,.38) 84px,
            rgba(107,114,128,.38) 86px
        );
    }
    .admin-time-axis-head {
        min-height:66px;
        display:flex;
        align-items:center;
        justify-content:center;
        color:#475569;
        font-size:.78rem;
        font-weight:700;
    }
    .admin-time-axis { position:relative; width:100%; }
    .admin-time-label {
        position:absolute;
        right:2px;
        transform:translateY(-50%);
        padding:0 3px;
        background:rgba(255,255,255,.94);
        color:#64748b;
        font-size:.67rem;
        line-height:1;
        font-weight:700;
        z-index:30;
    }
    div[data-testid="stHorizontalBlock"]:has(.admin-timeline-head) > div[data-testid="stColumn"] {
        position:relative; z-index:1;
    }
    /* Az admin idővonal függőleges Streamlit-konténereinek alapértelmezett hézaga nulla. */
    div[data-testid="stHorizontalBlock"]:has(.admin-timeline-head)
    > div[data-testid="stColumn"] div[data-testid="stVerticalBlock"] {
        gap:0 !important;
        row-gap:0 !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.admin-timeline-head)
    > div[data-testid="stColumn"] div[data-testid="stElementContainer"] {
        margin-top:0 !important;
        margin-bottom:0 !important;
        padding-top:0 !important;
        padding-bottom:0 !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.admin-timeline-head)
    > div[data-testid="stColumn"] div[data-testid="stMarkdownContainer"] {
        margin:0 !important;
        padding:0 !important;
    }
    div[class*="st-key-admin_free_"] { margin:0 !important; padding:0 !important; }
    div[class*="st-key-admin_free_"] button {
        height:40px !important; min-height:40px !important; max-height:40px !important;
        margin:0 !important; padding:2px 4px !important;
        white-space:normal !important; line-height:1.1 !important; font-size:.72rem !important;
    }
    div[class*="st-key-edit_"] { margin:0 !important; padding:0 !important; }
    div[class*="st-key-edit_"] button {
        margin:0 !important; padding:3px 5px !important;
        white-space:pre-line !important; overflow-wrap:anywhere !important;
        line-height:1.12 !important; font-size:.70rem !important; overflow:visible !important;
    }
    @media (max-width: 1000px) { .admin-calendar-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .admin-day-card { min-height:560px; } }
    @media (max-width: 650px) { .admin-calendar-grid { grid-template-columns:1fr; } .admin-day-card { min-height:auto; } }
    div[data-testid="stButton"] button[kind="primary"] { background:#22c55e; border-color:#16a34a; color:white; }
    div[data-testid="stButton"] button[kind="primary"]:hover { background:#16a34a; border-color:#15803d; color:white; }
    </style>
    """,
    unsafe_allow_html=True,
)


def secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def parse_time(value):
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value)[:5])


def minute_of_day(value):
    parsed = parse_time(value)
    return parsed.hour * 60 + parsed.minute


def monday_of(day):
    return day - timedelta(days=day.weekday())


def daterange_key(week_start):
    return week_start.isoformat(), (week_start + timedelta(days=6)).isoformat()


@st.cache_data(ttl=20, max_entries=128, show_spinner=False)
def load_public_week(week_start_iso):
    """Egyetlen csomagban tölti a hét nem személyes adatait."""
    week_start = date.fromisoformat(week_start_iso)
    start_iso, end_iso = daterange_key(week_start)
    booking_rows = (
        DB.table("bookings")
        .select("id,booking_date,booking_time,duration_min,service,status")
        .gte("booking_date", start_iso)
        .lte("booking_date", end_iso)
        .eq("status", "active")
        .execute().data or []
    )
    weekly_rows = DB.table("business_hours").select("*").order("weekday").execute().data or []
    exception_rows = (
        DB.table("opening_exceptions").select("*")
        .gte("exception_date", start_iso).lte("exception_date", end_iso)
        .execute().data or []
    )
    return {"bookings": booking_rows, "weekly": weekly_rows, "exceptions": exception_rows}


def load_admin_week(week_start):
    """Az admin személyes adatait egyetlen heti lekérdezéssel tölti le, globális cache nélkül."""
    start_iso, end_iso = daterange_key(week_start)
    booking_rows = (
        DB.table("bookings")
        .select("id,booking_date,booking_time,duration_min,service,status,customer_name,phone,email,dog_id,confirmation_sent_at,last_email_error,dog:dogs!bookings_dog_id_fkey(name)")
        .gte("booking_date", start_iso)
        .lte("booking_date", end_iso)
        .order("booking_date").order("booking_time")
        .execute().data or []
    )
    weekly_rows = DB.table("business_hours").select("*").order("weekday").execute().data or []
    exception_rows = (
        DB.table("opening_exceptions").select("*")
        .gte("exception_date", start_iso).lte("exception_date", end_iso)
        .execute().data or []
    )
    return {"bookings": booking_rows, "weekly": weekly_rows, "exceptions": exception_rows}


def schedule_from_bundle(day, bundle):
    exceptions = {row["exception_date"]: row for row in bundle["exceptions"]}
    weekly = {int(row["weekday"]): row for row in bundle["weekly"]}
    if day.isoformat() in exceptions:
        row = exceptions[day.isoformat()]
        return {
            "open": not row["is_closed"],
            "from": row.get("open_time"),
            "to": row.get("close_time"),
            "step": row.get("slot_interval_min") or 30,
            "note": row.get("note") or "",
        }
    row = weekly.get(day.weekday())
    if not row:
        return {"open": False, "note": "Nincs nyitvatartás"}
    return {
        "open": bool(row["is_open"]),
        "from": row.get("open_time"),
        "to": row.get("close_time"),
        "step": row.get("slot_interval_min") or 30,
        "note": "",
    }


def bookings_from_bundle(day, bundle, statuses=None, exclude_id=None):
    result = []
    for row in bundle["bookings"]:
        if row.get("booking_date") != day.isoformat():
            continue
        if statuses is not None and row.get("status") not in statuses:
            continue
        if exclude_id and row.get("id") == exclude_id:
            continue
        result.append(row)
    return result


def available_slots_from_bundle(day, duration, bundle, exclude_id=None, admin=False):
    schedule = schedule_from_bundle(day, bundle)
    if not schedule.get("open") or not schedule.get("from") or not schedule.get("to"):
        return [], schedule
    opening = minute_of_day(schedule["from"])
    closing = minute_of_day(schedule["to"])
    interval = int(schedule["step"])
    buffer_min = int(secret("BOOKING_BUFFER_MIN", 0))
    occupied = []
    for booking in bookings_from_bundle(day, bundle, ["active"], exclude_id):
        start = minute_of_day(booking["booking_time"])
        occupied.append((start, start + int(booking.get("duration_min") or 30) + buffer_min))
    now = datetime.now(TZ)
    notice = 0 if admin else int(secret("MIN_BOOKING_NOTICE_HOURS", 12))
    result = []
    cursor = opening
    while cursor + duration <= closing:
        candidate = datetime.combine(day, time(cursor // 60, cursor % 60), TZ)
        candidate_end = cursor + duration + buffer_min
        overlaps = any(cursor < booked_end and candidate_end > booked_start for booked_start, booked_end in occupied)
        if not overlaps and candidate >= now + timedelta(hours=notice):
            result.append(f"{cursor // 60:02d}:{cursor % 60:02d}")
        cursor += interval
    return result, schedule


def clear_public_cache():
    load_public_week.clear()


def week_navigation(key):
    if key not in st.session_state:
        st.session_state[key] = monday_of(datetime.now(TZ).date())
    left, center, right = st.columns([1, 4, 1])
    if left.button("◀ Előző hét", key=f"{key}_prev", use_container_width=True):
        st.session_state[key] -= timedelta(days=7)
        st.rerun()
    center.markdown(f"### {st.session_state[key]} – {st.session_state[key] + timedelta(days=6)}")
    if right.button("Következő hét ▶", key=f"{key}_next", use_container_width=True):
        st.session_state[key] += timedelta(days=7)
        st.rerun()
    return st.session_state[key]


def unsubscribe_token(email):
    secret_key = str(secret("UNSUBSCRIBE_SECRET", "")).encode("utf-8")
    normalized = email.strip().lower().encode("utf-8")
    if not secret_key:
        raise RuntimeError("Az UNSUBSCRIBE_SECRET nincs beállítva.")
    return hmac.new(secret_key, normalized, hashlib.sha256).hexdigest()


def unsubscribe_url(email):
    base_url = str(secret("PUBLIC_APP_URL", "")).rstrip("/")
    if not base_url:
        raise RuntimeError("A PUBLIC_APP_URL nincs beállítva.")
    return (
        f"{base_url}/?unsubscribe={urllib.parse.quote(email.strip().lower())}"
        f"&token={unsubscribe_token(email)}"
    )


def append_unsubscribe_footer(body, recipient):
    link = unsubscribe_url(recipient)
    return (
        body.rstrip()
        + "\n\n----------------------------------------\n"
        + "Ezt az üzenetet azért kaptad, mert hozzájárultál a hírlevélhez.\n"
        + "Leiratkozás egy kattintással:\n"
        + link
        + "\n\nA leiratkozás díjmentes, és azonnal érvénybe lép."
    )

def send_custom_email(recipient, subject, body, email_type="manual", booking_id=None):
    message = EmailMessage()
    message["From"] = secret("GMAIL_ADDRESS")
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(secret("GMAIL_ADDRESS"), str(secret("GMAIL_APP_PASSWORD", "")).replace(" ", ""))
            smtp.send_message(message)
        DB.table("email_logs").insert({
            "booking_id": booking_id, "email_type": email_type,
            "recipient": recipient, "subject": subject,
            "success": True, "error_message": None,
        }).execute()
        return True, None
    except Exception as exc:
        try:
            DB.table("email_logs").insert({
                "booking_id": booking_id, "email_type": email_type,
                "recipient": recipient, "subject": subject,
                "success": False, "error_message": str(exc)[:2000],
            }).execute()
        except Exception:
            pass
        return False, str(exc)


def chronological_day_items(day, service, bundle, admin=False):
    free_slots, day_schedule = available_slots_from_bundle(day, SERVICES[service], bundle, admin=admin)
    active = bookings_from_bundle(day, bundle, ["active"])
    items = []
    for slot in free_slots:
        items.append({"time": slot, "kind": "free"})
    for booking in active:
        items.append({"time": str(booking["booking_time"])[:5], "kind": "busy", "booking": booking})
    # A szabad és foglalt elemek közös listában, kezdési idő szerint jelennek meg.
    items.sort(key=lambda item: item["time"])
    return items, day_schedule

def public_week_calendar(service):
    week_start = week_navigation("public_week")
    bundle = load_public_week(week_start.isoformat())
    columns = st.columns(7)
    selected = None
    today = datetime.now(TZ).date()
    for day_index, day_column in enumerate(columns):
        day = week_start + timedelta(days=day_index)
        with day_column:
            st.markdown(
                f'<div class="day-head">{DAY_NAMES[day.weekday()]}<br>{day:%m.%d}</div>',
                unsafe_allow_html=True,
            )
            if day < today:
                st.markdown(
                    '<div class="slot-card slot-closed">Nem foglalható</div>',
                    unsafe_allow_html=True,
                )
                continue
            items, day_schedule = chronological_day_items(day, service, bundle)
            if not day_schedule.get("open"):
                st.markdown(
                    '<div class="slot-card slot-closed">Nem foglalható</div>',
                    unsafe_allow_html=True,
                )
                continue
            for item in items:
                if item["kind"] == "busy":
                    st.markdown(
                        f'<div class="slot-card slot-busy">{item["time"]}</div>',
                        unsafe_allow_html=True,
                    )
                elif st.button(
                    item["time"],
                    key=f"free_{day}_{item['time']}",
                    type="primary",
                    use_container_width=True,
                ):
                    selected = (day, item["time"])
            if not items:
                st.markdown(
                    '<div class="slot-card slot-closed">Nincs megfelelő sáv</div>',
                    unsafe_allow_html=True,
                )
    return selected


@st.dialog("Foglalás véglegesítése", width="large")
def booking_dialog(service, selected_date, selected_time):
    st.info(f"{selected_date} {selected_time} | {service} | {SERVICES[service]} perc")
    with st.form("booking_form"):
        col1, col2 = st.columns(2)
        with col1:
            owner = st.text_input("Név *")
            phone = st.text_input("Telefon *")
            email = st.text_input("E-mail *")
        with col2:
            dog_name = st.text_input("Kutya neve *")
            breed = st.text_input("Fajta")
            note = st.text_area("Megjegyzés")
        privacy = st.checkbox("Elfogadom az adatkezelést. *")
        newsletter = st.checkbox("Szeretnék hírlevelet és akciós értesítéseket kapni.", value=False)
        submit = st.form_submit_button("Foglalás elküldése", type="primary", use_container_width=True)
    if not submit:
        return
    owner, phone, email, dog_name = (" ".join(value.split()) for value in (owner, phone, email.lower(), dog_name))
    if len(owner) < 3 or not PHONE_RE.fullmatch(phone) or not EMAIL_RE.fullmatch(email) or not dog_name or not privacy:
        st.error("Ellenőrizd a kötelező mezőket.")
        return
    with st.spinner("Foglalás mentése és e-mail küldése...", show_time=True):
        fresh_bundle = load_public_week(monday_of(selected_date).isoformat())
        fresh_slots, _ = available_slots_from_bundle(selected_date, SERVICES[service], fresh_bundle)
        if selected_time not in fresh_slots:
            st.error("Az időpont időközben foglalttá vált.")
            return
        found = (
            DB.table("dogs").select("id")
            .eq("customer_email", email).ilike("name", dog_name).limit(1).execute().data or []
        )
        dog_payload = {
            "customer_name": owner, "customer_phone": phone, "customer_email": email,
            "breed": breed or None, "notes": note or None,
            "newsletter_consent": newsletter,
            "newsletter_consent_at": datetime.now(TZ).isoformat() if newsletter else None,
        }
        if found:
            dog_id = found[0]["id"]
            DB.table("dogs").update(dog_payload).eq("id", dog_id).execute()
        else:
            dog_payload["name"] = dog_name
            dog_id = DB.table("dogs").insert(dog_payload).execute().data[0]["id"]
        record = {
            "booking_date": selected_date.isoformat(), "booking_time": selected_time,
            "service": service, "duration_min": SERVICES[service], "customer_name": owner,
            "phone": phone, "email": email, "dog_id": dog_id, "status": "active",
        }
        saved = DB.table("bookings").insert(record).execute().data[0]
        clear_public_cache()
        email_ok, email_error = send_confirmation(saved)
    st.success(f"Foglalás rögzítve: {selected_date} {selected_time}")
    if not email_ok:
        st.warning(
            "A foglalás sikerült, de a visszaigazoló e-mail nem ment el. "
            f"Hiba: {email_error}"
        )
    st.session_state["flash_message"] = f"Foglalás rögzítve: {selected_date} {selected_time}"
    st.rerun()


def process_booking_cancellation_page():
    booking_id = str(st.query_params.get("cancel_booking", "")).strip()
    email = str(st.query_params.get("email", "")).strip().lower()
    supplied_token = str(st.query_params.get("token", "")).strip()
    st.title("Foglalás lemondása")
    if not booking_id or not email or not supplied_token:
        st.error("A lemondási link hiányos.")
        return
    try:
        valid = verify_cancellation_token(booking_id, email, supplied_token)
    except Exception as exc:
        st.error(f"A lemondás nincs megfelelően konfigurálva: {exc}")
        return
    if not valid:
        st.error("Érvénytelen vagy módosított lemondási link.")
        return
    rows = (
        DB.table("bookings")
        .select("id,booking_date,booking_time,service,status,customer_name,email")
        .eq("id", booking_id).eq("email", email).limit(1).execute().data or []
    )
    if not rows:
        st.error("A foglalás nem található.")
        return
    booking = rows[0]
    st.info(
        f"Foglalás: {booking['booking_date']} {str(booking['booking_time'])[:5]} | "
        f"{booking['service']}"
    )
    if booking.get("status") == "cancelled":
        st.success("Ezt a foglalást már korábban lemondták.")
        return
    if booking.get("status") != "active":
        st.warning("Ez a foglalás már nem aktív, ezért nem módosítható ezen a linken.")
        return
    st.warning("A lemondás végleges. A felszabaduló időpontot más vendég azonnal lefoglalhatja.")
    if st.button("Igen, lemondom a foglalást", type="primary", use_container_width=True):
        with st.spinner("Foglalás lemondása...", show_time=True):
            DB.table("bookings").update({
                "status": "cancelled",
                "cancelled_at": datetime.now(TZ).isoformat(),
                "updated_at": datetime.now(TZ).isoformat(),
            }).eq("id", booking_id).eq("status", "active").execute()
            clear_public_cache()
        st.success("A foglalást sikeresen lemondtad. Az időpont felszabadult.")


def process_unsubscribe_page():
    email = str(st.query_params.get("unsubscribe", "")).strip().lower()
    supplied_token = str(st.query_params.get("token", "")).strip()
    st.title("Hírlevél leiratkozás")
    if not email or not supplied_token:
        st.error("A leiratkozási link hiányos.")
        return
    try:
        expected_token = unsubscribe_token(email)
    except Exception as exc:
        st.error(f"A leiratkozás nincs megfelelően konfigurálva: {exc}")
        return
    if not hmac.compare_digest(supplied_token, expected_token):
        st.error("Érvénytelen vagy módosított leiratkozási link.")
        return
    with st.spinner("Leiratkozás feldolgozása...", show_time=True):
        matching = DB.table("dogs").select("id,newsletter_consent").eq("customer_email", email).execute().data or []
        if not matching:
            st.info("Ehhez az e-mail-címhez nem található aktív hírlevél-feliratkozás.")
            return
        DB.table("dogs").update({
            "newsletter_consent": False,
            "newsletter_unsubscribed_at": datetime.now(TZ).isoformat(),
        }).eq("customer_email", email).execute()
        try:
            DB.table("newsletter_events").insert({
                "email": email,
                "event_type": "unsubscribe",
                "event_time": datetime.now(TZ).isoformat(),
                "source": "email_link",
            }).execute()
        except Exception:
            pass
    st.success("Sikeresen leiratkoztál a hírlevélről.")
    st.info("A foglalási és időpont-emlékeztető e-maileket ez nem érinti.")


def public_menu():
    if "public_menu" not in st.session_state:
        st.session_state.public_menu = "Időpontfoglalás"
    home_col, booking_col, photos_col = st.columns(3)
    entries = [
        (home_col, "Kezdőlap", "🏠"),
        (booking_col, "Időpontfoglalás", "📅"),
        (photos_col, "Fényképek", "📷"),
    ]
    for column, label, icon in entries:
        if column.button(
            f"{icon}  {label}",
            key=f"public_nav_{label}",
            use_container_width=True,
            type="primary" if st.session_state.public_menu == label else "secondary",
        ):
            st.session_state.public_menu = label
            st.rerun()
    st.divider()
    return st.session_state.public_menu


def public_page():
    st.title("🐶 Kutyakozmetika Miskolc")
    selected_menu = public_menu()
    if selected_menu == "Kezdőlap":
        st.subheader("Üdvözlünk a Kutyakozmetika Miskolc oldalán")
        st.write("Az online foglaláshoz válaszd az Időpontfoglalás menüpontot.")
        return
    if selected_menu == "Fényképek":
        st.subheader("Fényképek")
        st.info("Ide kerülhetnek a szalon és az elkészült frizurák fényképei.")
        return
    if st.session_state.pop("flash_message", None):
        st.success("A foglalás sikeresen rögzítve és a naptár frissítve.")
    service = st.selectbox(
        "1. Válassz szolgáltatást",
        list(SERVICES), index=None, placeholder="Szolgáltatás kiválasztása",
    )
    if not service:
        st.info("A heti naptár a szolgáltatás kiválasztása után jelenik meg.")
        return
    st.caption(f"A kiválasztott szolgáltatás időtartama: {SERVICES[service]} perc")
    st.markdown(
        '<span class="legend" style="background:#22c55e"></span>Szabad &nbsp; '
        '<span class="legend" style="background:#eab308"></span>Foglalt &nbsp; '
        '<span class="legend" style="background:#9ca3af"></span>Nem foglalható',
        unsafe_allow_html=True,
    )
    selected = public_week_calendar(service)
    if selected:
        booking_dialog(service, selected[0], selected[1])


def admin_authenticated():
    if st.session_state.get("admin_authenticated"):
        return True
    with st.form("admin_login"):
        password = st.text_input("Admin jelszó", type="password")
        submit = st.form_submit_button("Belépés")
    if submit and hmac.compare_digest(password, str(secret("ADMIN_PASSWORD", ""))):
        st.session_state.admin_authenticated = True
        st.rerun()
    if submit:
        st.error("Hibás jelszó.")
    return False


def load_booking(booking_id):
    rows = (
        DB.table("bookings")
        .select("*,dog:dogs!bookings_dog_id_fkey(name,breed,notes)")
        .eq("id", booking_id).limit(1).execute().data or []
    )
    return rows[0] if rows else None


def owner_greeting(owner_name):
    first_name = (owner_name or "Gazdi").split()[0]
    return f"Kedves {first_name}!"


def booking_email_template(booking, template_type):
    greeting = owner_greeting(booking.get("customer_name"))
    date_text = booking.get("booking_date", "")
    time_text = str(booking.get("booking_time", ""))[:5]
    service = booking.get("service", "")
    if template_type == "confirmation":
        subject = "Foglalás visszaigazolása"
        body = (
            f"{greeting}\n\n"
            "Ezúton visszaigazoljuk a foglalásodat.\n\n"
            f"Időpont: {date_text} {time_text}\n"
            f"Szolgáltatás: {service}\n\n"
            "Szeretettel várunk!\n"
            "Kutyakozmetika Miskolc"
        )
    else:
        subject = "Emlékeztető a kutyakozmetikai időpontról"
        body = (
            f"{greeting}\n\n"
            "Emlékeztetünk a közelgő időpontodra.\n\n"
            f"Időpont: {date_text} {time_text}\n"
            f"Szolgáltatás: {service}\n\n"
            "Ha nem tudsz eljönni, kérjük, jelezd időben.\n"
            "Kutyakozmetika Miskolc"
        )
    # Kötelező ellenőrzési pont: mindkét foglalási sablon megkapja a lemondási linket.
    return subject, append_cancellation_footer(body, booking)


@st.dialog("E-mail küldése a gazdinak", width="large")
def editor_custom_email_dialog(booking):
    recipient = (booking.get("email") or "").strip()
    greeting = owner_greeting(booking.get("customer_name"))
    st.caption(f"Címzett: {recipient}")
    subject = st.text_input("Tárgy", value="Üzenet a Kutyakozmetika Miskolctól", key=f"editor_mail_subject_{booking['id']}")
    salutation = st.selectbox(
        "Köszönés",
        [greeting, "Kedves Gazdi!", "Tisztelt Ügyfelünk!", "Egyedi köszönés"],
        key=f"editor_mail_salutation_{booking['id']}",
    )
    custom_salutation = st.text_input(
        "Egyedi köszönés",
        value=greeting,
        disabled=salutation != "Egyedi köszönés",
        key=f"editor_mail_custom_salutation_{booking['id']}",
    )
    message = st.text_area("Üzenet", height=220, key=f"editor_mail_message_{booking['id']}")
    closing = st.text_area(
        "Elköszönés",
        value="Üdvözlettel,\nKutyakozmetika Miskolc",
        height=90,
        key=f"editor_mail_closing_{booking['id']}",
    )
    if st.button("E-mail elküldése", type="primary", use_container_width=True, disabled=not(recipient and subject.strip() and message.strip()), key=f"editor_mail_send_{booking['id']}"):
        selected_salutation = custom_salutation if salutation == "Egyedi köszönés" else salutation
        body = f"{selected_salutation}\n\n{message.strip()}\n\n{closing.strip()}"
        with st.spinner("E-mail küldése...", show_time=True):
            ok, error = send_custom_email(recipient, subject.strip(), body, "manual", booking.get("id"))
        st.success("Az e-mail elküldve.") if ok else st.error(f"Küldési hiba: {error}")


@st.dialog("Foglalási értesítés", width="large")
def editor_booking_email_dialog(booking, template_type):
    subject, body = booking_email_template(booking, template_type)
    label = "Visszaigazolás elküldése" if template_type == "confirmation" else "Emlékeztető elküldése"
    st.text_input("Tárgy", value=subject, disabled=True)
    st.text_area("Sablon és lemondási link", value=body, height=310, disabled=True)
    if st.button(label, type="primary", use_container_width=True, key=f"editor_template_send_{template_type}_{booking['id']}"):
        with st.spinner("E-mail küldése...", show_time=True):
            ok, error = send_custom_email(
                booking.get("email", ""), subject, body, template_type, booking.get("id")
            )
            if ok:
                timestamp_field = "confirmation_sent_at" if template_type == "confirmation" else "reminder_sent_at"
                DB.table("bookings").update({
                    timestamp_field: datetime.now(TZ).isoformat(),
                    "last_email_error": None,
                }).eq("id", booking["id"]).execute()
        st.success("Az e-mail elküldve.") if ok else st.error(f"Küldési hiba: {error}")


@st.dialog("Foglalás törlése", width="small")
def editor_delete_booking_dialog(booking):
    st.warning(
        f"Biztosan törlöd ezt a foglalást?\n\n"
        f"{booking.get('customer_name', '')} | {booking.get('booking_date', '')} "
        f"{str(booking.get('booking_time', ''))[:5]} | {booking.get('service', '')}"
    )
    if st.button("Igen, foglalás törlése", type="primary", use_container_width=True, key=f"editor_delete_confirm_{booking['id']}"):
        DB.table("bookings").update({
            "status": "cancelled",
            "cancelled_at": datetime.now(TZ).isoformat(),
            "updated_at": datetime.now(TZ).isoformat(),
        }).eq("id", booking["id"]).execute()
        clear_public_cache()
        st.session_state["admin_flash"] = "A foglalás törölve, az időpont felszabadult."
        st.rerun()


@st.dialog("Foglalás szerkesztése", width="large")
def edit_booking_dialog(booking_id):
    booking = load_booking(booking_id)
    if not booking:
        st.error("A foglalás nem található.")
        return
    dog = booking.get("dog") or {}
    selected_date = st.date_input("Dátum", date.fromisoformat(booking["booking_date"]), key=f"edit_date_{booking_id}")
    service = st.selectbox(
        "Szolgáltatás", list(SERVICES), index=list(SERVICES).index(booking["service"]),
        key=f"edit_service_{booking_id}",
    )
    status = st.selectbox(
        "Státusz", list(STATUS), index=list(STATUS).index(booking["status"]),
        format_func=lambda value: STATUS[value], key=f"edit_status_{booking_id}",
    )
    edit_week = monday_of(selected_date)
    edit_bundle = load_admin_week(edit_week)
    available, _ = available_slots_from_bundle(
        selected_date, SERVICES[service], edit_bundle, exclude_id=booking_id, admin=True
    )
    current_time = str(booking["booking_time"])[:5]
    choices = sorted(set(available + [current_time]))
    selected_time = st.selectbox(
        "Időpont", choices, index=choices.index(current_time), key=f"edit_time_{booking_id}"
    )
    col1, col2 = st.columns(2)
    with col1:
        customer_name = st.text_input("Ügyfél neve", booking["customer_name"])
        phone = st.text_input("Telefon", booking["phone"])
        email = st.text_input("E-mail", booking.get("email") or "")
    with col2:
        dog_name = st.text_input("Kutya neve", dog.get("name") or "")
        breed = st.text_input("Fajta", dog.get("breed") or "")
        notes = st.text_area("Megjegyzés", dog.get("notes") or "")
    if st.button("Módosítások mentése", type="primary", use_container_width=True, key=f"editor_save_{booking_id}"):
        if not PHONE_RE.fullmatch(phone) or not EMAIL_RE.fullmatch(email):
            st.error("Hibás telefonszám vagy e-mail-cím.")
            return
        valid_slots, _ = available_slots_from_bundle(
            selected_date, SERVICES[service], load_admin_week(edit_week), exclude_id=booking_id, admin=True
        )
        unchanged = (
            selected_date.isoformat() == booking["booking_date"]
            and selected_time == current_time
            and service == booking["service"]
        )
        if status == "active" and selected_time not in valid_slots and not unchanged:
            st.error("A kiválasztott új időpont nem szabad.")
            return
        with st.spinner("Módosítások mentése...", show_time=True):
            DB.table("bookings").update({
                "booking_date": selected_date.isoformat(), "booking_time": selected_time,
                "service": service, "duration_min": SERVICES[service], "status": status,
                "customer_name": customer_name.strip(), "phone": phone.strip(),
                "email": email.strip().lower(), "updated_at": datetime.now(TZ).isoformat(),
            }).eq("id", booking_id).execute()
            if booking.get("dog_id"):
                DB.table("dogs").update({
                    "name": dog_name.strip(), "breed": breed.strip() or None,
                    "notes": notes.strip() or None, "customer_name": customer_name.strip(),
                    "customer_phone": phone.strip(), "customer_email": email.strip().lower(),
                }).eq("id", booking["dog_id"]).execute()
            clear_public_cache()
        st.session_state["admin_flash"] = "A módosítások elmentve, a naptár frissítve."
        st.rerun()
    st.divider()
    st.markdown("#### Kommunikáció és foglalási műveletek")
    action_state_key = f"editor_action_{booking_id}"
    action1, action2, action3, action4 = st.columns(4)
    if action1.button("E-mail küldése", use_container_width=True, key=f"editor_custom_mail_{booking_id}"):
        st.session_state[action_state_key] = "custom_email"
    if action2.button("Visszaigazolás", use_container_width=True, key=f"editor_confirmation_{booking_id}"):
        st.session_state[action_state_key] = "confirmation"
    if action3.button("Emlékeztető", use_container_width=True, key=f"editor_reminder_{booking_id}"):
        st.session_state[action_state_key] = "reminder"
    if action4.button("Foglalás törlése", use_container_width=True, key=f"editor_delete_{booking_id}"):
        st.session_state[action_state_key] = "delete"

    selected_action = st.session_state.get(action_state_key)
    current_booking = load_booking(booking_id)

    if selected_action == "custom_email":
        st.markdown("##### Egyedi e-mail")
        recipient = (current_booking.get("email") or "").strip()
        greeting = owner_greeting(current_booking.get("customer_name"))
        st.caption(f"Címzett: {recipient}")
        subject = st.text_input(
            "Tárgy",
            value="Üzenet a Kutyakozmetika Miskolctól",
            key=f"inline_mail_subject_{booking_id}",
        )
        salutation = st.selectbox(
            "Köszönés",
            [greeting, "Kedves Gazdi!", "Tisztelt Ügyfelünk!", "Egyedi köszönés"],
            key=f"inline_mail_salutation_{booking_id}",
        )
        custom_salutation = st.text_input(
            "Egyedi köszönés",
            value=greeting,
            disabled=salutation != "Egyedi köszönés",
            key=f"inline_mail_custom_salutation_{booking_id}",
        )
        message = st.text_area("Üzenet", height=190, key=f"inline_mail_message_{booking_id}")
        closing = st.text_area(
            "Elköszönés",
            value="Üdvözlettel,\nKutyakozmetika Miskolc",
            height=80,
            key=f"inline_mail_closing_{booking_id}",
        )
        send_col, close_col = st.columns(2)
        if send_col.button(
            "E-mail elküldése",
            type="primary",
            use_container_width=True,
            disabled=not(recipient and subject.strip() and message.strip()),
            key=f"inline_mail_send_{booking_id}",
        ):
            selected_salutation = custom_salutation if salutation == "Egyedi köszönés" else salutation
            body = f"{selected_salutation}\n\n{message.strip()}\n\n{closing.strip()}"
            with st.spinner("E-mail küldése...", show_time=True):
                ok, error = send_custom_email(
                    recipient, subject.strip(), body, "manual", current_booking.get("id")
                )
            st.success("Az e-mail elküldve.") if ok else st.error(f"Küldési hiba: {error}")
        if close_col.button("Művelet bezárása", use_container_width=True, key=f"inline_mail_close_{booking_id}"):
            st.session_state.pop(action_state_key, None)
            st.rerun()

    elif selected_action in ("confirmation", "reminder"):
        template_type = selected_action
        subject, body = booking_email_template(current_booking, template_type)
        heading = "Visszaigazolás újraküldése" if template_type == "confirmation" else "Emlékeztető küldése"
        st.markdown(f"##### {heading}")
        st.text_input(
            "Tárgy",
            value=subject,
            disabled=True,
            key=f"inline_template_subject_{template_type}_{booking_id}",
        )
        st.text_area(
            "Sablon és lemondási link",
            value=body,
            height=300,
            disabled=True,
            key=f"inline_template_body_{template_type}_{booking_id}",
        )
        send_col, close_col = st.columns(2)
        if send_col.button(
            heading,
            type="primary",
            use_container_width=True,
            key=f"inline_template_send_{template_type}_{booking_id}",
        ):
            with st.spinner("E-mail küldése...", show_time=True):
                ok, error = send_custom_email(
                    current_booking.get("email", ""),
                    subject,
                    body,
                    template_type,
                    current_booking.get("id"),
                )
                if ok:
                    timestamp_field = (
                        "confirmation_sent_at"
                        if template_type == "confirmation"
                        else "reminder_sent_at"
                    )
                    DB.table("bookings").update({
                        timestamp_field: datetime.now(TZ).isoformat(),
                        "last_email_error": None,
                    }).eq("id", current_booking["id"]).execute()
            st.success("Az e-mail elküldve.") if ok else st.error(f"Küldési hiba: {error}")
        if close_col.button(
            "Művelet bezárása",
            use_container_width=True,
            key=f"inline_template_close_{template_type}_{booking_id}",
        ):
            st.session_state.pop(action_state_key, None)
            st.rerun()

    elif selected_action == "delete":
        st.markdown("##### Foglalás törlése")
        st.warning(
            f"Biztosan törlöd ezt a foglalást?\n\n"
            f"{current_booking.get('customer_name', '')} | "
            f"{current_booking.get('booking_date', '')} "
            f"{str(current_booking.get('booking_time', ''))[:5]} | "
            f"{current_booking.get('service', '')}"
        )
        delete_col, close_col = st.columns(2)
        if delete_col.button(
            "Igen, foglalás törlése",
            type="primary",
            use_container_width=True,
            key=f"inline_delete_confirm_{booking_id}",
        ):
            DB.table("bookings").update({
                "status": "cancelled",
                "cancelled_at": datetime.now(TZ).isoformat(),
                "updated_at": datetime.now(TZ).isoformat(),
            }).eq("id", current_booking["id"]).execute()
            clear_public_cache()
            st.session_state.pop(action_state_key, None)
            st.session_state["admin_flash"] = "A foglalás törölve, az időpont felszabadult."
            st.rerun()
        if close_col.button("Művelet bezárása", use_container_width=True, key=f"inline_delete_close_{booking_id}"):
            st.session_state.pop(action_state_key, None)
            st.rerun()


@st.dialog("Adminisztrátori foglalás rögzítése", width="large")
def admin_free_slot_booking_dialog(selected_date, selected_time):
    st.info(f"Kiválasztott időpont: {selected_date} {selected_time}")
    service = st.selectbox(
        "Szolgáltatás",
        list(SERVICES),
        key=f"admin_new_service_{selected_date}_{selected_time}",
    )
    with st.form(f"admin_new_booking_{selected_date}_{selected_time}"):
        col1, col2 = st.columns(2)
        with col1:
            owner = st.text_input("Név *")
            phone = st.text_input("Telefon *")
            email = st.text_input("E-mail *")
        with col2:
            dog_name = st.text_input("Kutya neve *")
            breed = st.text_input("Fajta")
            note = st.text_area("Megjegyzés")
        newsletter = st.checkbox(
            "A gazdi hozzájárul a hírlevélhez és akciós értesítésekhez.",
            value=False,
        )
        send_email = st.checkbox("Visszaigazoló e-mail küldése", value=True)
        submit = st.form_submit_button(
            "Foglalás rögzítése",
            type="primary",
            use_container_width=True,
        )
    if not submit:
        return

    owner, phone, email, dog_name = (
        " ".join(value.split())
        for value in (owner, phone, email.lower(), dog_name)
    )
    if len(owner) < 3 or not PHONE_RE.fullmatch(phone) or not EMAIL_RE.fullmatch(email) or not dog_name:
        st.error("Ellenőrizd a kötelező mezőket.")
        return

    selected_week = monday_of(selected_date)
    fresh_bundle = load_admin_week(selected_week)
    valid_slots, _ = available_slots_from_bundle(
        selected_date,
        SERVICES[service],
        fresh_bundle,
        admin=True,
    )
    if selected_time not in valid_slots:
        st.error("A kiválasztott időpont ehhez a szolgáltatáshoz már nem szabad.")
        return

    with st.spinner("Adminisztrátori foglalás mentése...", show_time=True):
        found = (
            DB.table("dogs").select("id")
            .eq("customer_email", email)
            .ilike("name", dog_name)
            .limit(1).execute().data or []
        )
        dog_payload = {
            "customer_name": owner,
            "customer_phone": phone,
            "customer_email": email,
            "breed": breed or None,
            "notes": note or None,
            "newsletter_consent": newsletter,
            "newsletter_consent_at": datetime.now(TZ).isoformat() if newsletter else None,
        }
        if found:
            dog_id = found[0]["id"]
            DB.table("dogs").update(dog_payload).eq("id", dog_id).execute()
        else:
            dog_payload["name"] = dog_name
            dog_id = DB.table("dogs").insert(dog_payload).execute().data[0]["id"]

        record = {
            "booking_date": selected_date.isoformat(),
            "booking_time": selected_time,
            "service": service,
            "duration_min": SERVICES[service],
            "customer_name": owner,
            "phone": phone,
            "email": email,
            "dog_id": dog_id,
            "status": "active",
        }
        saved = DB.table("bookings").insert(record).execute().data[0]
        clear_public_cache()
        email_ok, email_error = (True, None)
        if send_email:
            email_ok, email_error = send_confirmation(saved)

    st.session_state["admin_flash"] = (
        f"Az adminisztrátori foglalás rögzítve: {selected_date} {selected_time}."
    )
    if send_email and not email_ok:
        st.warning(f"A foglalás elkészült, de az e-mail nem ment ki: {email_error}")
        return
    st.rerun()


@st.fragment
def admin_calendar_fragment():
    week_start = week_navigation("admin_week")
    color_mode = st.radio(
        "Színezés", ["Státusz szerint", "Szolgáltatás szerint"], horizontal=True
    )
    if color_mode == "Státusz szerint":
        legend_items = [(STATUS_COLORS[key], STATUS[key]) for key in STATUS]
    else:
        legend_items = [(SERVICE_COLORS[service], service) for service in SERVICES]
    legend_items.append(("#22c55e", "Szabad"))
    legend_html = "".join(
        f'<span class="admin-legend-item"><span class="admin-legend-dot" '
        f'style="background:{color}"></span>{html.escape(label)}</span>'
        for color, label in legend_items
    )
    st.markdown(
        f'<div class="admin-legend-row">{legend_html}</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Heti naptár frissítése...", show_time=True):
        bundle = load_admin_week(week_start)

    day_data = []
    opening_values = []
    closing_values = []
    for day_index in range(7):
        day = week_start + timedelta(days=day_index)
        schedule = schedule_from_bundle(day, bundle)
        bookings = bookings_from_bundle(day, bundle)
        day_data.append((day, schedule, bookings))
        if schedule.get("open") and schedule.get("from") and schedule.get("to"):
            opening_values.append(minute_of_day(schedule["from"]))
            closing_values.append(minute_of_day(schedule["to"]))

    timeline_start = min(opening_values) if opening_values else 9 * 60
    timeline_end = max(closing_values) if closing_values else 17 * 60
    cell_minutes = 30
    cell_height = 40
    timeline_height = ((timeline_end - timeline_start) // cell_minutes) * cell_height

    time_column, *columns = st.columns([0.42, 1, 1, 1, 1, 1, 1, 1], gap="small")
    st.markdown(
        f"""
        <style>
        div[data-testid="stHorizontalBlock"]:has(.admin-timeline-head) > div[data-testid="stColumn"] {{
            min-height: {timeline_height + 82}px;
            border: 1px solid #dbe3ec;
            border-radius: 10px;
            padding: 7px;
            background: transparent;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    with time_column:
        st.markdown('<div class="admin-time-axis-head">Idő</div>', unsafe_allow_html=True)
        time_labels = []
        label_minute = timeline_start
        while label_minute <= timeline_end:
            label_top = round((label_minute - timeline_start) / 30 * 43)
            time_labels.append(
                f'<span class="admin-time-label" style="top:{label_top}px">'
                f'{label_minute // 60:02d}:00</span>'
            )
            label_minute += 60
        st.markdown(
            f'<div class="admin-time-axis" style="height:{timeline_height}px">'
            f'{"".join(time_labels)}</div>',
            unsafe_allow_html=True,
        )

    for day_column, (day, day_schedule, bookings) in zip(columns, day_data):
        with day_column:
            capacity = (
                minute_of_day(day_schedule["to"]) - minute_of_day(day_schedule["from"])
                if day_schedule.get("open") and day_schedule.get("from") and day_schedule.get("to")
                else 0
            )
            used = sum(
                int(item.get("duration_min") or 0)
                for item in bookings
                if item.get("status") == "active"
            )
            percentage = round(100 * used / capacity) if capacity else 0
            st.markdown(
                f'<div class="day-head admin-timeline-head">'
                f'{DAY_NAMES[day.weekday()]} {day:%m.%d}<br>'
                f'{used}/{capacity} perc ({percentage}%)</div>',
                unsafe_allow_html=True,
            )

            schedule_open = (
                day_schedule.get("open")
                and day_schedule.get("from")
                and day_schedule.get("to")
            )
            opening = minute_of_day(day_schedule["from"]) if schedule_open else timeline_start
            closing = minute_of_day(day_schedule["to"]) if schedule_open else timeline_end

            if not schedule_open:
                st.markdown(
                    '<div class="slot-card slot-closed admin-timeline-closed">Zárva</div>',
                    unsafe_allow_html=True,
                )
                remaining = max(timeline_height - 42, 0)
                st.markdown(
                    f'<div class="admin-timeline-spacer" style="height:{remaining}px"></div>',
                    unsafe_allow_html=True,
                )
                continue

            if opening > timeline_start:
                top_gap = round((opening - timeline_start) / cell_minutes * cell_height)
                st.markdown(
                    f'<div class="admin-timeline-spacer" style="height:{top_gap}px"></div>',
                    unsafe_allow_html=True,
                )

            free_slots, _ = available_slots_from_bundle(day, 30, bundle, admin=True)
            free_set = set(free_slots)
            booking_by_start = {}
            for booking in bookings:
                booking_by_start.setdefault(
                    minute_of_day(booking["booking_time"]), booking
                )

            cursor = opening
            while cursor < closing:
                time_text = f"{cursor // 60:02d}:{cursor % 60:02d}"
                booking = booking_by_start.get(cursor)

                if booking:
                    duration = max(int(booking.get("duration_min") or 30), 30)
                    duration = min(duration, closing - cursor)
                    card_height = max(
                        round(duration / cell_minutes * cell_height),
                        cell_height,
                    )
                    color = (
                        STATUS_COLORS.get(booking["status"], "#64748b")
                        if color_mode == "Státusz szerint"
                        else SERVICE_COLORS.get(booking["service"], "#64748b")
                    )
                    button_key = f"edit_{booking['id']}"
                    st.markdown(
                        f'<style>'
                        f'.st-key-{button_key} button {{'
                        f'background-color:{color} !important;'
                        f'border-color:{color} !important;'
                        f'color:white !important;'
                        f'font-weight:700 !important;'
                        f'height:{card_height}px !important;'
                        f'min-height:{card_height}px !important;'
                        f'max-height:{card_height}px !important;'
                        f'white-space:pre-line !important;'
                        f'overflow-wrap:anywhere !important;'
                        f'line-height:1.12 !important;'
                        f'font-size:.70rem !important;'
                        f'overflow:visible !important;'
                        f'}}'
                        f'.st-key-{button_key} button:hover {{'
                        f'filter:brightness(0.92); border-color:{color} !important;'
                        f'}}'
                        f'</style>',
                        unsafe_allow_html=True,
                    )
                    dog = booking.get("dog") or {}
                    owner_name = booking.get("customer_name") or "Névtelen gazdi"
                    dog_name = dog.get("name") or "Nincs kutyanév"
                    label = (
                        f"{time_text} {owner_name}\n"
                        f"{dog_name}\n{booking['service']}"
                    )
                    if st.button(
                        label,
                        key=button_key,
                        use_container_width=True,
                    ):
                        edit_booking_dialog(booking["id"])
                    cursor += duration
                    continue

                if time_text in free_set:
                    free_key = f"admin_free_{day.isoformat()}_{cursor}"
                    if st.button(
                        f"{time_text} Szabad",
                        key=free_key,
                        type="primary",
                        use_container_width=True,
                    ):
                        admin_free_slot_booking_dialog(day, time_text)
                else:
                    st.markdown(
                        f'<div class="admin-timeline-spacer" '
                        f'style="height:{cell_height}px"></div>',
                        unsafe_allow_html=True,
                    )
                cursor += cell_minutes

            if closing < timeline_end:
                bottom_gap = round((timeline_end - closing) / cell_minutes * cell_height)
                st.markdown(
                    f'<div class="admin-timeline-spacer" style="height:{bottom_gap}px"></div>',
                    unsafe_allow_html=True,
                )

def normalize_email(value):
    return (value or "").strip().lower()


def normalize_phone(value):
    return re.sub(r"[^0-9+]", "", value or "")


def contact_key(row):
    email = normalize_email(row.get("customer_email"))
    phone = normalize_phone(row.get("customer_phone"))
    return email or f"phone:{phone}"


def load_contacts():
    return (
        DB.table("dogs")
        .select("id,name,breed,customer_name,customer_phone,customer_email,notes,newsletter_consent,newsletter_consent_at,newsletter_unsubscribed_at")
        .order("customer_name")
        .execute().data or []
    )


def load_owner_bookings(email, phone):
    query = DB.table("bookings").select("booking_date,booking_time,service,status,dog:dogs!bookings_dog_id_fkey(name,breed)")
    if email:
        return query.eq("email", email).order("booking_date", desc=True).execute().data or []
    if phone:
        return query.eq("phone", phone).order("booking_date", desc=True).execute().data or []
    return []


def latest_active_booking(bookings):
    today_iso = datetime.now(TZ).date().isoformat()
    active = [
        item for item in bookings
        if item.get("status") == "active" and item.get("booking_date", "") >= today_iso
    ]
    active.sort(key=lambda item: (item.get("booking_date", ""), str(item.get("booking_time", ""))))
    return active[0] if active else None


def owner_greeting(owner_name):
    first_name = (owner_name or "Gazdi").split()[0]
    return f"Kedves {first_name}!"


def booking_template(owner_name, booking, template_type):
    greeting = owner_greeting(owner_name)
    date_text = booking.get("booking_date", "")
    time_text = str(booking.get("booking_time", ""))[:5]
    service = booking.get("service", "")
    if template_type == "confirmation":
        subject = "Foglalás visszaigazolása"
        body = f"{greeting}\n\nEzúton visszaigazoljuk a foglalásodat.\n\nIdőpont: {date_text} {time_text}\nSzolgáltatás: {service}\n\nSzeretettel várunk!\nKutyakozmetika Miskolc"
    else:
        subject = "Emlékeztető a kutyakozmetikai időpontról"
        body = f"{greeting}\n\nEmlékeztetünk a közelgő időpontodra.\n\nIdőpont: {date_text} {time_text}\nSzolgáltatás: {service}\n\nHa nem tudsz eljönni, kérjük, jelezd időben.\nKutyakozmetika Miskolc"
    body = append_cancellation_footer(body, booking)
    return subject, body


@st.dialog("Levél küldése a gazdinak", width="large")
def owner_email_dialog(owner_name, recipient):
    greeting = owner_greeting(owner_name)
    subject = st.text_input("Tárgy", value="Üzenet a Kutyakozmetika Miskolctól")
    intro = st.selectbox("Alap köszönés", [greeting, "Kedves Gazdi!", "Tisztelt Ügyfelünk!", "Egyedi köszönés"])
    custom_intro = st.text_input("Egyedi köszönés", value=greeting, disabled=intro != "Egyedi köszönés")
    message = st.text_area("Szerkeszthető üzenet", height=220, placeholder="Írd ide az üzenetet...")
    closing = st.text_area("Elköszönés", value="Üdvözlettel,\nKutyakozmetika Miskolc", height=90)
    if st.button("Levél elküldése", type="primary", use_container_width=True, disabled=not(subject.strip() and message.strip())):
        salutation = custom_intro if intro == "Egyedi köszönés" else intro
        body = f"{salutation}\n\n{message.strip()}\n\n{closing.strip()}"
        with st.spinner("Levél küldése...", show_time=True):
            ok, error = send_custom_email(recipient, subject.strip(), body, "manual")
        st.success("A levél elküldve.") if ok else st.error(f"Küldési hiba: {error}")


@st.dialog("Foglalási művelet", width="large")
def booking_action_dialog(owner_name, recipient, booking, action):
    if not booking:
        st.error("A gazdinak nincs aktív foglalása.")
        return
    template_type = "confirmation" if action == "confirmation" else "reminder"
    subject, body = booking_template(owner_name, booking, template_type)
    st.text_input("Tárgy", value=subject, disabled=True)
    st.text_area("Sablon szöveg", value=body, height=260, disabled=True)
    label = "Visszaigazolás elküldése" if action == "confirmation" else "Emlékeztető elküldése"
    if st.button(label, type="primary", use_container_width=True):
        with st.spinner("E-mail küldése...", show_time=True):
            ok, error = send_custom_email(recipient, subject, body, template_type, booking.get("id"))
            if ok:
                field = "confirmation_sent_at" if action == "confirmation" else "reminder_sent_at"
                DB.table("bookings").update({field: datetime.now(TZ).isoformat(), "last_email_error": None}).eq("id", booking["id"]).execute()
        st.success("Az e-mail elküldve.") if ok else st.error(f"Küldési hiba: {error}")


@st.dialog("Foglalás törlése", width="small")
def delete_booking_dialog(owner_name, booking):
    if not booking:
        st.error("A gazdinak nincs aktív foglalása.")
        return
    st.warning(f"Törlöd ezt a foglalást?\n\n{owner_name} | {booking['booking_date']} {str(booking['booking_time'])[:5]} | {booking['service']}")
    if st.button("Igen, foglalás törlése", type="primary", use_container_width=True):
        DB.table("bookings").update({"status": "cancelled", "updated_at": datetime.now(TZ).isoformat()}).eq("id", booking["id"]).execute()
        clear_public_cache()
        st.session_state["admin_flash"] = "A foglalás lemondva, az időpont felszabadult."
        st.rerun()


def duplicate_groups(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(contact_key(row), []).append(row)
    return {key: values for key, values in grouped.items() if key and len(values) > 1}


def duplicate_admin(rows):
    st.subheader("Duplikátumkezelés")
    groups = duplicate_groups(rows)
    exact_duplicates = []
    for key, values in groups.items():
        seen = {}
        for row in values:
            dog_key = (str(row.get("name") or "").strip().casefold(), str(row.get("breed") or "").strip().casefold())
            seen.setdefault(dog_key, []).append(row)
        for dog_key, duplicates in seen.items():
            if dog_key[0] and len(duplicates) > 1:
                exact_duplicates.append((key, dog_key, duplicates))
    st.caption(f"Azonos gazdielérhetőséggel rendelkező csoportok: {len(groups)} | Valószínű duplikált kutyarekordok: {len(exact_duplicates)}")
    if not exact_duplicates:
        st.success("Nem található automatikusan egyesíthető duplikált kutyarekord.")
        return
    for index, (owner_key, dog_key, duplicates) in enumerate(exact_duplicates):
        with st.expander(f"{duplicates[0].get('customer_name','')} | {duplicates[0].get('name','')} | {len(duplicates)} rekord"):
            st.write("Rekordazonosítók:", ", ".join(item["id"] for item in duplicates))
            keep_options = {f"{item['id']} | {item.get('name','')} | {item.get('breed') or ''}": item["id"] for item in duplicates}
            keep_label = st.selectbox("Megtartandó rekord", list(keep_options), key=f"keep_duplicate_{index}")
            if st.button("Duplikátumok egyesítése", key=f"merge_duplicate_{index}", type="primary"):
                keep_id = keep_options[keep_label]
                remove_ids = [item["id"] for item in duplicates if item["id"] != keep_id]
                with st.spinner("Duplikátumok egyesítése...", show_time=True):
                    DB.rpc("merge_duplicate_dogs", {"keep_dog_id": keep_id, "remove_dog_ids": remove_ids}).execute()
                st.success("A duplikált rekordok egyesítve.")
                st.rerun()


@st.dialog("E-mail küldése a gazdinak", width="large")
def owner_record_email_dialog(owner_name, recipient, owner_key):
    greeting = owner_greeting(owner_name)
    st.caption(f"Címzett: {recipient}")
    subject = st.text_input(
        "Tárgy",
        value="Üzenet a Kutyakozmetika Miskolctól",
        key=f"owner_record_subject_{owner_key}",
    )
    salutation = st.selectbox(
        "Köszönés",
        [greeting, "Kedves Gazdi!", "Tisztelt Ügyfelünk!", "Egyedi köszönés"],
        key=f"owner_record_salutation_{owner_key}",
    )
    custom_salutation = st.text_input(
        "Egyedi köszönés",
        value=greeting,
        disabled=salutation != "Egyedi köszönés",
        key=f"owner_record_custom_salutation_{owner_key}",
    )
    message = st.text_area("Üzenet", height=220, key=f"owner_record_message_{owner_key}")
    closing = st.text_area(
        "Elköszönés",
        value="Üdvözlettel,\nKutyakozmetika Miskolc",
        height=90,
        key=f"owner_record_closing_{owner_key}",
    )
    if st.button(
        "E-mail elküldése",
        type="primary",
        use_container_width=True,
        disabled=not (recipient and subject.strip() and message.strip()),
        key=f"owner_record_send_{owner_key}",
    ):
        selected_salutation = custom_salutation if salutation == "Egyedi köszönés" else salutation
        body = f"{selected_salutation}\n\n{message.strip()}\n\n{closing.strip()}"
        with st.spinner("E-mail küldése...", show_time=True):
            ok, error = send_custom_email(recipient, subject.strip(), body, "manual")
        st.success("Az e-mail elküldve.") if ok else st.error(f"Küldési hiba: {error}")


def formatted_owner_history(bookings):
    result = []
    for booking in bookings:
        dog = booking.get("dog") or {}
        result.append({
            "Dátum": booking.get("booking_date"),
            "Időpont": str(booking.get("booking_time") or "")[:5],
            "Szolgáltatás": booking.get("service"),
            "Státusz": STATUS.get(booking.get("status"), booking.get("status")),
            "Kutya": dog.get("name") or "",
            "Fajta": dog.get("breed") or "",
        })
    return result


def dog_booking_history(dog_id):
    rows = (
        DB.table("bookings")
        .select("booking_date,booking_time,service,status")
        .eq("dog_id", dog_id)
        .order("booking_date", desc=True)
        .execute().data or []
    )
    return [
        {
            "Dátum": row.get("booking_date"),
            "Időpont": str(row.get("booking_time") or "")[:5],
            "Szolgáltatás": row.get("service"),
            "Státusz": STATUS.get(row.get("status"), row.get("status")),
        }
        for row in rows
    ]


def grouped_contacts():
    groups = {}
    for row in load_contacts():
        groups.setdefault(contact_key(row), []).append(row)
    return groups


def owners_admin_section():
    st.subheader("Gazdik")
    groups = grouped_contacts()
    search = st.text_input("Keresés gazdi, e-mail, telefon vagy kutya alapján", key="owner_search")
    if search:
        needle = search.casefold()
        groups = {
            key: dogs for key, dogs in groups.items()
            if needle in " ".join([
                dogs[0].get("customer_name") or "", dogs[0].get("customer_email") or "",
                dogs[0].get("customer_phone") or "",
                " ".join(dog.get("name") or "" for dog in dogs),
            ]).casefold()
        }
    st.caption(f"Gazdik száma: {len(groups)}")
    for owner_key, dogs in sorted(groups.items(), key=lambda item: str(item[1][0].get("customer_name") or "").casefold()):
        primary = dogs[0]
        email = normalize_email(primary.get("customer_email"))
        phone = primary.get("customer_phone") or ""
        owner_name = primary.get("customer_name") or "Gazdi"
        focus = st.session_state.get("focus_owner_key") == owner_key
        with st.expander(f"{'👉 ' if focus else ''}{owner_name} | {email or phone} | {len(dogs)} kutya", expanded=focus):
            with st.form(f"owner_edit_{hashlib.sha256(owner_key.encode()).hexdigest()[:12]}"):
                edited_name = st.text_input("Név", owner_name)
                edited_phone = st.text_input("Telefon", phone)
                edited_email = st.text_input("E-mail", email)
                save_col, email_col = st.columns(2)
                save = save_col.form_submit_button("Gazdi adatainak mentése", use_container_width=True)
                send = email_col.form_submit_button("✉️ E-mail küldése", use_container_width=True)
            if save:
                for dog in dogs:
                    DB.table("dogs").update({
                        "customer_name": edited_name.strip(),
                        "customer_phone": edited_phone.strip(),
                        "customer_email": edited_email.strip().lower(),
                    }).eq("id", dog["id"]).execute()
                booking_query = DB.table("bookings").update({
                    "customer_name": edited_name.strip(),
                    "phone": edited_phone.strip(),
                    "email": edited_email.strip().lower(),
                })
                if email:
                    booking_query.eq("email", email).execute()
                else:
                    booking_query.eq("phone", phone).execute()
                st.rerun()
            if send:
                owner_record_email_dialog(owner_name, email, hashlib.sha256(owner_key.encode()).hexdigest()[:12])
            st.markdown("**Kutyák és megjegyzések**")
            for dog in sorted(dogs, key=lambda item: str(item.get("name") or "").casefold()):
                st.write(
                    f"• **{dog.get('name') or ''}** | {dog.get('breed') or 'ismeretlen fajta'} | "
                    f"Megjegyzés: {dog.get('notes') or 'Nincs'}"
                )
                if st.button(
                    f"🐕 {dog.get('name') or 'Kutya'} megnyitása",
                    key=f"owner_to_dog_{dog['id']}",
                ):
                    st.session_state.admin_section = "Kutyák"
                    st.session_state.focus_dog_id = dog["id"]
                    st.rerun()
            bookings = load_owner_bookings(email, phone)
            st.markdown("**Foglalási előzmények**")
            history = formatted_owner_history(bookings)
            if history:
                st.dataframe(history, use_container_width=True, hide_index=True)
            else:
                st.info("Nincs foglalási előzmény.")


def dogs_admin_section():
    st.subheader("Kutyák")
    rows = load_contacts()
    search = st.text_input("Keresés kutyanév, fajta, megjegyzés vagy gazdi alapján", key="dog_search")
    if search:
        needle = search.casefold()
        rows = [
            row for row in rows
            if needle in " ".join(str(row.get(key) or "") for key in (
                "name", "breed", "notes", "customer_name", "customer_email", "customer_phone"
            )).casefold()
        ]
    st.caption(f"Kutyák száma: {len(rows)}")
    for dog in rows:
        owner_key = contact_key(dog)
        focus = st.session_state.get("focus_dog_id") == dog["id"]
        with st.expander(
            f"{'👉 ' if focus else ''}{dog.get('name') or ''} | {dog.get('breed') or 'ismeretlen fajta'} | "
            f"Gazdi: {dog.get('customer_name') or ''}",
            expanded=focus,
        ):
            with st.form(f"dog_edit_{dog['id']}"):
                name = st.text_input("Kutya neve", dog.get("name") or "")
                breed = st.text_input("Fajta", dog.get("breed") or "")
                notes = st.text_area("Megjegyzések", dog.get("notes") or "")
                save = st.form_submit_button("Kutya adatainak mentése")
            if save:
                DB.table("dogs").update({
                    "name": name.strip(), "breed": breed.strip() or None,
                    "notes": notes.strip() or None,
                }).eq("id", dog["id"]).execute()
                st.rerun()
            st.write(
                f"**Gazdi:** {dog.get('customer_name') or ''} | "
                f"{dog.get('customer_phone') or ''} | {dog.get('customer_email') or ''}"
            )
            if st.button(
                f"👤 {dog.get('customer_name') or 'Gazdi'} megnyitása",
                key=f"dog_to_owner_{dog['id']}",
            ):
                st.session_state.admin_section = "Gazdik"
                st.session_state.focus_owner_key = owner_key
                st.rerun()
            st.markdown("**Foglalási előzmények**")
            history = dog_booking_history(dog["id"])
            if history:
                st.dataframe(history, use_container_width=True, hide_index=True)
            else:
                st.info("Nincs foglalási előzmény.")


def newsletter_admin_section():
    st.subheader("Hírlevél")
    subscribers = {}
    for row in load_contacts():
        email = normalize_email(row.get("customer_email"))
        if row.get("newsletter_consent") and email:
            subscribers[email] = row.get("customer_name") or "Gazdi"
    st.info(f"Kifejezetten hozzájárult, egyedi címzettek száma: {len(subscribers)}")
    newsletter_subject = st.text_input("Hírlevél tárgya", key="newsletter_subject")
    newsletter_body = st.text_area("Hírlevél szövege", height=220, key="newsletter_body")
    confirm_bulk = st.checkbox(
        f"Megerősítem, hogy a hírlevelet {len(subscribers)} hozzájárult címzettnek elküldöm.",
        key="newsletter_confirm",
    )
    ready = bool(subscribers and newsletter_subject.strip() and newsletter_body.strip() and confirm_bulk)
    if st.button("Hírlevél kiküldése mindenkinek", type="primary", disabled=not ready):
        successes, failures = 0, []
        progress = st.progress(0, text="Hírlevél küldése...")
        for index, (recipient, owner_name) in enumerate(subscribers.items(), start=1):
            personalized = newsletter_body.replace("{{nev}}", owner_name)
            try:
                personalized = append_unsubscribe_footer(personalized, recipient)
                ok, error = send_custom_email(recipient, newsletter_subject, personalized, "newsletter")
                successes += int(ok)
                if not ok:
                    failures.append(f"{recipient}: {error}")
            except Exception as exc:
                failures.append(f"{recipient}: {exc}")
            progress.progress(index / len(subscribers), text=f"Küldés: {index}/{len(subscribers)}")
        st.success(f"Hírlevélküldés befejezve. Sikeres: {successes}; hibás: {len(failures)}")
        if failures:
            st.error("\n".join(failures[:20]))

def admin_page():
    st.title("🔒 Adminnaptár")
    if not admin_authenticated():
        return
    if st.session_state.pop("admin_flash", None):
        st.success("A módosítások elmentve, a naptár frissítve.")
    if "admin_section" not in st.session_state:
        st.session_state.admin_section = "Heti naptár"
    nav_columns = st.columns(4)
    for column, label, icon in zip(
        nav_columns,
        ["Heti naptár", "Gazdik", "Kutyák", "Hírlevél"],
        ["📅", "👤", "🐕", "✉️"],
    ):
        if column.button(
            f"{icon}  {label}",
            key=f"admin_nav_{label}",
            use_container_width=True,
            type="primary" if st.session_state.admin_section == label else "secondary",
        ):
            st.session_state.admin_section = label
            st.rerun()
    logout_col, refresh_col = st.columns(2)
    if logout_col.button("Kijelentkezés", use_container_width=True):
        st.session_state.admin_authenticated = False
        st.rerun()
    if refresh_col.button("Adatok frissítése", use_container_width=True):
        clear_public_cache()
        st.rerun()
    st.divider()
    if st.session_state.admin_section == "Heti naptár":
        admin_calendar_fragment()
    elif st.session_state.admin_section == "Gazdik":
        owners_admin_section()
    elif st.session_state.admin_section == "Kutyák":
        dogs_admin_section()
    else:
        newsletter_admin_section()


if st.query_params.get("cancel_booking"):
    process_booking_cancellation_page()
elif st.query_params.get("unsubscribe"):
    process_unsubscribe_page()
elif st.query_params.get("admin", "0") == "1":
    admin_page()
else:
    public_page()
