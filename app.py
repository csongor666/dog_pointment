import hashlib
import hmac
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from github_storage import GitHubJSONStorage, StorageError

st.set_page_config(page_title="Kutyakozmetika Miskolc", page_icon="🐶", layout="centered")

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
.block-container {max-width: 920px; padding-top: 2rem;}
.hero {padding: 1.5rem; border-radius: 22px; background: linear-gradient(135deg,#ecfdf5,#fffbeb); margin-bottom: 1rem;}
.hero h1 {margin: 0; color:#14532d;}
.success-box {padding:1.4rem; border:1px solid #86efac; background:#f0fdf4; border-radius:18px; text-align:center;}
.small-note {color:#64748b; font-size:.86rem;}
div[data-testid="stButton"] button {border-radius:12px;}
</style>
""", unsafe_allow_html=True)


def secret(name: str, default=None):
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return default


def storage() -> GitHubJSONStorage:
    required = ["GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_REPO"]
    missing = [name for name in required if not secret(name)]
    if missing:
        raise StorageError("Hiányzó Streamlit secret: " + ", ".join(missing))
    return GitHubJSONStorage(
        token=secret("GITHUB_TOKEN"),
        owner=secret("GITHUB_OWNER"),
        repo=secret("GITHUB_REPO"),
        branch=secret("GITHUB_BRANCH", "main"),
        path=secret("BOOKINGS_PATH", "data/bookings.json"),
    )


def load_bookings(show_error=True):
    try:
        records, _ = storage().read()
        return records
    except StorageError as exc:
        if show_error:
            st.error(str(exc))
        return []


def hash_phone(value: str) -> str:
    pepper = str(secret("PHONE_HASH_PEPPER", "change-me"))
    return hashlib.sha256((pepper + value).encode("utf-8")).hexdigest()


def is_active(item):
    return item.get("status", "active") == "active"


def admin_login():
    expected = str(secret("ADMIN_PASSWORD", ""))
    if not expected:
        st.error("Az ADMIN_PASSWORD nincs beállítva a Secrets között.")
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
    if not admin_login():
        return
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Foglalások frissítése", use_container_width=True):
            st.rerun()
    with col2:
        if st.button("Kijelentkezés", use_container_width=True):
            st.session_state.admin_authenticated = False
            st.rerun()

    records = load_bookings()
    active = [x for x in records if is_active(x)]
    today = date.today().isoformat()
    m1, m2 = st.columns(2)
    m1.metric("Aktív foglalások", len(active))
    m2.metric("Mai foglalások", sum(x.get("date") == today for x in active))

    query = st.text_input("Keresés név, telefonszám vagy szolgáltatás alapján")
    filtered = active
    if query.strip():
        needle = query.casefold().strip()
        filtered = [x for x in active if needle in " ".join(str(x.get(k, "")) for k in ("name", "phone", "service")).casefold()]
    filtered.sort(key=lambda x: (x.get("date", ""), x.get("time", "")))

    if not filtered:
        st.info("Nincs megjeleníthető foglalás.")
        return
    for item in filtered:
        with st.container(border=True):
            cols = st.columns([1.1, 1.4, 1.4, 1.5, .7])
            cols[0].markdown(f"**{item.get('date','')}**  \\n{item.get('time','')}")
            cols[1].write(item.get("service", ""))
            cols[2].write(item.get("name", ""))
            cols[3].write(item.get("phone", ""))
            if cols[4].button("Törlés", key=f"del_{item.get('id')}"):
                try:
                    storage().cancel_booking(item["id"])
                    st.success("A foglalás törölve.")
                    st.rerun()
                except StorageError as exc:
                    st.error(str(exc))

    export_rows = [{k: x.get(k, "") for k in ("date", "time", "service", "name", "phone", "created_at")} for x in filtered]
    csv_data = pd.DataFrame(export_rows).to_csv(index=False).encode("utf-8-sig")
    st.download_button("CSV letöltése", csv_data, "foglalasok.csv", "text/csv", use_container_width=True)


def booking_page():
    st.markdown('<div class="hero"><h1>🐶 Kutyakozmetika Miskolc</h1><p>Válassz szolgáltatást és szabad időpontot.</p></div>', unsafe_allow_html=True)

    if st.session_state.get("booking_success"):
        saved = st.session_state.booking_success
        st.markdown(f'<div class="success-box"><h2>Köszönjük!</h2><p>Időpontja rögzítve:</p><h3>{saved["date"]} {saved["time"]}</h3></div>', unsafe_allow_html=True)
        if st.button("Új foglalás", use_container_width=True):
            del st.session_state.booking_success
            st.rerun()
        return

    records = load_bookings()
    service = st.selectbox("Válassz szolgáltatást", list(SERVICES), index=None, placeholder="Szolgáltatás kiválasztása")
    min_day = datetime.now(BUDAPEST).date()
    max_day = min_day + timedelta(days=int(secret("BOOKING_DAYS_AHEAD", 90)))
    selected_day = st.date_input("Válassz napot", min_value=min_day, max_value=max_day)

    if selected_day.weekday() >= 5:
        st.warning("Hétvégére jelenleg nem fogadunk online foglalást.")
        available = []
    else:
        occupied = {x.get("time") for x in records if is_active(x) and x.get("date") == selected_day.isoformat()}
        available = [t for t in TIMES if t not in occupied]

    chosen_time = st.radio("Kiválasztható időpontok", available, horizontal=True, index=None) if available else None
    if not available:
        st.info("Erre a napra nincs szabad időpont.")

    with st.form("booking_form"):
        name = st.text_input("Név", max_chars=80)
        phone = st.text_input("Telefonszám", placeholder="+36 30 123 4567", max_chars=25)
        privacy = st.checkbox("Elfogadom, hogy az adataimat kizárólag az időpont kezelése céljából tárolják.")
        submitted = st.form_submit_button("Időpont foglalása", use_container_width=True, disabled=not (service and chosen_time))

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
        booking = {
            "id": str(uuid.uuid4()),
            "date": selected_day.isoformat(),
            "time": chosen_time,
            "service": service,
            "duration_min": SERVICES[service],
            "name": clean_name,
            "phone": clean_phone,
            "phone_hash": hash_phone(clean_phone),
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            storage().add_booking(booking)
            st.session_state.booking_success = {"date": booking["date"], "time": booking["time"]}
            st.rerun()
        except StorageError as exc:
            st.error(str(exc))

    st.markdown('<p class="small-note">Lemondáshoz kérjük, telefonon jelezd. Az adminfelület külön linken és jelszóval érhető el.</p>', unsafe_allow_html=True)


admin_requested = st.query_params.get("admin", "0") == "1"
if admin_requested:
    admin_page()
else:
    booking_page()
