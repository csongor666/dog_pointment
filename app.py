import hashlib
import hmac
import html
import secrets
import smtplib
import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Kutyakozmetika Miskolc V6", page_icon="🐶", layout="wide")
TZ = ZoneInfo("Europe/Budapest")
SERVICES = {"Kistestű nyírás": 90, "Nagytestű nyírás": 120, "Fürdetés": 60, "Karomvágás": 30}
TIMES = ["09:00", "10:30", "13:00", "15:00"]
STATUS_MARKERS = {"active": "🟦", "completed": "🟩", "cancelled": "🟥", "blocked": "⬛"}
SERVICE_MARKERS = {"Kistestű nyírás": "🟪", "Nagytestű nyírás": "🟥", "Fürdetés": "🟦", "Karomvágás": "🟨"}


@st.cache_resource
def db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SECRET_KEY"])


def app_url():
    return str(st.secrets.get("APP_URL", "https://dog-pointment.streamlit.app")).rstrip("/")


def send_mail(to, subject, text_body, html_body=None):
    message = EmailMessage()
    message["From"] = st.secrets["GMAIL_ADDRESS"]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(st.secrets["GMAIL_ADDRESS"], st.secrets["GMAIL_APP_PASSWORD"])
        smtp.send_message(message)


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_action_url(action, owner_id=None, booking_id=None, expires_days=365):
    token = secrets.token_urlsafe(9)
    db().table("action_tokens").insert({
        "token_hash": token_hash(token),
        "action": action,
        "owner_id": owner_id,
        "booking_id": booking_id,
        "expires_at": (datetime.now(TZ) + timedelta(days=expires_days)).isoformat(),
    }).execute()
    return f"{app_url()}/?action={action}&t={token}"


def email_button(url, label, color="#166534"):
    return (
        f'<a href="{html.escape(url, quote=True)}" '
        f'style="display:inline-block;padding:12px 18px;background:{color};color:#fff;'
        f'text-decoration:none;border-radius:8px;font-weight:700">{html.escape(label)}</a>'
    )


def get_bookings(include_all=True):
    query = db().table("bookings").select(
        "*,owner:owners!bookings_owner_id_fkey(*),dog:dogs!bookings_dog_id_fkey(*)"
    )
    if not include_all:
        query = query.eq("status", "active")
    return query.order("booking_date").order("booking_time").execute().data or []


def get_owners():
    return db().table("owners").select(
        "*,dogs(*),bookings(id,booking_date,booking_time,service,status)"
    ).order("full_name").execute().data or []


def get_owner(owner_id):
    return db().table("owners").select("*").eq("id", owner_id).single().execute().data


def upsert_owner(name, phone, email, newsletter=False):
    normalized = email.strip().lower()
    found = db().table("owners").select("id").eq("email", normalized).execute().data or []
    payload = {
        "full_name": name.strip(), "phone": phone.strip(), "email": normalized,
        "newsletter_subscribed": newsletter, "updated_at": datetime.now(TZ).isoformat(),
    }
    if found:
        owner_id = found[0]["id"]
        db().table("owners").update(payload).eq("id", owner_id).execute()
        return owner_id
    payload["id"] = str(uuid.uuid4())
    return db().table("owners").insert(payload).execute().data[0]["id"]


def upsert_dog(owner_id, name, breed, notes):
    owner = get_owner(owner_id)
    found = db().table("dogs").select("id").eq("owner_id", owner_id).ilike("name", name.strip()).execute().data or []
    payload = {
        "owner_id": owner_id, "name": name.strip(), "breed": breed.strip() or None,
        "notes": notes.strip() or None,
        # Régi oszlopok kompatibilitási célból megmaradnak.
        "customer_name": owner["full_name"], "customer_phone": owner["phone"],
        "customer_email": owner["email"],
    }
    if found:
        dog_id = found[0]["id"]
        db().table("dogs").update(payload).eq("id", dog_id).execute()
        return dog_id
    payload["id"] = str(uuid.uuid4())
    return db().table("dogs").insert(payload).execute().data[0]["id"]


def save_booking(booking_id, day, slot, service, owner_id, dog_id, status="active"):
    owner = get_owner(owner_id)
    payload = {
        "booking_date": day.isoformat(), "booking_time": slot, "service": service,
        "duration_min": SERVICES[service], "owner_id": owner_id, "dog_id": dog_id,
        "status": status, "customer_name": owner["full_name"], "phone": owner["phone"],
        "email": owner["email"], "is_demo": False,
    }
    if booking_id:
        db().table("bookings").update(payload).eq("id", booking_id).execute()
        return booking_id
    payload["id"] = str(uuid.uuid4())
    db().table("bookings").insert(payload).execute()
    return payload["id"]


