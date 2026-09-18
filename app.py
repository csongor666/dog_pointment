import hashlib
import hmac
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from postgrest.exceptions import APIError
from supabase import Client, create_client

st.set_page_config(
    page_title="Kutyakozmetika Miskolc",
    page_icon="🐶",
    layout="centered",
)

SERVICES = {
    "Kistestű nyírás": 90,
    "Nagytestű nyírás": 120,
    "Fürdetés": 60,
    "Karomvágás": 30,
}
TIMES = ["09:00", "10:30", "13:00", "15:00"]
BUDAPEST = ZoneInfo("Europe/Budapest")
PHONE_RE = re.compile(r"^[+0-9][0-9 ()/-]{6,24}$")

st.markdown("""
<style>
.block-container {max-width: 920px; padding-top: 2rem; padding-bottom: 3rem;}
.hero {padding: 1.6rem; border-radius: 22px; background: linear-gradient(135deg,#ecfdf5,#fffbeb); margin-bottom: 1.2rem;}
.hero h1 {margin: 0; color:#14532d;}
.success-box {padding:1.5rem; border:1px solid #86efac; background:#f0fdf4; border-radius:18px; text-align:center;}
.small-note {color:#64748b; font-size:.86rem;}
div[data-testid="stButton"] button {border-radius:12px;}
</style>
""", unsafe_allow_html=True)


def get_secret(name: str, default=None):
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return default


@st.cache_resource
def get_supabase() -> Client:
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise RuntimeError("Hiányzik a SUPABASE_URL vagy SUPABASE_SECRET_KEY a Streamlit Secrets beállításból.")
    return create_client(url, key)


def active_bookings_for_day(day_iso: str) -> list[dict]:
    response = (
        get_supabase()
        .table("bookings")
        .select("id,booking_date,booking_time")
        .eq("booking_date", day_iso)
        .eq("status", "active")
        .execute()
    )
    return response.data or []


def load_admin_bookings() -> list[dict]:
    response = (
        get_supabase()
        .table("bookings")
        .select("id,created_at,booking_date,booking_time,service,duration_min,customer_name,phone,dog_name,dog_breed,notes,status")
        .eq("status", "active")
        .order("booking_date")
        .order("booking_time")
        .execute()
    )
    return response.data or []


def hash_phone(value: str) -> str:
    pepper = str(get_secret("PHONE_HASH_PEPPER", "change-this-now"))
    return hashlib.sha256((pepper + value).encode("utf-8")).hexdigest()


def friendly_database_error(exc: Exception) -> str:
    text = str(exc)
    if "23505" in text or "duplicate key" in text.lower():
        return "Ezt az időpontot időközben lefoglalták. Válassz másikat."
    return "Az adatbázis jelenleg nem érhető el. Kérjük, próbáld újra később."


def authenticate_admin() -> bool:
    expected = str(get_secret("ADMIN_PASSWORD", ""))
    if not expected:
        st.error("Az ADMIN_PASSWORD nincs beállítva a Streamlit Secrets között.")
        return False
    if st.session_state.get("admin_authenticated"):
        return True
    with st.form("admin_login"):
        password = st.text_input("Admin jelszó", type="password")
        submitted = st.form_submit_button("Belépés", use_container_width=True)
    if submitted:
        if hmac.compare_digest(password, expected):
            st.session_state.admin_authenticated = True
            st.rerun()
        st.error("Hibás jelszó.")
    return False


