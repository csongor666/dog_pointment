import hmac
import re
import smtplib
import hashlib
import urllib.parse
from email.message import EmailMessage
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
from db import get_db
from email_service import send_confirmation

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
    "completed": "#16a34a",
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
    .day-head { text-align:center; font-weight:700; padding:8px 3px; background:#f1f5f9; border-radius:8px; margin-bottom:4px; }
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
        .select("id,booking_date,booking_time,duration_min,service,status,customer_name,phone,email,dog_id,confirmation_sent_at,last_email_error")
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
    items.sort(key=lambda item: item["time"])
    return items, day_schedule

def public_week_calendar(service):
    week_start = week_navigation("public_week")
    bundle = load_public_week(week_start.isoformat())
    columns = st.columns(7)
    selected = None
    for day_index, day_column in enumerate(columns):
        day = week_start + timedelta(days=day_index)
        with day_column:
            st.markdown(f'<div class="day-head">{DAY_NAMES[day.weekday()]}<br>{day:%m.%d}</div>', unsafe_allow_html=True)
            items, day_schedule = chronological_day_items(day, service, bundle)
            if not day_schedule.get("open"):
                st.markdown('<div class="slot-card slot-closed">Nem foglalható</div>', unsafe_allow_html=True)
                continue
            for item in items:
                if item["kind"] == "busy":
                    st.markdown(
                        f'<div class="slot-card slot-busy">{item["time"]}<br>Foglalt</div>',
                        unsafe_allow_html=True,
                    )
                elif st.button(item["time"], key=f"free_{day}_{item['time']}", type="primary", use_container_width=True):
                    selected = (day, item["time"])
            if not items:
                st.markdown('<div class="slot-card slot-closed">Nincs megfelelő sáv</div>', unsafe_allow_html=True)
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
        st.warning("A foglalás sikerült, de a visszaigazoló e-mail nem ment el.")
    st.session_state["flash_message"] = f"Foglalás rögzítve: {selected_date} {selected_time}"
    st.rerun()


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


def public_page():
    st.title("🐶 Kutyakozmetika Miskolc")
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
    save_col, mail_col = st.columns(2)
    if save_col.button("Módosítások mentése", type="primary", use_container_width=True):
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
    if mail_col.button("Visszaigazolás újraküldése", use_container_width=True):
        current = load_booking(booking_id)
        with st.spinner("E-mail küldése...", show_time=True):
            ok, error = send_confirmation(current, "manual")
        if ok:
            st.success("A visszaigazolás elküldve.")
        else:
            st.error(f"E-mail-hiba: {error}")


@st.fragment
def admin_calendar_fragment():
    week_start = week_navigation("admin_week")
    color_mode = st.radio(
        "Színezés", ["Státusz szerint", "Szolgáltatás szerint"], horizontal=True
    )
    with st.spinner("Heti naptár frissítése...", show_time=True):
        bundle = load_admin_week(week_start)
    columns = st.columns(7)
    for day_index, day_column in enumerate(columns):
        day = week_start + timedelta(days=day_index)
        with day_column:
            day_schedule = schedule_from_bundle(day, bundle)
            bookings = bookings_from_bundle(day, bundle)
            capacity = (
                minute_of_day(day_schedule["to"]) - minute_of_day(day_schedule["from"])
                if day_schedule.get("open") and day_schedule.get("from") and day_schedule.get("to") else 0
            )
            used = sum(int(item.get("duration_min") or 0) for item in bookings if item.get("status") == "active")
            percentage = round(100 * used / capacity) if capacity else 0
            st.markdown(
                f'<div class="day-head">{DAY_NAMES[day.weekday()]} {day:%m.%d}<br>'
                f'{used}/{capacity} perc ({percentage}%)</div>', unsafe_allow_html=True,
            )
            if not day_schedule.get("open"):
                st.markdown('<div class="slot-card slot-closed">Zárva</div>', unsafe_allow_html=True)
                continue
            free, _ = available_slots_from_bundle(day, 30, bundle, admin=True)
            calendar_items = ([{"time": slot, "kind": "free"} for slot in free] +
                              [{"time": str(item["booking_time"])[:5], "kind": "booking", "booking": item} for item in bookings])
            calendar_items.sort(key=lambda item: item["time"])
            for item in calendar_items:
                if item["kind"] == "free":
                    st.markdown(f'<div class="slot-card slot-free">{item["time"]} Szabad</div>', unsafe_allow_html=True)
                    continue
                booking = item["booking"]
                color = (STATUS_COLORS.get(booking["status"], "#64748b")
                         if color_mode == "Státusz szerint"
                         else SERVICE_COLORS.get(booking["service"], "#64748b"))
                st.markdown(
                    f'<div class="slot-card" style="background:{color};color:white">'
                    f'{item["time"]} {booking["customer_name"]}<br>{booking["service"]}</div>',
                    unsafe_allow_html=True,
                )
                if st.button("Szerkesztés", key=f"edit_{booking['id']}", use_container_width=True):
                    edit_booking_dialog(booking["id"])


def load_contacts():
    return DB.table("dogs").select("id,name,breed,customer_name,customer_phone,customer_email,notes,newsletter_consent,newsletter_consent_at").order("customer_name").execute().data or []


def contact_database_admin():
    st.subheader("Gazdi- és kutyaadatbázis")
    rows = load_contacts()
    search = st.text_input("Keresés gazdi, kutya, e-mail, telefon vagy fajta alapján")
    if search:
        needle = search.casefold()
        rows = [row for row in rows if needle in " ".join(str(row.get(key) or "") for key in ("customer_name","name","customer_email","customer_phone","breed")).casefold()]
    owners = {}
    for row in rows:
        key = (row.get("customer_email") or "", row.get("customer_name") or "")
        owners.setdefault(key, []).append(row)
    st.caption(f"Gazdik: {len(owners)} | Kutyák: {len(rows)}")
    for (email, owner_name), dogs in owners.items():
        consent = any(bool(dog.get("newsletter_consent")) for dog in dogs)
        with st.expander(f"{owner_name} | {email} | {len(dogs)} kutya | Hírlevél: {'igen' if consent else 'nem'}"):
            st.write("Telefon:", dogs[0].get("customer_phone") or "")
            for dog in dogs:
                st.markdown(f"**{dog.get('name','')}** | {dog.get('breed') or 'ismeretlen fajta'}")
                if dog.get("notes"):
                    st.caption(dog["notes"])
            st.session_state.setdefault("selected_contact_email", email)
            if st.button("Levél írása", key=f"mail_owner_{email}"):
                st.session_state.selected_contact_email = email
                st.session_state.selected_contact_name = owner_name

    st.divider()
    st.subheader("Egyedi levél")
    recipient = st.text_input("Címzett", value=st.session_state.get("selected_contact_email", ""))
    subject = st.text_input("Tárgy", key="single_subject")
    body = st.text_area("Üzenet", height=180, key="single_body")
    if st.button("Egyedi levél elküldése", type="primary", disabled=not(recipient and subject and body)):
        with st.spinner("Levél küldése...", show_time=True):
            ok, error = send_custom_email(recipient, subject, body, "manual")
        st.success("A levél elküldve.") if ok else st.error(f"Küldési hiba: {error}")

    st.divider()
    st.subheader("Hírlevél küldése")
    st.caption("Minden hírlevél végére automatikusan egyedi, egykattintásos leiratkozási link kerül.")
    subscribers = {}
    for row in load_contacts():
        if row.get("newsletter_consent") and row.get("customer_email"):
            subscribers[row["customer_email"].lower()] = row.get("customer_name") or "Gazdi"
    st.info(f"Kifejezetten hozzájárult, egyedi címzettek száma: {len(subscribers)}")
    newsletter_subject = st.text_input("Hírlevél tárgya")
    newsletter_body = st.text_area("Hírlevél szövege", height=220)
    confirm_bulk = st.checkbox(f"Megerősítem, hogy a hírlevelet {len(subscribers)} hozzájárult címzettnek elküldöm.")
    bulk_ready = bool(subscribers) and bool(newsletter_subject.strip()) and bool(newsletter_body.strip()) and confirm_bulk
    if st.button("Hírlevél kiküldése mindenkinek", type="primary", disabled=not bulk_ready):
        successes = 0
        failures = []
        progress = st.progress(0, text="Hírlevél küldése...")
        for index, (subscriber_email, subscriber_name) in enumerate(subscribers.items(), start=1):
            personalized = newsletter_body.replace("{{nev}}", subscriber_name)
            try:
                personalized = append_unsubscribe_footer(personalized, subscriber_email)
            except Exception as exc:
                failures.append(f"{subscriber_email}: leiratkozási link hiba: {exc}")
                progress.progress(index / len(subscribers), text=f"Küldés: {index}/{len(subscribers)}")
                continue
            ok, error = send_custom_email(subscriber_email, newsletter_subject, personalized, "newsletter")
            if ok:
                successes += 1
            else:
                failures.append(f"{subscriber_email}: {error}")
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
    logout_col, refresh_col = st.columns(2)
    if logout_col.button("Kijelentkezés", use_container_width=True):
        st.session_state.admin_authenticated = False
        st.rerun()
    if refresh_col.button("Naptár frissítése", use_container_width=True):
        clear_public_cache()
        st.rerun()
    calendar_tab, contacts_tab = st.tabs(["Heti naptár", "Gazdik és kutyák / levelezés"])
    with calendar_tab:
        admin_calendar_fragment()
    with contacts_tab:
        contact_database_admin()


if st.query_params.get("unsubscribe"):
    process_unsubscribe_page()
elif st.query_params.get("admin", "0") == "1":
    admin_page()
else:
    public_page()
