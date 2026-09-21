import hmac
import smtplib
import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Kutyakozmetika Miskolc V5", page_icon="🐶", layout="wide")
TZ = ZoneInfo("Europe/Budapest")
SERVICES = {"Kistestű nyírás": 90, "Nagytestű nyírás": 120, "Fürdetés": 60, "Karomvágás": 30}
TIMES = ["09:00", "10:30", "13:00", "15:00"]

@st.cache_resource
def db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SECRET_KEY"])

def send_mail(to, subject, body):
    msg=EmailMessage(); msg["From"]=st.secrets["GMAIL_ADDRESS"]; msg["To"]=to; msg["Subject"]=subject; msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com",465,timeout=30) as smtp:
        smtp.login(st.secrets["GMAIL_ADDRESS"],st.secrets["GMAIL_APP_PASSWORD"]); smtp.send_message(msg)

def confirmation_body(row):
    dog = row.get("dog") or {}
    return (
        f"Kedves {row['customer_name']}!\n\n"
        f"Foglalásod visszaigazoljuk: {row['booking_date']} "
        f"{row['booking_time']}, {row['service']}.\n"
        f"Kutya: {dog.get('name') or 'nincs megadva'}\n\n"
        "Kutyakozmetika Miskolc"
    )


def reminder_body(row):
    return (
        f"Kedves {row['customer_name']}!\n\n"
        f"Emlékeztetünk a kutyakozmetikai időpontra: "
        f"{row['booking_date']} {row['booking_time']}.\n"
        f"Szolgáltatás: {row['service']}\n\n"
        "Kutyakozmetika Miskolc"
    )


def booking_action_buttons(row, key_prefix):
    booking_id = row["id"]
    email = (row.get("email") or "").strip()
    cols = st.columns(4)

    if cols[0].button("✉️ E-mail", key=f"{key_prefix}_mail_{booking_id}", disabled=not email, use_container_width=True):
        try:
            send_mail(email, "Üzenet a Kutyakozmetika Miskolctól", f"Kedves {row['customer_name']}!\n\nEz egy üzenet a Kutyakozmetika Miskolctól.")
            st.success(f"E-mail elküldve: {email}")
        except Exception as exc:
            st.error(f"Az e-mail küldése nem sikerült: {type(exc).__name__}")

    if cols[1].button("✅ Visszaigazolás", key=f"{key_prefix}_confirm_{booking_id}", disabled=not email, use_container_width=True):
        try:
            send_mail(email, "Kutyakozmetikai foglalás visszaigazolása", confirmation_body(row))
            db().table("bookings").update({"confirmation_sent_at": datetime.now(TZ).isoformat()}).eq("id", booking_id).execute()
            st.success("A visszaigazolást elküldtük.")
        except Exception as exc:
            st.error(f"A visszaigazolás küldése nem sikerült: {type(exc).__name__}")

    if cols[2].button("⏰ Emlékeztető", key=f"{key_prefix}_reminder_{booking_id}", disabled=not email, use_container_width=True):
        try:
            send_mail(email, "Emlékeztető a kutyakozmetikai időpontról", reminder_body(row))
            db().table("bookings").update({"reminder_sent_at": datetime.now(TZ).isoformat()}).eq("id", booking_id).execute()
            st.success("Az emlékeztetőt elküldtük.")
        except Exception as exc:
            st.error(f"Az emlékeztető küldése nem sikerült: {type(exc).__name__}")

    if cols[3].button("🗑️ Törlés", key=f"{key_prefix}_delete_{booking_id}", use_container_width=True):
        db().table("bookings").update({
            "status": "cancelled",
            "cancelled_at": datetime.now(TZ).isoformat(),
        }).eq("id", booking_id).execute()
        st.success("A foglalást töröltük.")
        st.rerun()


def bookings(day=None, include_cancelled=False):
    q=db().table("bookings").select("*,dog:dogs!bookings_dog_id_fkey(id,name,breed,notes)")
    if not include_cancelled: q=q.eq("status","active")
    if day: q=q.eq("booking_date",day)
    return q.order("booking_date").order("booking_time").execute().data or []

