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
SERVICES = {"Kistestű nyírás": 90, "Nagytestű nyírás": 120, "Fürdetés": 60, "Karomvágás": 30}
STATUSES = {"active":"Aktív", "completed":"Teljesítve", "cancelled":"Lemondva", "no_show":"Nem jelent meg"}
WEEKDAYS = {0:"Hétfő",1:"Kedd",2:"Szerda",3:"Csütörtök",4:"Péntek",5:"Szombat",6:"Vasárnap"}
PHONE_RE=re.compile(r"^[+0-9][0-9 ()/-]{6,24}$")
EMAIL_RE=re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

def secret(name, default=None):
    try: return st.secrets.get(name, default)
    except Exception: return default

@st.cache_resource
def db()->Client:
    return create_client(secret("SUPABASE_URL"),secret("SUPABASE_SECRET_KEY"))

def parse_time(v):
    if isinstance(v,time): return v.replace(second=0,microsecond=0)
    return time.fromisoformat(str(v)[:5])

def mins(v): v=parse_time(v); return v.hour*60+v.minute

def hhmm(v): return parse_time(v).strftime("%H:%M")

def log_email(booking_id, email_type, recipient, subject, success, error=None):
    try:
        db().table("email_logs").insert({
            "booking_id": booking_id,
            "email_type": email_type,
            "recipient": recipient,
            "subject": subject,
            "success": success,
            "error_message": str(error)[:2000] if error else None,
        }).execute()
    except Exception as log_error:
        print(f"E-mail naplózási hiba: {log_error}")

def send_email(booking, email_type="confirmation"):
    recipient=booking.get("email","").strip()
    if not recipient: raise ValueError("A foglaláshoz nincs e-mail-cím.")
    if email_type in ("confirmation", "manual"):
        subject="Foglalás visszaigazolása"
        body=f"Kedves {booking['customer_name']}!\n\nFoglalásod rögzítettük:\n{booking['booking_date']} {booking['booking_time']}\n{booking['service']}\n\nKutyakozmetika Miskolc"
        timestamp_field="confirmation_sent_at"
    else:
        subject="Kutyakozmetikai értesítés"
        body=f"Kedves {booking['customer_name']}!\n\nIdőpontod adatai:\n{booking['booking_date']} {booking['booking_time']}\n{booking['service']}\n\nKutyakozmetika Miskolc"
        timestamp_field=None
    msg=EmailMessage(); msg["From"]=secret("GMAIL_ADDRESS"); msg["To"]=recipient; msg["Subject"]=subject; msg.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com",465,timeout=30) as smtp:
            smtp.login(secret("GMAIL_ADDRESS"),secret("GMAIL_APP_PASSWORD").replace(" ","")); smtp.send_message(msg)
        log_email(booking["id"], email_type, recipient, subject, True)
        if timestamp_field:
            try:
                db().table("bookings").update({
                    timestamp_field: datetime.now(TZ).isoformat(),
                    "last_email_error": None,
                }).eq("id", booking["id"]).execute()
            except Exception as update_error:
                print(f"E-mail állapotfrissítési hiba: {update_error}")
        return True, None
    except Exception as exc:
        log_email(booking["id"], email_type, recipient, subject, False, exc)
        try:
            db().table("bookings").update({
                "last_email_error": str(exc)[:2000]
            }).eq("id", booking["id"]).execute()
        except Exception as update_error:
            print(f"E-mail hibaállapot mentési hiba: {update_error}")
        return False, str(exc)

def day_schedule(d):
    ex=db().table("opening_exceptions").select("*").eq("exception_date",d.isoformat()).limit(1).execute().data or []
    if ex:
        x=ex[0]; return {"is_open":not x["is_closed"],"open_time":x.get("open_time"),"close_time":x.get("close_time"),"slot_interval_min":x.get("slot_interval_min") or 30,"note":x.get("note") or ""}
    rows=db().table("business_hours").select("*").eq("weekday",d.weekday()).limit(1).execute().data or []
    if not rows: return {"is_open":False,"note":"Nincs beállított nyitvatartás."}
    x=rows[0]; return {"is_open":x["is_open"],"open_time":x.get("open_time"),"close_time":x.get("close_time"),"slot_interval_min":x.get("slot_interval_min") or 30,"note":""}