def admin_page():
    st.title("🔒 Adminisztráció")
    st.caption("Ez az oldal csak a külön adminlinkkel és jelszóval használható.")
    if not authenticate_admin():
        return

    c1, c2 = st.columns(2)
    if c1.button("Frissítés", use_container_width=True):
        st.rerun()
    if c2.button("Kijelentkezés", use_container_width=True):
        st.session_state.admin_authenticated = False
        st.rerun()

    try:
        bookings = load_admin_bookings()
    except Exception as exc:
        st.error(friendly_database_error(exc))
        return

    today_iso = datetime.now(BUDAPEST).date().isoformat()
    m1, m2, m3 = st.columns(3)
    m1.metric("Aktív foglalások", len(bookings))
    m2.metric("Mai foglalások", sum(x["booking_date"] == today_iso for x in bookings))
    m3.metric("Jövőbeli foglalások", sum(x["booking_date"] >= today_iso for x in bookings))

    query = st.text_input("Keresés név, telefon, kutya, fajta vagy szolgáltatás alapján")
    if query.strip():
        needle = query.strip().casefold()
        fields = ("customer_name", "phone", "dog_name", "dog_breed", "service")
        bookings = [b for b in bookings if needle in " ".join(str(b.get(k) or "") for k in fields).casefold()]

    if not bookings:
        st.info("Nincs megjeleníthető foglalás.")
        return

    for item in bookings:
        with st.container(border=True):
            top = st.columns([1.2, 1.4, 1.3, 1.5, .7])
            top[0].markdown(f"**{item['booking_date']}**  \\n{item['booking_time']}")
            top[1].write(item.get("service", ""))
            top[2].write(item.get("customer_name", ""))
            top[3].write(item.get("phone", ""))
            if top[4].button("Törlés", key=f"delete_{item['id']}"):
                try:
                    (
                        get_supabase()
                        .table("bookings")
                        .update({"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat()})
                        .eq("id", item["id"])
                        .execute()
                    )
                    st.success("A foglalás törölve.")
                    st.rerun()
                except Exception as exc:
                    st.error(friendly_database_error(exc))
            dog = item.get("dog_name") or "Nincs megadva"
            breed = item.get("dog_breed") or "Nincs megadva"
            st.caption(f"Kutya: {dog} | Fajta: {breed} | Időtartam: {item.get('duration_min', '')} perc")
            if item.get("notes"):
                st.write("Megjegyzés:", item["notes"])

    export_fields = ["booking_date", "booking_time", "service", "duration_min", "customer_name", "phone", "dog_name", "dog_breed", "notes", "created_at"]
    export = [{key: row.get(key, "") for key in export_fields} for row in bookings]
    csv = pd.DataFrame(export).to_csv(index=False).encode("utf-8-sig")
    st.download_button("CSV letöltése", csv, "foglalasok.csv", "text/csv", use_container_width=True)


def booking_page():
    st.markdown('<div class="hero"><h1>🐶 Kutyakozmetika Miskolc</h1><p>Válassz szolgáltatást és szabad időpontot.</p></div>', unsafe_allow_html=True)

    if st.session_state.get("booking_success"):
        result = st.session_state.booking_success
        st.markdown(
            f'<div class="success-box"><h2>Köszönjük!</h2><p>Időpontja rögzítve:</p><h3>{result["date"]} {result["time"]}</h3></div>',
            unsafe_allow_html=True,
        )
        if st.button("Új foglalás", use_container_width=True):
            del st.session_state.booking_success
            st.rerun()
        return

    service = st.selectbox(
        "Válassz szolgáltatást",
        list(SERVICES),
        index=None,
        placeholder="Szolgáltatás kiválasztása",
    )
    min_day = datetime.now(BUDAPEST).date()
    max_day = min_day + timedelta(days=int(get_secret("BOOKING_DAYS_AHEAD", 90)))
    selected_day = st.date_input("Válassz napot", min_value=min_day, max_value=max_day)

    available = []
    if selected_day.weekday() >= 5:
        st.warning("Hétvégére jelenleg nem fogadunk online foglalást.")
    else:
        try:
            occupied = {x["booking_time"] for x in active_bookings_for_day(selected_day.isoformat())}
            available = [slot for slot in TIMES if slot not in occupied]
        except Exception as exc:
            st.error(friendly_database_error(exc))

    chosen_time = None
    if available:
        chosen_time = st.radio("Kiválasztható időpontok", available, horizontal=True, index=None)
    else:
        st.info("Erre a napra nincs szabad időpont.")

    with st.form("booking_form"):
        name = st.text_input("Név", max_chars=80)
        phone = st.text_input("Telefonszám", placeholder="+36 30 123 4567", max_chars=25)
        dog_name = st.text_input("Kutya neve", max_chars=60)
        dog_breed = st.text_input("Kutya fajtája", max_chars=80)
        notes = st.text_area("Megjegyzés, például érzékenység vagy viselkedés", max_chars=500)
        privacy = st.checkbox("Elfogadom, hogy az adataimat kizárólag az időpont kezelése céljából tárolják.")
        submitted = st.form_submit_button(
            "Időpont foglalása",
            use_container_width=True,
            disabled=not (service and chosen_time),
        )

    if submitted:
        clean_name = " ".join(name.split())
        clean_phone = " ".join(phone.split())
        if len(clean_name) < 3:
            st.error("Kérjük, adj meg érvényes nevet.")
            return
        if not PHONE_RE.fullmatch(clean_phone):
            st.error("Kérjük, adj meg érvényes telefonszámot.")
            return
        if not privacy:
            st.error("A foglaláshoz szükséges az adatkezelési hozzájárulás.")
            return

        record = {
            "id": str(uuid.uuid4()),
            "booking_date": selected_day.isoformat(),
            "booking_time": chosen_time,
            "service": service,
            "duration_min": SERVICES[service],
            "customer_name": clean_name,
            "phone": clean_phone,
            "phone_hash": hash_phone(clean_phone),
            "dog_name": " ".join(dog_name.split()) or None,
            "dog_breed": " ".join(dog_breed.split()) or None,
            "notes": notes.strip() or None,
            "status": "active",
        }
        try:
            # Az egyedi részindex az adatbázisban is megakadályozza a dupla foglalást.
            get_supabase().table("bookings").insert(record).execute()
            st.session_state.booking_success = {"date": record["booking_date"], "time": record["booking_time"]}
            st.rerun()
        except (APIError, Exception) as exc:
            st.error(friendly_database_error(exc))

    st.markdown('<p class="small-note">Lemondáshoz kérjük, telefonon jelezd. A személyes adatok nem kerülnek a nyilvános GitHub repositoryba.</p>', unsafe_allow_html=True)


if st.query_params.get("admin", "0") == "1":
    admin_page()
else:
    booking_page()