def send_confirmation(booking):
    owner = booking["owner"]
    dog = booking.get("dog") or {}
    cancel_url = create_action_url("cancel_booking", owner["id"], booking["id"])
    text = (
        f"Kedves {owner['full_name']}!\n\nFoglalásod rögzítettük: "
        f"{booking['booking_date']} {booking['booking_time']}, {booking['service']}.\n"
        f"Kutya: {dog.get('name', '')}\n\nFoglalás lemondása: {cancel_url}"
    )
    html_body = (
        f"<p>Kedves {html.escape(owner['full_name'])}!</p>"
        f"<p>Foglalásod rögzítettük: <strong>{booking['booking_date']} "
        f"{booking['booking_time']}</strong>, {html.escape(booking['service'])}.</p>"
        f"<p>{email_button(cancel_url, 'Foglalás lemondása', '#b91c1c')}</p>"
    )
    send_mail(owner["email"], "Kutyakozmetikai foglalás visszaigazolása", text, html_body)
    db().table("bookings").update({"confirmation_sent_at": datetime.now(TZ).isoformat()}).eq("id", booking["id"]).execute()


def admin_login():
    if st.session_state.get("admin"):
        return True
    with st.form("admin_login"):
        password = st.text_input("Admin jelszó", type="password")
        submitted = st.form_submit_button("Belépés")
    if submitted and hmac.compare_digest(password, str(st.secrets["ADMIN_PASSWORD"])):
        st.session_state.admin = True
        st.rerun()
    if submitted:
        st.error("Hibás jelszó")
    return False


@st.dialog("Időpont szerkesztése", width="large")
def booking_editor(day, slot, booking=None):
    owners = get_owners()
    labels = {f"{o['full_name']} | {o['email']}": o for o in owners}
    current_owner = (booking or {}).get("owner") or {}
    current_dog = (booking or {}).get("dog") or {}
    default_owner = next((i for i, o in enumerate(labels.values()) if o["id"] == current_owner.get("id")), None)
    mode = st.radio("Gazdi", ["Meglévő gazdi", "Új gazdi"], horizontal=True, index=0 if default_owner is not None else 1)
    selected_owner = None
    if mode == "Meglévő gazdi" and labels:
        selected_label = st.selectbox("Gazdi kiválasztása", list(labels), index=default_owner or 0)
        selected_owner = labels[selected_label]
        name, phone, email = selected_owner["full_name"], selected_owner["phone"], selected_owner["email"]
        owner_dogs = selected_owner.get("dogs") or []
        dog_labels = {f"{d['name']} | {d.get('breed') or 'ismeretlen fajta'}": d for d in owner_dogs}
    else:
        name = st.text_input("Gazdi neve", value=current_owner.get("full_name", ""))
        phone = st.text_input("Telefon", value=current_owner.get("phone", ""))
        email = st.text_input("E-mail", value=current_owner.get("email", ""))
        dog_labels = {}
    service = st.selectbox("Szolgáltatás", list(SERVICES), index=list(SERVICES).index((booking or {}).get("service")) if (booking or {}).get("service") in SERVICES else 0)
    edit_day = st.date_input("Nap", value=day)
    edit_slot = st.selectbox("Időpont", TIMES, index=TIMES.index(slot))
    newsletter = st.checkbox("Hírlevél", value=bool(current_owner.get("newsletter_subscribed", False)))
    if dog_labels:
        current_index = next((i for i, d in enumerate(dog_labels.values()) if d["id"] == current_dog.get("id")), 0)
        dog_choice = st.selectbox("Meglévő kutya", list(dog_labels) + ["+ Új kutya"], index=current_index)
        selected_dog = dog_labels.get(dog_choice)
    else:
        selected_dog = None
    dog_name = st.text_input("Kutya neve", value=(selected_dog or current_dog).get("name", ""))
    breed = st.text_input("Fajta", value=(selected_dog or current_dog).get("breed", "") or "")
    notes = st.text_area("Kutyával kapcsolatos megjegyzés", value=(selected_dog or current_dog).get("notes", "") or "")
    c1, c2 = st.columns(2)
    if c1.button("Mentés", type="primary", use_container_width=True):
        if not all([name.strip(), phone.strip(), email.strip(), dog_name.strip()]):
            st.error("A gazdi és a kutya kötelező adatait töltsd ki.")
            return
        owner_id = selected_owner["id"] if selected_owner else upsert_owner(name, phone, email, newsletter)
        if selected_owner:
            db().table("owners").update({"newsletter_subscribed": newsletter}).eq("id", owner_id).execute()
        dog_id = selected_dog["id"] if selected_dog else upsert_dog(owner_id, dog_name, breed, notes)
        if selected_dog:
            db().table("dogs").update({"breed": breed or None, "notes": notes or None}).eq("id", dog_id).execute()
        try:
            save_booking((booking or {}).get("id"), edit_day, edit_slot, service, owner_id, dog_id)
        except Exception:
            st.error("Az időpont foglalt, vagy adatbázishiba történt.")
            return
        st.rerun()
    if booking and c2.button("Foglalás törlése", use_container_width=True):
        db().table("bookings").update({"status": "cancelled", "cancelled_at": datetime.now(TZ).isoformat()}).eq("id", booking["id"]).execute()
        st.rerun()


