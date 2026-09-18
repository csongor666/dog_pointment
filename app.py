import hmac, smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Kutyakozmetika Miskolc", page_icon="🐶", layout="wide")
TZ=ZoneInfo("Europe/Budapest")
SERVICES={"Kistestű nyírás":90,"Nagytestű nyírás":120,"Fürdetés":60,"Karomvágás":30}
TIMES=["09:00","10:30","13:00","15:00"]

@st.cache_resource
def db(): return create_client(st.secrets["SUPABASE_URL"],st.secrets["SUPABASE_SECRET_KEY"])

def send_mail(to,subject,body):
    msg=EmailMessage(); msg["From"]=st.secrets["GMAIL_ADDRESS"]; msg["To"]=to; msg["Subject"]=subject; msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
        s.login(st.secrets["GMAIL_ADDRESS"],st.secrets["GMAIL_APP_PASSWORD"]); s.send_message(msg)

def rows(date=None):
    q=db().table("bookings").select("*,dogs(name,breed,notes)").eq("status","active")
    if date: q=q.eq("booking_date",date)
    return q.order("booking_date").order("booking_time").execute().data or []

def admin():
    st.title("🔒 Admin és naptár")
    if not st.session_state.get("admin"):
        with st.form("login"):
            p=st.text_input("Jelszó",type="password"); ok=st.form_submit_button("Belépés")
        if ok and hmac.compare_digest(p,str(st.secrets["ADMIN_PASSWORD"])): st.session_state.admin=True; st.rerun()
        if ok: st.error("Hibás jelszó")
        return
    data=rows(); today=datetime.now(TZ).date()
    c1,c2,c3=st.columns(3); c1.metric("Aktív",len(data)); c2.metric("Mai",sum(x["booking_date"]==today.isoformat() for x in data)); c3.metric("Kutyák",len({x.get("dog_id") for x in data if x.get("dog_id")}))
    tab1,tab2,tab3=st.tabs(["Naptár","Foglalások","Kutyatörzs és előzmények"])
    with tab1:
        d=st.date_input("Nap",today); day=[x for x in data if x["booking_date"]==d.isoformat()]
        for t in TIMES:
            b=next((x for x in day if x["booking_time"]==t),None)
            st.write(f"**{t}**  "+(f"{b['customer_name']} | {b['service']}" if b else "🟢 Szabad"))
    with tab2:
        q=st.text_input("Keresés")
        shown=[x for x in data if not q or q.casefold() in str(x).casefold()]
        for b in shown:
            with st.container(border=True):
                a,z=st.columns([5,1]); dog=b.get("dogs") or {}; a.write(f"**{b['booking_date']} {b['booking_time']}** | {b['customer_name']} | {b['service']} | {b['phone']} | {b['email']}"); a.caption(f"Kutya: {dog.get('name','')} | {dog.get('breed','')} | {dog.get('notes','')}")
                if z.button("Törlés",key=b['id']): db().table("bookings").update({"status":"cancelled"}).eq("id",b['id']).execute(); st.rerun()
        st.download_button("CSV",pd.DataFrame(shown).to_csv(index=False).encode("utf-8-sig"),"foglalasok.csv")
    with tab3:
        dogs=db().table("dogs").select("*,bookings(booking_date,booking_time,service,status)").order("customer_name").execute().data or []
        for d in dogs:
            with st.expander(f"{d['name']} ({d.get('breed') or 'ismeretlen fajta'}) | Gazdi: {d['customer_name']}"):
                st.write(d.get('notes') or "Nincs megjegyzés"); hist=[x for x in d.get('bookings',[]) if x.get('status')=='active']; st.dataframe(hist,use_container_width=True,hide_index=True)

def public():
    st.title("🐶 Kutyakozmetika Miskolc")
    service=st.selectbox("Szolgáltatás",list(SERVICES),index=None); d=st.date_input("Nap",datetime.now(TZ).date(),min_value=datetime.now(TZ).date(),max_value=datetime.now(TZ).date()+timedelta(days=90))
    busy={x['booking_time'] for x in rows(d.isoformat())}; available=[] if d.weekday()>4 else [x for x in TIMES if x not in busy]
    slot=st.radio("Szabad időpont",available,horizontal=True,index=None) if available else None
    with st.form("book"):
        name=st.text_input("Név"); phone=st.text_input("Telefon"); email=st.text_input("E-mail"); dog=st.text_input("Kutya neve"); breed=st.text_input("Fajta"); notes=st.text_area("Kutya megjegyzés"); privacy=st.checkbox("Elfogadom az adatkezelést"); submit=st.form_submit_button("Foglalás",disabled=not(service and slot))
    if submit:
        if not all([name.strip(),phone.strip(),email.strip(),dog.strip(),privacy]): st.error("Töltsd ki a kötelező mezőket."); return
        existing=db().table("dogs").select("id").eq("customer_email",email.strip().lower()).eq("name",dog.strip()).execute().data
        if existing: dog_id=existing[0]['id']; db().table("dogs").update({"breed":breed.strip() or None,"notes":notes.strip() or None,"customer_name":name.strip(),"customer_phone":phone.strip()}).eq("id",dog_id).execute()
        else: dog_id=db().table("dogs").insert({"name":dog.strip(),"breed":breed.strip() or None,"notes":notes.strip() or None,"customer_name":name.strip(),"customer_phone":phone.strip(),"customer_email":email.strip().lower()}).execute().data[0]['id']
        rec={"booking_date":d.isoformat(),"booking_time":slot,"service":service,"duration_min":SERVICES[service],"customer_name":name.strip(),"phone":phone.strip(),"email":email.strip().lower(),"dog_id":dog_id,"status":"active"}
        try:
            db().table("bookings").insert(rec).execute(); send_mail(rec['email'],"Foglalás visszaigazolása",f"Kedves {name}!\n\nFoglalásod rögzítettük: {d} {slot}, {service}.\n\nKutyakozmetika Miskolc"); st.success(f"Köszönjük! Időpontja rögzítve: {d} {slot}")
        except Exception as e: st.error("Nem sikerült a foglalás vagy az e-mail küldése. Ellenőrizd a beállításokat.")

admin() if st.query_params.get("admin","0")=="1" else public()
