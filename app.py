from datetime import date, datetime, time, timedelta
import pandas as pd
import streamlit as st
from supabase_client import get_supabase

st.set_page_config(page_title="Miskolci Kutyakozmetika", page_icon="🐕", layout="wide")

SERVICES = {
    "Teljes kozmetika, kistestű": 9500,
    "Teljes kozmetika, közepes testű": 13500,
    "Teljes kozmetika, nagytestű": 17500,
    "Fürdetés és szárítás": 7000,
    "Karomvágás": 2500,
    "Konzultáció": 0,
}

def db():
    try:
        return get_supabase()
    except Exception as exc:
        st.error(f"Adatbázis-kapcsolati hiba: {exc}")
        st.stop()

def flash():
    msg = st.session_state.pop("flash", None)
    if msg:
        st.success(msg)

def is_admin() -> bool:
    return bool(st.session_state.get("admin_user"))

def login_panel():
    with st.form("login"):
        email = st.text_input("E-mail")
        password = st.text_input("Jelszó", type="password")
        submitted = st.form_submit_button("Belépés", use_container_width=True)
    if submitted:
        try:
            response = db().auth.sign_in_with_password({"email": email, "password": password})
            user = response.user
            profile = db().table("profiles").select("role,full_name").eq("id", user.id).single().execute()
            if not profile.data or profile.data.get("role") != "admin":
                db().auth.sign_out()
                st.error("Ehhez a fiókhoz nincs adminisztrátori jogosultság.")
            else:
                st.session_state.admin_user = {"id": user.id, "email": user.email, **profile.data}
                st.rerun()
        except Exception as exc:
            st.error(f"Sikertelen belépés: {exc}")

def booking_page():
    st.header("Időpontkérés")
    st.caption("Az időpont az adminisztrátori visszaigazolás után válik véglegessé.")
    min_day = date.today() + timedelta(days=1)
    with st.form("booking", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            owner_name = st.text_input("Gazdi neve *", max_chars=120)
            email = st.text_input("E-mail *", max_chars=200)
            phone = st.text_input("Telefonszám *", max_chars=40)
            dog_name = st.text_input("Kutya neve *", max_chars=100)
        with c2:
            breed = st.text_input("Fajta", max_chars=120)
            service = st.selectbox("Szolgáltatás *", list(SERVICES))
            appt_date = st.date_input("Kért nap *", min_value=min_day, value=min_day)
            appt_time = st.time_input("Kért időpont *", value=time(9, 0), step=1800)
        notes = st.text_area("Megjegyzés, viselkedés, egészségügyi tudnivaló", max_chars=1000)
        privacy = st.checkbox("Elfogadom, hogy az adataimat az időpont egyeztetéséhez kezeljék. *")
        sent = st.form_submit_button("Időpontkérés elküldése", type="primary", use_container_width=True)
    if sent:
        if not all(x.strip() for x in [owner_name, email, phone, dog_name]) or not privacy:
            st.error("Töltsd ki a kötelező mezőket és fogadd el az adatkezelést.")
            return
        if "@" not in email:
            st.error("Adj meg érvényes e-mail-címet.")
            return
        payload = {
            "owner_name": owner_name.strip(), "email": email.strip().lower(), "phone": phone.strip(),
            "dog_name": dog_name.strip(), "breed": breed.strip() or None, "service": service,
            "price_huf": SERVICES[service], "appointment_at": datetime.combine(appt_date, appt_time).isoformat(),
            "notes": notes.strip() or None, "status": "pending"
        }
        try:
            db().table("appointments").insert(payload).execute()
            st.session_state.flash = "Köszönjük! Az időpontkérést rögzítettük."
            st.rerun()
        except Exception as exc:
            st.error(f"A mentés nem sikerült: {exc}")

def admin_page():
    st.header("Adminisztráció")
    if not is_admin():
        login_panel(); return
    st.caption(f"Belépve: {st.session_state.admin_user.get('full_name') or st.session_state.admin_user['email']}")
    if st.button("Kijelentkezés"):
        try: db().auth.sign_out()
        except Exception: pass
        st.session_state.pop("admin_user", None); st.rerun()
    status_filter = st.multiselect("Állapot", ["pending", "confirmed", "completed", "cancelled"], default=["pending", "confirmed"])
    try:
        query = db().table("appointments").select("*").order("appointment_at")
        if status_filter:
            query = query.in_("status", status_filter)
        rows = query.execute().data or []
    except Exception as exc:
        st.error(f"Lekérdezési hiba: {exc}"); return
    if not rows:
        st.info("Nincs a szűrésnek megfelelő időpont."); return
    df = pd.DataFrame(rows)
    show_cols = [c for c in ["appointment_at", "owner_name", "phone", "dog_name", "breed", "service", "price_huf", "status"] if c in df.columns]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)
    labels = {f"{r['appointment_at']} | {r['dog_name']} | {r['owner_name']}": r["id"] for r in rows}
    selected_label = st.selectbox("Időpont kiválasztása", labels.keys())
    selected = next(r for r in rows if r["id"] == labels[selected_label])
    with st.form("update"):
        new_status = st.selectbox("Új állapot", ["pending", "confirmed", "completed", "cancelled"], index=["pending", "confirmed", "completed", "cancelled"].index(selected["status"]))
        admin_note = st.text_area("Belső megjegyzés", value=selected.get("admin_note") or "")
        save = st.form_submit_button("Módosítás mentése", type="primary")
    if save:
        try:
            db().table("appointments").update({"status": new_status, "admin_note": admin_note.strip() or None}).eq("id", selected["id"]).execute()
            st.success("Módosítás elmentve."); st.rerun()
        except Exception as exc:
            st.error(f"Sikertelen módosítás: {exc}")

def main():
    st.title("🐕 Miskolci Kutyakozmetika")
    flash()
    page = st.sidebar.radio("Menü", ["Kezdőlap", "Időpontkérés", "Admin"])
    if page == "Kezdőlap":
        st.subheader("Kíméletes ápolás, átlátható időpontfoglalás")
        st.write("Ez az MVP bemutatja a nyilvános szolgáltatáslistát, az időpontkérést és a védett adminisztrációt.")
        cols = st.columns(3)
        for i, (name, price) in enumerate(SERVICES.items()):
            with cols[i % 3]:
                st.metric(name, "Egyedi ár" if price == 0 else f"{price:,} Ft".replace(",", " "))
        st.info("Cím, nyitvatartás, telefonszám és adatkezelési tájékoztató a végleges induláskor illesztendő be.")
    elif page == "Időpontkérés": booking_page()
    else: admin_page()

if __name__ == "__main__":
    main()