def admin_login():
    if st.session_state.get("admin"): return True
    with st.form("login"):
        password=st.text_input("Admin jelszó",type="password"); submitted=st.form_submit_button("Belépés")
    if submitted and hmac.compare_digest(password,str(st.secrets["ADMIN_PASSWORD"])):
        st.session_state.admin=True; st.rerun()
    if submitted: st.error("Hibás jelszó")
    return False

def admin_page():
    st.title("🔒 Adminisztráció V5")
    if not admin_login(): return
    top1,top2=st.columns(2)
    if top1.button("Frissítés",use_container_width=True): st.rerun()
    if top2.button("Kijelentkezés",use_container_width=True): st.session_state.admin=False; st.rerun()
    data=bookings(include_cancelled=True); today=datetime.now(TZ).date().isoformat()
    active=[x for x in data if x["status"]=="active"]
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Aktív",len(active)); c2.metric("Mai",sum(x["booking_date"]==today for x in active)); c3.metric("Visszaigazolatlan e-mail",sum(not x.get("confirmation_sent_at") for x in active)); c4.metric("Minta rekord",sum(x.get("is_demo",False) for x in data))
    tab1,tab2,tab3=st.tabs(["📅 Naptár","📋 Foglalások","🐕 Kutyatörzs és előzmények"])
    with tab1:
        selected=st.date_input("A hét egyik napja",datetime.now(TZ).date(),key="calendar_day")
        week_start=selected-timedelta(days=selected.weekday())
        week_days=[week_start+timedelta(days=i) for i in range(7)]
        st.caption(f"Hét: {week_days[0]} – {week_days[-1]}")
        for current_day in week_days:
            st.subheader(current_day.strftime("%Y.%m.%d. %A"))
            day_rows=[x for x in active if x["booking_date"]==current_day.isoformat()]
            for slot in TIMES:
                row=next((x for x in day_rows if x["booking_time"]==slot),None)
                if row:
                    dog=row.get("dog") or {}
                    with st.container(border=True):
                        st.markdown(f"**{slot} | {row['customer_name']} | {dog.get('name','')} | {row['service']}**")
                        st.caption(f"{row.get('phone','')} | {row.get('email','')}")
                        booking_action_buttons(row, f"week_{current_day.isoformat()}_{slot.replace(':','')}")
                else:
                    st.success(f"{slot} | Szabad")

    with tab2:
        states=st.multiselect("Állapot",["active","cancelled","completed"],default=["active"])
        search=st.text_input("Keresés név, telefon, e-mail, kutya vagy szolgáltatás alapján")
        shown=[x for x in data if x["status"] in states and (not search or search.casefold() in str(x).casefold())]
        for row in shown:
            dog=row.get("dog") or {}
            with st.container(border=True):
                a,b=st.columns([5,1]); a.write(f"**{row['booking_date']} {row['booking_time']}** | {row['customer_name']} | {row['service']}"); a.caption(f"{row['phone']} | {row['email']} | Kutya: {dog.get('name','')} ({dog.get('breed') or 'nincs megadva'})")
                new=b.selectbox("Állapot",["active","completed","cancelled"],index=["active","completed","cancelled"].index(row['status']) if row['status'] in ["active","completed","cancelled"] else 0,key=f"s_{row['id']}")
                if b.button("Mentés",key=f"u_{row['id']}"):
                    db().table("bookings").update({"status":new,"cancelled_at":datetime.now(TZ).isoformat() if new=="cancelled" else None}).eq("id",row["id"]).execute(); st.rerun()
        export=pd.DataFrame(shown)
        st.download_button("CSV letöltése",export.to_csv(index=False).encode("utf-8-sig"),"foglalasok_v5.csv",use_container_width=True)
    with tab3:
        dogs=db().table("dogs").select("*,bookings(booking_date,booking_time,service,status)").order("customer_name").execute().data or []
        for dog in dogs:
            with st.expander(f"{dog['name']} | {dog.get('breed') or 'ismeretlen'} | Gazdi: {dog['customer_name']}"):
                st.write(f"Telefon: {dog['customer_phone']} | E-mail: {dog['customer_email']}"); st.write("Megjegyzés:",dog.get("notes") or "Nincs")
                st.dataframe(pd.DataFrame(dog.get("bookings") or []),use_container_width=True,hide_index=True)