def legend(view):
    st.markdown("**Színmagyarázat:**")
    if view == "Státusz szerint":
        items = [("🟦", "Aktív"), ("🟩", "Teljesített"), ("🟥", "Lemondott"), ("⬛", "Zárolt"), ("⬜", "Szabad")]
    else:
        items = [(SERVICE_MARKERS[name], name) for name in SERVICES] + [("⬜", "Szabad")]
    st.write("   ".join(f"{marker} {label}" for marker, label in items))


def calendar_button(row, day, slot, view):
    if row:
        owner = row.get("owner") or {}
        dog = row.get("dog") or {}
        marker = STATUS_MARKERS.get(row.get("status"), "⬜") if view == "Státusz szerint" else SERVICE_MARKERS.get(row.get("service"), "⬜")
        label = f"{marker} {slot} | {owner.get('full_name', 'Névtelen')} | {dog.get('name', '')} | {row.get('service', '')}"
    else:
        label = f"⬜ {slot} | Szabad"
    element_id = row["id"] if row else "free"
    if st.button(label, key=f"calendar_{day}_{slot}_{element_id}", use_container_width=True):
        booking_editor(day, slot, row)


def admin_calendar():
    data = get_bookings(True)
    selected = st.date_input("A hét egyik napja", datetime.now(TZ).date(), key="week_date")
    view = st.radio("Színezés", ["Státusz szerint", "Szolgáltatás szerint"], horizontal=True)
    statuses = st.multiselect("Megjelenített státuszok", ["active", "completed", "cancelled", "blocked"], default=["active", "completed"])
    legend(view)
    start = selected - timedelta(days=selected.weekday())
    for offset in range(7):
        day = start + timedelta(days=offset)
        st.subheader(day.strftime("%Y.%m.%d"))
        day_rows = [x for x in data if x["booking_date"] == day.isoformat() and x["status"] in statuses]
        for slot in TIMES:
            candidates = [x for x in day_rows if x["booking_time"] == slot]
            row = next((x for x in candidates if x["status"] == "active"), candidates[0] if candidates else None)
            calendar_button(row, day, slot, view)


def owners_admin():
    for owner in get_owners():
        with st.expander(f"{owner['full_name']} | {owner['email']} | {len(owner.get('dogs') or [])} kutya"):
            with st.form(f"owner_form_{owner['id']}"):
                name = st.text_input("Név", owner["full_name"])
                phone = st.text_input("Telefon", owner["phone"])
                email = st.text_input("E-mail", owner["email"])
                newsletter = st.checkbox("Hírlevél", owner.get("newsletter_subscribed", False))
                save = st.form_submit_button("Gazdi adatainak mentése")
            if save:
                db().table("owners").update({
                    "full_name": name.strip(), "phone": phone.strip(), "email": email.strip().lower(),
                    "newsletter_subscribed": newsletter, "updated_at": datetime.now(TZ).isoformat(),
                }).eq("id", owner["id"]).execute()
                st.rerun()
            st.write("**Kutyák:**", ", ".join(d["name"] for d in owner.get("dogs") or []) or "Nincs")
            st.write("**Korábbi és jelenlegi foglalások:**")
            st.dataframe(pd.DataFrame(owner.get("bookings") or []), use_container_width=True, hide_index=True)
            if st.button("Gazdi és kapcsolódó adatok törlése", key=f"delete_owner_{owner['id']}"):
                st.session_state[f"confirm_owner_{owner['id']}"] = True
            if st.session_state.get(f"confirm_owner_{owner['id']}"):
                st.warning("A végleges törlés a gazdi kutyáit és foglalásait is eltávolítja.")
                if st.button("Végleges törlés megerősítése", key=f"confirm_delete_owner_{owner['id']}"):
                    db().table("owners").delete().eq("id", owner["id"]).execute()
                    st.rerun()


