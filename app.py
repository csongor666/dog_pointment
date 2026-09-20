import hmac
import re
import smtplib
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from postgrest.exceptions import APIError
from supabase import Client, create_client

st.set_page_config(page_title="Kutyakozmetika Miskolc", page_icon="🐶", layout="wide")

TZ = ZoneInfo("Europe/Budapest")
SERVICES = {
    "Kistestű nyírás": 90,
    "Nagytestű nyírás": 120,
    "Fürdetés": 60,
    "Karomvágás": 30,
}
WEEKDAYS = {
    0: "Hétfő", 1: "Kedd", 2: "Szerda", 3: "Csütörtök",
    4: "Péntek", 5: "Szombat", 6: "Vasárnap",
}
PHONE_RE = re.compile(r"^[+0-9][0-9 ()/-]{6,24}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def secret(name: str, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


@st.cache_resource
def db() -> Client:
    url = secret("SUPABASE_URL")
    key = secret("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise RuntimeError("Hiányzik a SUPABASE_URL vagy SUPABASE_SECRET_KEY.")
    return create_client(url, key)


def parse_time(value) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    return time.fromisoformat(str(value)[:5])


def minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def as_hhmm(value) -> str:
    return parse_time(value).strftime("%H:%M")


def send_email(recipient: str, subject: str, body: str) -> None:
    address = secret("GMAIL_ADDRESS")
    password = secret("GMAIL_APP_PASSWORD")
    if not address or not password:
        raise RuntimeError("A Gmail küldési adatok nincsenek beállítva.")
    message = EmailMessage()
    message["From"] = address
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(address, password.replace(" ", ""))
        smtp.send_message(message)


def get_day_schedule(selected_date: date) -> dict:
    exception_rows = (
        db().table("opening_exceptions").select("*")
        .eq("exception_date", selected_date.isoformat()).limit(1).execute().data or []
    )
    if exception_rows:
        row = exception_rows[0]
        return {
            "source": "exception",
            "is_open": not row["is_closed"],
            "open_time": row.get("open_time"),
            "close_time": row.get("close_time"),
            "slot_interval_min": row.get("slot_interval_min") or 30,
            "note": row.get("note") or "",
        }
    weekly = (
        db().table("business_hours").select("*")
        .eq("weekday", selected_date.weekday()).limit(1).execute().data or []
    )
    if not weekly:
        return {"source": "missing", "is_open": False, "note": "Nincs beállított nyitvatartás."}
    row = weekly[0]
    return {
        "source": "weekly",
        "is_open": bool(row["is_open"]),
        "open_time": row.get("open_time"),
        "close_time": row.get("close_time"),
        "slot_interval_min": row.get("slot_interval_min") or 30,
        "note": "",
    }


def active_bookings(selected_date: date) -> list[dict]:
    return (
        db().table("bookings")
        .select("id,booking_date,booking_time,duration_min,service")
        .eq("booking_date", selected_date.isoformat())
        .eq("status", "active")
        .execute().data or []
    )


def available_slots(selected_date: date, duration_min: int) -> tuple[list[str], dict]:
    schedule = get_day_schedule(selected_date)
    if not schedule.get("is_open") or not schedule.get("open_time") or not schedule.get("close_time"):
        return [], schedule
    day_open = minutes(parse_time(schedule["open_time"]))
    day_close = minutes(parse_time(schedule["close_time"]))
    interval = int(schedule["slot_interval_min"])
    buffer_min = int(secret("BOOKING_BUFFER_MIN", 0))
    occupied = []
    for booking in active_bookings(selected_date):
        start = minutes(parse_time(booking["booking_time"]))
        occupied.append((start, start + int(booking.get("duration_min") or 30) + buffer_min))
    slots = []
    cursor = day_open
    now = datetime.now(TZ)
    min_notice = int(secret("MIN_BOOKING_NOTICE_HOURS", 12))
    while cursor + duration_min <= day_close:
        candidate_start = datetime.combine(selected_date, time(cursor // 60, cursor % 60), TZ)
        candidate_end = cursor + duration_min + buffer_min
        overlaps = any(cursor < booked_end and candidate_end > booked_start for booked_start, booked_end in occupied)
        if not overlaps and candidate_start >= now + timedelta(hours=min_notice):
            slots.append(f"{cursor // 60:02d}:{cursor % 60:02d}")
        cursor += interval
    return slots, schedule


def get_or_create_dog(owner_name: str, phone: str, email: str, dog_name: str, breed: str, notes: str) -> str:
    existing = (
        db().table("dogs").select("id")
        .eq("customer_email", email).ilike("name", dog_name).limit(1).execute().data or []
    )
    payload = {
        "customer_name": owner_name,
        "customer_phone": phone,
        "customer_email": email,
        "breed": breed or None,
        "notes": notes or None,
    }
    if existing:
        dog_id = existing[0]["id"]
        db().table("dogs").update(payload).eq("id", dog_id).execute()
        return dog_id
    payload["name"] = dog_name
    return db().table("dogs").insert(payload).execute().data[0]["id"]


def public_page():
    st.title("🐶 Kutyakozmetika Miskolc")
    st.write("Válassz szolgáltatást és a nyitvatartás alapján felajánlott szabad időpontot.")
    service = st.selectbox("Szolgáltatás", list(SERVICES), index=None, placeholder="Válassz szolgáltatást")
    today = datetime.now(TZ).date()
    selected_date = st.date_input("Nap", value=today, min_value=today, max_value=today + timedelta(days=int(secret("BOOKING_DAYS_AHEAD", 90))))
    slots, schedule = (available_slots(selected_date, SERVICES[service]) if service else ([], get_day_schedule(selected_date)))
    if not schedule.get("is_open"):
        st.warning(schedule.get("note") or "Ezen a napon zárva tartunk.")
    elif service:
        st.caption(f"Nyitvatartás: {as_hhmm(schedule['open_time'])}–{as_hhmm(schedule['close_time'])}")
        if schedule.get("note"):
            st.info(schedule["note"])
    slot = st.radio("Szabad időpont", slots, horizontal=True, index=None) if slots else None
    if service and schedule.get("is_open") and not slots:
        st.info("Erre a napra nincs a kiválasztott szolgáltatáshoz megfelelő szabad időpont.")
    with st.form("booking"):
        col1, col2 = st.columns(2)
        with col1:
            owner = st.text_input("Név *", max_chars=80)
            phone = st.text_input("Telefonszám *", max_chars=25)
            email = st.text_input("E-mail *", max_chars=150)
        with col2:
            dog_name = st.text_input("Kutya neve *", max_chars=60)
            breed = st.text_input("Fajta", max_chars=80)
            notes = st.text_area("Tartós megjegyzés a kutyáról", max_chars=500)
        privacy = st.checkbox("Elfogadom az adatkezelést. *")
        submit = st.form_submit_button("Időpont foglalása", type="primary", use_container_width=True, disabled=not(service and slot))
    if not submit:
        return
    owner, phone, email, dog_name = (" ".join(x.split()) for x in (owner, phone, email.lower(), dog_name))
    if len(owner) < 3 or not PHONE_RE.fullmatch(phone) or not EMAIL_RE.fullmatch(email) or not dog_name or not privacy:
        st.error("Ellenőrizd a kötelező mezőket, az e-mail-címet, a telefonszámot és az adatkezelési hozzájárulást.")
        return
    try:
        fresh_slots, _ = available_slots(selected_date, SERVICES[service])
        if slot not in fresh_slots:
            st.error("Az időpont időközben foglalttá vált. Válassz másikat.")
            return
        dog_id = get_or_create_dog(owner, phone, email, dog_name, breed.strip(), notes.strip())
        record = {
            "booking_date": selected_date.isoformat(), "booking_time": slot,
            "service": service, "duration_min": SERVICES[service],
            "customer_name": owner, "phone": phone, "email": email,
            "dog_id": dog_id, "status": "active",
        }
        inserted = db().table("bookings").insert(record).execute().data[0]
        mail_error = None
        try:
            send_email(email, "Foglalás visszaigazolása", f"Kedves {owner}!\n\nFoglalásod rögzítettük:\n{selected_date} {slot}\n{service}\n\nKutyakozmetika Miskolc")
            db().table("bookings").update({"confirmation_sent_at": datetime.now(TZ).isoformat()}).eq("id", inserted["id"]).execute()
        except Exception as exc:
            mail_error = str(exc)
        st.success(f"Köszönjük! Időpontja rögzítve: {selected_date} {slot}")
        if mail_error:
            st.warning("A foglalás sikerült, de a visszaigazoló e-mailt nem sikerült elküldeni.")
    except APIError as exc:
        if "23505" in str(exc):
            st.error("Az időpontot időközben lefoglalták. Válassz másikat.")
        else:
            st.error(f"Adatbázishiba: {exc}")
    except Exception as exc:
        st.error(f"A foglalás nem sikerült: {exc}")


def admin_login() -> bool:
    if st.session_state.get("admin"):
        return True
    with st.form("admin_login"):
        password = st.text_input("Admin jelszó", type="password")
        submitted = st.form_submit_button("Belépés")
    if submitted and hmac.compare_digest(password, str(secret("ADMIN_PASSWORD", ""))):
        st.session_state.admin = True
        st.rerun()
    if submitted:
        st.error("Hibás jelszó.")
    return False


def weekly_hours_editor():
    st.subheader("Heti nyitvatartás")
    rows = db().table("business_hours").select("*").order("weekday").execute().data or []
    by_day = {row["weekday"]: row for row in rows}
    with st.form("weekly_hours"):
        edited = []
        for weekday in range(7):
            current = by_day.get(weekday, {})
            cols = st.columns([1.4, 1, 1, 1, 1])
            cols[0].markdown(f"**{WEEKDAYS[weekday]}**")
            is_open = cols[1].checkbox("Nyitva", value=current.get("is_open", weekday < 5), key=f"open_{weekday}")
            open_time = cols[2].time_input("Nyitás", value=parse_time(current.get("open_time") or "09:00"), key=f"from_{weekday}")
            close_time = cols[3].time_input("Zárás", value=parse_time(current.get("close_time") or "17:00"), key=f"to_{weekday}")
            interval = cols[4].selectbox("Időköz", [15, 30, 45, 60], index=[15,30,45,60].index(int(current.get("slot_interval_min") or 30)), key=f"int_{weekday}")
            edited.append({"weekday": weekday, "is_open": is_open, "open_time": open_time.strftime("%H:%M"), "close_time": close_time.strftime("%H:%M"), "slot_interval_min": interval})
        save = st.form_submit_button("Heti nyitvatartás mentése", type="primary", use_container_width=True)
    if save:
        invalid = [WEEKDAYS[x["weekday"]] for x in edited if x["is_open"] and x["open_time"] >= x["close_time"]]
        if invalid:
            st.error("A nyitásnak korábbinak kell lennie a zárásnál: " + ", ".join(invalid))
        else:
            db().table("business_hours").upsert(edited, on_conflict="weekday").execute()
            st.success("A heti nyitvatartás elmentve.")


def exceptions_editor():
    st.subheader("Egyedi napok, szabadság és eltérő nyitvatartás")
    with st.form("new_exception"):
        d = st.date_input("Dátum", min_value=datetime.now(TZ).date())
        closed = st.checkbox("Egész nap zárva", value=True)
        c1, c2, c3 = st.columns(3)
        opening = c1.time_input("Nyitás", value=time(9, 0), disabled=closed)
        closing = c2.time_input("Zárás", value=time(17, 0), disabled=closed)
        interval = c3.selectbox("Időköz", [15, 30, 45, 60], index=1, disabled=closed)
        note = st.text_input("Megjegyzés", placeholder="Például szabadság vagy rendkívüli nyitvatartás")
        save = st.form_submit_button("Egyedi nap mentése", type="primary")
    if save:
        if not closed and opening >= closing:
            st.error("A nyitásnak korábbinak kell lennie a zárásnál.")
        else:
            payload = {"exception_date": d.isoformat(), "is_closed": closed, "open_time": None if closed else opening.strftime("%H:%M"), "close_time": None if closed else closing.strftime("%H:%M"), "slot_interval_min": interval, "note": note.strip() or None}
            db().table("opening_exceptions").upsert(payload, on_conflict="exception_date").execute()
            st.success("Az egyedi nap elmentve.")
    exceptions = db().table("opening_exceptions").select("*").gte("exception_date", datetime.now(TZ).date().isoformat()).order("exception_date").execute().data or []
    for item in exceptions:
        label = "Zárva" if item["is_closed"] else f"{as_hhmm(item['open_time'])}–{as_hhmm(item['close_time'])}"
        c1, c2 = st.columns([5, 1])
        c1.write(f"**{item['exception_date']}** | {label} | {item.get('note') or ''}")
        if c2.button("Törlés", key=f"exception_{item['id']}"):
            db().table("opening_exceptions").delete().eq("id", item["id"]).execute()
            st.rerun()


def bookings_admin():
    data = db().table("bookings").select("*,dog:dogs!bookings_dog_id_fkey(name,breed,notes)").eq("status", "active").order("booking_date").order("booking_time").execute().data or []
    query = st.text_input("Keresés a foglalásokban")
    if query:
        data = [x for x in data if query.casefold() in str(x).casefold()]
    for item in data:
        with st.container(border=True):
            dog = item.get("dog") or {}
            st.write(f"**{item['booking_date']} {item['booking_time']}** | {item['customer_name']} | {item['service']} | {item['phone']} | {item.get('email','')}")
            st.caption(f"Kutya: {dog.get('name','')} | Fajta: {dog.get('breed','')}")
    if data:
        st.download_button("CSV letöltése", pd.DataFrame(data).to_csv(index=False).encode("utf-8-sig"), "foglalasok.csv")


def admin_page():
    st.title("🔒 Adminisztráció")
    if not admin_login():
        return
    if st.button("Kijelentkezés"):
        st.session_state.admin = False
        st.rerun()
    tab1, tab2, tab3 = st.tabs(["Nyitvatartás", "Egyedi napok", "Foglalások"])
    with tab1:
        weekly_hours_editor()
    with tab2:
        exceptions_editor()
    with tab3:
        bookings_admin()


if st.query_params.get("admin", "0") == "1":
    admin_page()
else:
    public_page()