def public_page():
    st.title("🐶 Kutyakozmetika Miskolc")
    service=st.selectbox("Válassz szolgáltatást",list(SERVICES),index=None)
    today=datetime.now(TZ).date(); day=st.date_input("Válassz napot",today,min_value=today,max_value=today+timedelta(days=90))
    busy={x["booking_time"] for x in bookings(day.isoformat())}
    if "selected_slot" not in st.session_state:
        st.session_state.selected_slot=None
    if st.session_state.selected_slot in busy or day.weekday()>4:
        st.session_state.selected_slot=None
    st.write("Válassz időpontot")
    slot_cols=st.columns(len(TIMES))
    for index, timeslot in enumerate(TIMES):
        occupied=timeslot in busy or day.weekday()>4
        label=f"{timeslot}\nFoglalt" if occupied else timeslot
        if slot_cols[index].button(label,key=f"public_slot_{day.isoformat()}_{timeslot}",disabled=occupied,use_container_width=True):
            st.session_state.selected_slot=timeslot
            st.rerun()
    slot=st.session_state.selected_slot
    if slot:
        st.success(f"Kiválasztott időpont: {slot}")
    elif day.weekday()>4:
        st.warning("Hétvégére jelenleg nincs online foglalás.")
    elif len(busy)==len(TIMES):
        st.warning("Erre a napra nincs foglalható időpont.")
    with st.form("booking"):
        c1,c2=st.columns(2)
        name=c1.text_input("Név *"); phone=c1.text_input("Telefon *"); email=c1.text_input("E-mail *")
        dog_name=c2.text_input("Kutya neve *"); breed=c2.text_input("Fajta"); notes=st.text_area("Kutyával kapcsolatos tartós megjegyzés")
        privacy=st.checkbox("Elfogadom az adatkezelést *"); submitted=st.form_submit_button("Időpont foglalása",disabled=not(service and slot),use_container_width=True)
    if submitted:
        if not all([name.strip(),phone.strip(),email.strip(),dog_name.strip(),privacy]) or "@" not in email:
            st.error("Töltsd ki helyesen a kötelező mezőket."); return
        normalized=email.strip().lower()
        found=db().table("dogs").select("id").eq("customer_email",normalized).ilike("name",dog_name.strip()).execute().data or []
        if found:
            dog_id=found[0]["id"]; db().table("dogs").update({"breed":breed.strip() or None,"notes":notes.strip() or None,"customer_name":name.strip(),"customer_phone":phone.strip()}).eq("id",dog_id).execute()
        else:
            dog_id=db().table("dogs").insert({"name":dog_name.strip(),"breed":breed.strip() or None,"notes":notes.strip() or None,"customer_name":name.strip(),"customer_phone":phone.strip(),"customer_email":normalized}).execute().data[0]["id"]
        record={"id":str(uuid.uuid4()),"booking_date":day.isoformat(),"booking_time":slot,"service":service,"duration_min":SERVICES[service],"customer_name":name.strip(),"phone":phone.strip(),"email":normalized,"dog_id":dog_id,"status":"active","is_demo":False}
        try:
            db().table("bookings").insert(record).execute()
        except Exception:
            st.error("Az időpont időközben foglalttá vált, vagy adatbázishiba történt."); return
        try:
            send_mail(normalized,"Kutyakozmetikai foglalás visszaigazolása",f"Kedves {name}!\n\nFoglalásod rögzítettük: {day} {slot}, {service}.\n\nKutyakozmetika Miskolc")
            db().table("bookings").update({"confirmation_sent_at":datetime.now(TZ).isoformat()}).eq("id",record["id"]).execute()
            st.success(f"Köszönjük! Időpontja rögzítve: {day} {slot}. A visszaigazoló e-mailt elküldtük.")
        except Exception:
            st.warning(f"Az időpont rögzítve: {day} {slot}, de az e-mail küldése nem sikerült. Az adminfelületről ellenőrizhető.")

admin_page() if st.query_params.get("admin","0")=="1" else public_page()