def admin_page():
    st.title("Adminisztráció")
    if not admin_login():
        return
    tab1, tab2 = st.tabs(["📅 Heti naptár", "👤 Gazdik"])
    with tab1:
        admin_calendar()
    with tab2:
        owners_admin()


def booking_page():
    st.header("Időpontfoglalás")
    service = st.selectbox("Szolgáltatás", list(SERVICES), index=None)
    today = datetime.now(TZ).date()
    day = st.date_input("Nap", today, min_value=today, max_value=today + timedelta(days=90))
    busy = {x["booking_time"] for x in get_bookings(False) if x["booking_date"] == day.isoformat()}
    if st.session_state.get("slot_day") != day.isoformat():
        st.session_state.public_slot = None
        st.session_state.slot_day = day.isoformat()
    cols = st.columns(len(TIMES))
    for i, timeslot in enumerate(TIMES):
        disabled = timeslot in busy or day.weekday() > 4
        if cols[i].button(f"{timeslot}{' | Foglalt' if disabled else ''}", key=f"public_{day}_{timeslot}", disabled=disabled, use_container_width=True):
            st.session_state.public_slot = timeslot
    slot = st.session_state.get("public_slot")
    if slot:
        st.success(f"Kiválasztott időpont: {slot}")
    with st.form("public_booking"):
        name = st.text_input("Név")
        phone = st.text_input("Telefon")
        email = st.text_input("E-mail")
        dog = st.text_input("Kutya neve")
        breed = st.text_input("Fajta")
        notes = st.text_area("Megjegyzés")
        newsletter = st.checkbox("Kérek hírlevelet")
        privacy = st.checkbox("Elfogadom az adatkezelést")
        submit = st.form_submit_button("Foglalás", disabled=not (service and slot))
    if submit:
        if not all([name.strip(), phone.strip(), email.strip(), dog.strip(), privacy]):
            st.error("Töltsd ki a kötelező mezőket.")
            return
        owner_id = upsert_owner(name, phone, email, newsletter)
        dog_id = upsert_dog(owner_id, dog, breed, notes)
        booking_id = save_booking(None, day, slot, service, owner_id, dog_id)
        booking = db().table("bookings").select("*,owner:owners!bookings_owner_id_fkey(*),dog:dogs!bookings_dog_id_fkey(*)").eq("id", booking_id).single().execute().data
        try:
            send_confirmation(booking)
            st.success(f"Foglalás rögzítve: {day} {slot}. A visszaigazoló e-mailt elküldtük.")
        except Exception:
            st.warning(f"Foglalás rögzítve: {day} {slot}, de az e-mail küldése nem sikerült.")


def photos_page():
    st.header("Fényképek")
    st.info("Ide kerülhetnek a szalon és az elkészült frizurák képei.")


def home_page():
    st.header("Kutyakozmetika Miskolc")
    st.write("Kíméletes ápolás és egyszerű online időpontfoglalás.")


def token_action_page(action, token):
    records = db().table("action_tokens").select("*").eq("token_hash", token_hash(token)).eq("action", action).is_("used_at", "null").execute().data or []
    if not records:
        st.error("A link érvénytelen vagy már felhasználták.")
        return
    item = records[0]
    if item.get("expires_at") and datetime.fromisoformat(item["expires_at"].replace("Z", "+00:00")) < datetime.now(TZ):
        st.error("A link lejárt.")
        return
    if action == "cancel_booking":
        db().table("bookings").update({"status": "cancelled", "cancelled_at": datetime.now(TZ).isoformat()}).eq("id", item["booking_id"]).execute()
        message = "A foglalást lemondtuk."
    else:
        db().table("owners").update({"newsletter_subscribed": False}).eq("id", item["owner_id"]).execute()
        message = "A hírlevélről sikeresen leiratkoztál."
    db().table("action_tokens").update({"used_at": datetime.now(TZ).isoformat()}).eq("id", item["id"]).execute()
    st.success(message)
    st.page_link(st.Page(home_page, title="Kezdőlap"), label="Vissza a kezdőlapra", icon="🏠")


params = st.query_params
if params.get("admin") == "1":
    admin_page()
else:
    action, token = params.get("action"), params.get("t")
    home = st.Page(home_page, title="Kezdőlap", icon="🏠")
    booking = st.Page(booking_page, title="Időpontfoglalás", icon="📅")
    photos = st.Page(photos_page, title="Fényképek", icon="📷")
    if action and token:
        action_page = st.Page(lambda: token_action_page(action, token), title="Művelet eredménye", icon="🔗", default=True)
        navigation = st.navigation({"Főmenü": [home, booking, photos], "Művelet": [action_page]}, position="top")
    else:
        navigation = st.navigation({"Főmenü": [home, booking, photos]}, position="top")
    navigation.run()