def bookings_on(d, exclude_id=None):
    q=db().table("bookings").select("id,booking_time,duration_min").eq("booking_date",d.isoformat()).eq("status","active")
    data=q.execute().data or []
    return [x for x in data if x["id"]!=exclude_id]

def available_slots(d,duration,exclude_id=None):
    sch=day_schedule(d)
    if not sch.get("is_open") or not sch.get("open_time"): return [],sch
    start,end=mins(sch["open_time"]),mins(sch["close_time"]); interval=int(sch["slot_interval_min"]); buffer_min=int(secret("BOOKING_BUFFER_MIN",0))
    occupied=[]
    for b in bookings_on(d,exclude_id):
        s=mins(b["booking_time"]); occupied.append((s,s+int(b.get("duration_min") or 30)+buffer_min))
    now=datetime.now(TZ); notice=int(secret("MIN_BOOKING_NOTICE_HOURS",12)); result=[]; cursor=start
    while cursor+duration<=end:
        candidate=datetime.combine(d,time(cursor//60,cursor%60),TZ); cend=cursor+duration+buffer_min
        if candidate>=now+timedelta(hours=notice) and not any(cursor<e and cend>s for s,e in occupied): result.append(f"{cursor//60:02d}:{cursor%60:02d}")
        cursor+=interval
    return result,sch

def get_or_create_dog(owner,phone,email,name,breed,notes):
    found=db().table("dogs").select("id").eq("customer_email",email).ilike("name",name).limit(1).execute().data or []
    payload={"customer_name":owner,"customer_phone":phone,"customer_email":email,"breed":breed or None,"notes":notes or None}
    if found:
        dog_id=found[0]["id"]; db().table("dogs").update(payload).eq("id",dog_id).execute(); return dog_id
    payload["name"]=name; return db().table("dogs").insert(payload).execute().data[0]["id"]

def public_page():
    st.title("🐶 Kutyakozmetika Miskolc")
    service=st.selectbox("Szolgáltatás",list(SERVICES),index=None)
    today=datetime.now(TZ).date(); d=st.date_input("Nap",today,min_value=today,max_value=today+timedelta(days=int(secret("BOOKING_DAYS_AHEAD",90))))
    slots,sch=available_slots(d,SERVICES[service]) if service else ([],day_schedule(d))
    if not sch.get("is_open"): st.warning(sch.get("note") or "Ezen a napon zárva tartunk.")
    elif service: st.caption(f"Nyitvatartás: {hhmm(sch['open_time'])}–{hhmm(sch['close_time'])}")
    slot=st.radio("Szabad időpont",slots,horizontal=True,index=None) if slots else None
    with st.form("booking"):
        c1,c2=st.columns(2)
        with c1: owner=st.text_input("Név *"); phone=st.text_input("Telefon *"); email=st.text_input("E-mail *")
        with c2: dog_name=st.text_input("Kutya neve *"); breed=st.text_input("Fajta"); notes=st.text_area("Megjegyzés")
        privacy=st.checkbox("Elfogadom az adatkezelést. *")
        submit=st.form_submit_button("Időpont foglalása",type="primary",use_container_width=True,disabled=not(service and slot))
    if not submit:return
    owner,phone,email,dog_name=(" ".join(x.split()) for x in (owner,phone,email.lower(),dog_name))
    if len(owner)<3 or not PHONE_RE.fullmatch(phone) or not EMAIL_RE.fullmatch(email) or not dog_name or not privacy:
        st.error("Ellenőrizd a kötelező adatokat."); return
    with st.spinner("Foglalás mentése és visszaigazolás küldése...",show_time=True):
        try:
            fresh,_=available_slots(d,SERVICES[service])
            if slot not in fresh: st.error("Az időpont időközben foglalttá vált."); return
            dog_id=get_or_create_dog(owner,phone,email,dog_name,breed.strip(),notes.strip())
            rec={"booking_date":d.isoformat(),"booking_time":slot,"service":service,"duration_min":SERVICES[service],"customer_name":owner,"phone":phone,"email":email,"dog_id":dog_id,"status":"active"}
            saved=db().table("bookings").insert(rec).execute().data[0]
            ok,error=send_email(saved,"confirmation")
        except APIError as exc:
            st.error("Az időpont foglalt vagy az adatbázis visszautasította a mentést." if "23505" in str(exc) else f"Adatbázishiba: {exc}"); return
        except Exception as exc: st.error(f"A foglalás nem sikerült: {exc}"); return
    st.success(f"Köszönjük! Időpontja rögzítve: {d} {slot}")
    if not ok: st.warning("A foglalás sikerült, de a visszaigazoló e-mail nem ment el. Az admin később újraküldheti.")

def admin_login():
    if st.session_state.get("admin"): return True
    with st.form("login"):
        p=st.text_input("Admin jelszó",type="password"); submit=st.form_submit_button("Belépés")
    if submit and hmac.compare_digest(p,str(secret("ADMIN_PASSWORD",""))): st.session_state.admin=True; st.rerun()
    if submit: st.error("Hibás jelszó.")
    return False

def weekly_editor():
    rows=db().table("business_hours").select("*").order("weekday").execute().data or []; by={x["weekday"]:x for x in rows}
    with st.form("weekly"):
        edited=[]
        for wd in range(7):
            x=by.get(wd,{}); c=st.columns([1.4,1,1,1,1]); c[0].markdown(f"**{WEEKDAYS[wd]}**")
            opened=c[1].checkbox("Nyitva",x.get("is_open",wd<5),key=f"o{wd}"); ot=c[2].time_input("Nyitás",parse_time(x.get("open_time") or "09:00"),key=f"ot{wd}"); ct=c[3].time_input("Zárás",parse_time(x.get("close_time") or "17:00"),key=f"ct{wd}"); inter=c[4].selectbox("Időköz",[15,30,45,60],index=[15,30,45,60].index(int(x.get("slot_interval_min") or 30)),key=f"i{wd}")
            edited.append({"weekday":wd,"is_open":opened,"open_time":ot.strftime("%H:%M"),"close_time":ct.strftime("%H:%M"),"slot_interval_min":inter})
        save=st.form_submit_button("Mentés")
    if save:
        if any(x["is_open"] and x["open_time"]>=x["close_time"] for x in edited): st.error("Hibás nyitási idő.")
        else: db().table("business_hours").upsert(edited,on_conflict="weekday").execute(); st.success("Mentve.")

def exceptions_editor():
    with st.form("exception"):
        d=st.date_input("Dátum",min_value=datetime.now(TZ).date()); closed=st.checkbox("Egész nap zárva",True); c=st.columns(3); ot=c[0].time_input("Nyitás",time(9),disabled=closed); ct=c[1].time_input("Zárás",time(17),disabled=closed); inter=c[2].selectbox("Időköz",[15,30,45,60],index=1,disabled=closed); note=st.text_input("Megjegyzés"); save=st.form_submit_button("Mentés")
    if save:
        payload={"exception_date":d.isoformat(),"is_closed":closed,"open_time":None if closed else ot.strftime("%H:%M"),"close_time":None if closed else ct.strftime("%H:%M"),"slot_interval_min":inter,"note":note or None}; db().table("opening_exceptions").upsert(payload,on_conflict="exception_date").execute(); st.success("Mentve.")
    for x in db().table("opening_exceptions").select("*").gte("exception_date",datetime.now(TZ).date().isoformat()).order("exception_date").execute().data or []:
        a,b=st.columns([5,1]); a.write(f"{x['exception_date']} | {'Zárva' if x['is_closed'] else hhmm(x['open_time'])+'–'+hhmm(x['close_time'])} | {x.get('note') or ''}")
        if b.button("Törlés",key=f"ex{x['id']}"): db().table("opening_exceptions").delete().eq("id",x["id"]).execute(); st.rerun()

def edit_booking(item):
    dog=item.get("dog") or {}
    with st.form(f"edit_{item['id']}"):
        c1,c2=st.columns(2)
        with c1:
            d=st.date_input("Dátum",date.fromisoformat(item["booking_date"]),key=f"d{item['id']}"); service=st.selectbox("Szolgáltatás",list(SERVICES),index=list(SERVICES).index(item["service"]),key=f"s{item['id']}"); status=st.selectbox("Státusz",list(STATUSES),format_func=lambda x:STATUSES[x],index=list(STATUSES).index(item["status"]),key=f"st{item['id']}")
        with c2:
            slots,_=available_slots(d,SERVICES[service],item["id"]); current=item["booking_time"][:5]
            choices=sorted(set(slots+[current])); selected_time=st.selectbox("Idő",choices,index=choices.index(current),key=f"t{item['id']}"); name=st.text_input("Ügyfél neve",item["customer_name"]); phone=st.text_input("Telefon",item["phone"]); email=st.text_input("E-mail",item.get("email") or "")
        dog_name=st.text_input("Kutya neve",dog.get("name") or ""); breed=st.text_input("Fajta",dog.get("breed") or ""); notes=st.text_area("Kutya megjegyzés",dog.get("notes") or "")
        save=st.form_submit_button("Módosítások mentése",type="primary")
    if save:
        if not PHONE_RE.fullmatch(phone) or not EMAIL_RE.fullmatch(email): st.error("Hibás telefon vagy e-mail."); return
        if status=="active" and selected_time not in available_slots(d,SERVICES[service],item["id"])[0] and not(d.isoformat()==item["booking_date"] and selected_time==current and service==item["service"]): st.error("Az új időpont nem szabad."); return
        with st.spinner("Módosítások mentése...",show_time=True):
            upd={"booking_date":d.isoformat(),"booking_time":selected_time,"service":service,"duration_min":SERVICES[service],"customer_name":name.strip(),"phone":phone.strip(),"email":email.strip().lower(),"status":status,"updated_at":datetime.now(TZ).isoformat()}
            db().table("bookings").update(upd).eq("id",item["id"]).execute()
            if item.get("dog_id"): db().table("dogs").update({"name":dog_name.strip(),"breed":breed.strip() or None,"notes":notes.strip() or None,"customer_name":name.strip(),"customer_phone":phone.strip(),"customer_email":email.strip().lower()}).eq("id",item["dog_id"]).execute()
        st.success("A foglalás módosítva."); st.rerun()

def bookings_admin():
    data=db().table("bookings").select("*,dog:dogs!bookings_dog_id_fkey(name,breed,notes)").order("booking_date").order("booking_time").execute().data or []
    statuses=st.multiselect("Státusz",list(STATUSES),default=["active"],format_func=lambda x:STATUSES[x]); q=st.text_input("Keresés")
    data=[x for x in data if (not statuses or x["status"] in statuses) and (not q or q.casefold() in str(x).casefold())]
    for item in data:
        sent="✅" if item.get("confirmation_sent_at") else "⚠️"
        with st.expander(f"{item['booking_date']} {item['booking_time'][:5]} | {item['customer_name']} | {item['service']} | {STATUSES[item['status']]} | E-mail {sent}"):
            edit_booking(item)
            c1,c2=st.columns(2)
            if c1.button("Visszaigazolás újraküldése",key=f"mail{item['id']}"):
                with st.spinner("E-mail küldése...",show_time=True): ok,error=send_email(item,"manual")
                st.success("E-mail elküldve.") if ok else st.error(f"E-mail hiba: {error}")
            if item.get("last_email_error"): c2.warning(item["last_email_error"])
    if data: st.download_button("CSV",pd.DataFrame(data).to_csv(index=False).encode("utf-8-sig"),"foglalasok.csv")

def email_log_admin():
    logs=db().table("email_logs").select("*").order("created_at",desc=True).limit(500).execute().data or []
    if not logs: st.info("Még nincs e-mail-napló."); return
    df=pd.DataFrame(logs); st.dataframe(df[[c for c in ["created_at","recipient","email_type","success","subject","error_message"] if c in df]],use_container_width=True,hide_index=True)

def admin_page():
    st.title("🔒 Adminisztráció")
    if not admin_login(): return
    if st.button("Kijelentkezés"): st.session_state.admin=False; st.rerun()
    t1,t2,t3,t4=st.tabs(["Foglalások","E-mail napló","Nyitvatartás","Egyedi napok"])
    with t1: bookings_admin()
    with t2: email_log_admin()
    with t3: weekly_editor()
    with t4: exceptions_editor()

admin_page() if st.query_params.get("admin","0")=="1" else public_page()
