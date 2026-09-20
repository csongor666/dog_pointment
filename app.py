import hmac,re
from datetime import date,datetime,time,timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from db import get_db
from email_service import send_confirmation
st.set_page_config(page_title="Kutyakozmetika Miskolc",page_icon="🐶",layout="wide")
DB=get_db(); TZ=ZoneInfo("Europe/Budapest")
SERVICES={"Kistestű nyírás":90,"Nagytestű nyírás":120,"Fürdetés":60,"Karomvágás":30}
STATUS={"active":"Aktív","completed":"Teljesítve","cancelled":"Lemondva","no_show":"Nem jelent meg"}
SERVICE_COLORS={"Kistestű nyírás":"#3b82f6","Nagytestű nyírás":"#8b5cf6","Fürdetés":"#06b6d4","Karomvágás":"#f97316"}
STATUS_COLORS={"active":"#eab308","completed":"#22c55e","cancelled":"#64748b","no_show":"#ef4444"}
PHONE=re.compile(r"^[+0-9][0-9 ()/-]{6,24}$"); EMAIL=re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
st.markdown('''<style>.block-container{max-width:1400px}.legend{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:5px}.slot{padding:5px;border-radius:6px;margin:2px 0;font-size:.82rem;text-align:center}.free{background:#dcfce7;color:#166534}.busy{background:#fef3c7;color:#854d0e}.closed{background:#e5e7eb;color:#4b5563}.dayhead{text-align:center;font-weight:700;padding:8px;background:#f8fafc;border-radius:8px}</style>''',unsafe_allow_html=True)

def secret(n,d=None):
    try:return st.secrets.get(n,d)
    except:return d

def pt(v): return time.fromisoformat(str(v)[:5]) if not isinstance(v,time) else v

def m(v): v=pt(v); return v.hour*60+v.minute

def monday(d): return d-timedelta(days=d.weekday())

def schedule(d):
    x=DB.table("opening_exceptions").select("*").eq("exception_date",d.isoformat()).limit(1).execute().data or []
    if x:
        x=x[0]; return {"open":not x["is_closed"],"from":x.get("open_time"),"to":x.get("close_time"),"step":x.get("slot_interval_min") or 30,"note":x.get("note") or ""}
    x=DB.table("business_hours").select("*").eq("weekday",d.weekday()).limit(1).execute().data or []
    if not x:return {"open":False,"note":"Nincs nyitvatartás"}
    x=x[0];return {"open":x["is_open"],"from":x.get("open_time"),"to":x.get("close_time"),"step":x.get("slot_interval_min") or 30,"note":""}

def day_bookings(d,statuses=None):
    q=DB.table("bookings").select("*,dog:dogs!bookings_dog_id_fkey(name,breed,notes)").eq("booking_date",d.isoformat())
    data=q.execute().data or []
    return [x for x in data if statuses is None or x.get("status") in statuses]

def slots(d,duration,exclude=None,admin=False):
    s=schedule(d)
    if not s.get("open") or not s.get("from"):return [],s
    occupied=[]
    for b in day_bookings(d,["active"]):
        if b["id"]==exclude:continue
        start=m(b["booking_time"]);occupied.append((start,start+int(b.get("duration_min") or 30)))
    cur,end=m(s["from"]),m(s["to"]);out=[];now=datetime.now(TZ);notice=0 if admin else int(secret("MIN_BOOKING_NOTICE_HOURS",12));buffer=int(secret("BOOKING_BUFFER_MIN",0))
    while cur+duration<=end:
        candidate=datetime.combine(d,time(cur//60,cur%60),TZ);ce=cur+duration+buffer
        if candidate>=now+timedelta(hours=notice) and not any(cur<be and ce>bs for bs,be in occupied):out.append(f"{cur//60:02d}:{cur%60:02d}")
        cur+=int(s["step"])
    return out,s

def week_nav(key):
    if key not in st.session_state:st.session_state[key]=monday(datetime.now(TZ).date())
    a,b,c=st.columns([1,4,1])
    if a.button("◀ Előző hét",key=key+"prev"):st.session_state[key]-=timedelta(days=7);st.rerun()
    b.markdown(f"### {st.session_state[key]} – {st.session_state[key]+timedelta(days=6)}")
    if c.button("Következő hét ▶",key=key+"next"):st.session_state[key]+=timedelta(days=7);st.rerun()
    return st.session_state[key]

def public_calendar(service):
    start=week_nav("user_week");days=[start+timedelta(days=i) for i in range(7)]; cols=st.columns(7)
    chosen=None
    for col,d in zip(cols,days):
        with col:
            st.markdown(f'<div class="dayhead">{["H","K","Sze","Cs","P","Szo","V"][d.weekday()]}<br>{d:%m.%d}</div>',unsafe_allow_html=True)
            free,s=slots(d,SERVICES[service]); bookings=day_bookings(d,["active"])
            if not s.get("open"):
                st.markdown('<div class="slot closed">Nem foglalható</div>',unsafe_allow_html=True);continue
            # Privacy-safe summary; no customer data.
            for b in bookings: st.markdown(f'<div class="slot busy">{str(b["booking_time"])[:5]} Foglalt</div>',unsafe_allow_html=True)
            for t in free:
                if st.button("🟢 "+t,key=f"pick_{d}_{t}",use_container_width=True): chosen=(d,t)
            if not free and not bookings:st.markdown('<div class="slot closed">Nincs megfelelő sáv</div>',unsafe_allow_html=True)
    return chosen

@st.dialog("Foglalás véglegesítése", width="large")
def save_public(service,d,t):
    st.info(f"Kiválasztott időpont: {d} {t} | {service} | {SERVICES[service]} perc")
    with st.form("customer_form"):
        c1,c2=st.columns(2)
        with c1:owner=st.text_input("Név *");phone=st.text_input("Telefon *");email=st.text_input("E-mail *")
        with c2:dog=st.text_input("Kutya neve *");breed=st.text_input("Fajta");note=st.text_area("Megjegyzés")
        privacy=st.checkbox("Elfogadom az adatkezelést. *");submit=st.form_submit_button("Foglalás elküldése",type="primary",use_container_width=True)
    if not submit:return
    owner,phone,email,dog=(" ".join(x.split()) for x in (owner,phone,email.lower(),dog))
    if len(owner)<3 or not PHONE.fullmatch(phone) or not EMAIL.fullmatch(email) or not dog or not privacy:st.error("Ellenőrizd a kötelező mezőket.");return
    with st.spinner("Foglalás mentése és e-mail küldése...",show_time=True):
        fresh,_=slots(d,SERVICES[service])
        if t not in fresh:st.error("Az időpont időközben foglalttá vált.");return
        found=DB.table("dogs").select("id").eq("customer_email",email).ilike("name",dog).limit(1).execute().data or []
        dp={"customer_name":owner,"customer_phone":phone,"customer_email":email,"breed":breed or None,"notes":note or None}
        if found: dog_id=found[0]["id"];DB.table("dogs").update(dp).eq("id",dog_id).execute()
        else:dp["name"]=dog;dog_id=DB.table("dogs").insert(dp).execute().data[0]["id"]
        rec={"booking_date":d.isoformat(),"booking_time":t,"service":service,"duration_min":SERVICES[service],"customer_name":owner,"phone":phone,"email":email,"dog_id":dog_id,"status":"active"}
        saved=DB.table("bookings").insert(rec).execute().data[0];ok,error=send_confirmation(saved)
    st.success(f"Foglalás rögzítve: {d} {t}")
    if not ok:st.warning("A foglalás sikerült, de az e-mail nem ment el.")
    st.session_state.pop("chosen_slot", None)
    st.caption("A párbeszédablak bezárható az X gombbal.")

def public():
    st.title("🐶 Kutyakozmetika Miskolc")
    st.write("Először válassz szolgáltatást. A heti naptár csak ezután jelenik meg.")

    service = st.selectbox(
        "Válassz szolgáltatást",
        list(SERVICES),
        index=None,
        placeholder="Szolgáltatás kiválasztása",
        key="public_service",
    )

    if not service:
        st.info("A heti naptár a szolgáltatás kiválasztása után jelenik meg.")
        return

    st.caption(f"A kiválasztott szolgáltatás időtartama: {SERVICES[service]} perc")
    st.markdown(
        '<span class="legend" style="background:#dcfce7"></span>Szabad &nbsp; '
        '<span class="legend" style="background:#fef3c7"></span>Foglalt &nbsp; '
        '<span class="legend" style="background:#e5e7eb"></span>Nem foglalható',
        unsafe_allow_html=True,
    )

    picked = public_calendar(service)
    if picked:
        st.session_state.chosen_slot = picked

    if st.session_state.get("chosen_slot"):
        selected_date, selected_time = st.session_state.chosen_slot
        save_public(service, selected_date, selected_time)

def admin_login():
    if st.session_state.get("admin"):return True
    with st.form("login"):p=st.text_input("Admin jelszó",type="password");go=st.form_submit_button("Belépés")
    if go and hmac.compare_digest(p,str(secret("ADMIN_PASSWORD",""))):st.session_state.admin=True;st.rerun()
    if go:st.error("Hibás jelszó")
    return False

def admin_calendar():
    start=week_nav("admin_week");mode=st.radio("Színezés",["Státusz szerint","Szolgáltatás szerint"],horizontal=True);days=[start+timedelta(days=i) for i in range(7)]
    cols=st.columns(7)
    for col,d in zip(cols,days):
        with col:
            sch=schedule(d);data=day_bookings(d);capacity=(m(sch["to"])-m(sch["from"])) if sch.get("open") else 0;used=sum(int(x.get("duration_min") or 0) for x in data if x["status"]=="active");pct=round(100*used/capacity) if capacity else 0
            st.markdown(f'<div class="dayhead">{["H","K","Sze","Cs","P","Szo","V"][d.weekday()]} {d:%m.%d}<br>{used}/{capacity} perc ({pct}%)</div>',unsafe_allow_html=True)
            if not sch.get("open"):st.markdown('<div class="slot closed">Zárva</div>',unsafe_allow_html=True)
            for b in data:
                color=STATUS_COLORS[b["status"]] if mode.startswith("Státusz") else SERVICE_COLORS.get(b["service"],"#eab308")
                st.markdown(f'<div class="slot" style="background:{color};color:white">{str(b["booking_time"])[:5]} {b["customer_name"]}<br>{b["service"]}</div>',unsafe_allow_html=True)
                if st.button("Szerkesztés",key=f"caledit_{b['id']}",use_container_width=True):st.session_state.edit_booking_id=b["id"]
            free,_=slots(d,30,admin=True)
            for t in free[:12]:st.markdown(f'<div class="slot free">{t} Szabad</div>',unsafe_allow_html=True)

def edit_selected():
    bid=st.session_state.get("edit_booking_id")
    if not bid:return
    rows=DB.table("bookings").select("*,dog:dogs!bookings_dog_id_fkey(name,breed,notes)").eq("id",bid).limit(1).execute().data or []
    if not rows:return
    b=rows[0];dog=b.get("dog") or {};st.subheader("Foglalás közvetlen szerkesztése")
    with st.form("direct_edit"):
        c1,c2=st.columns(2)
        with c1:d=st.date_input("Dátum",date.fromisoformat(b["booking_date"]));service=st.selectbox("Szolgáltatás",list(SERVICES),index=list(SERVICES).index(b["service"]));status=st.selectbox("Státusz",list(STATUS),format_func=STATUS.get,index=list(STATUS).index(b["status"]))
        with c2:
            avail,_=slots(d,SERVICES[service],exclude=b["id"],admin=True);current=str(b["booking_time"])[:5];choices=sorted(set(avail+[current]));t=st.selectbox("Idő",choices,index=choices.index(current));name=st.text_input("Név",b["customer_name"]);phone=st.text_input("Telefon",b["phone"]);email=st.text_input("E-mail",b.get("email") or "")
        dogname=st.text_input("Kutya neve",dog.get("name") or "");breed=st.text_input("Fajta",dog.get("breed") or "");note=st.text_area("Megjegyzés",dog.get("notes") or "")
        save=st.form_submit_button("Mentés",type="primary")
    if save:
        if status=="active" and t not in slots(d,SERVICES[service],exclude=b["id"],admin=True)[0] and not(d.isoformat()==b["booking_date"] and t==current and service==b["service"]):st.error("Az időpont nem szabad.");return
        DB.table("bookings").update({"booking_date":d.isoformat(),"booking_time":t,"service":service,"duration_min":SERVICES[service],"status":status,"customer_name":name,"phone":phone,"email":email,"updated_at":datetime.now(TZ).isoformat()}).eq("id",b["id"]).execute()
        if b.get("dog_id"):DB.table("dogs").update({"name":dogname,"breed":breed or None,"notes":note or None,"customer_name":name,"customer_phone":phone,"customer_email":email}).eq("id",b["dog_id"]).execute()
        st.success("Mentve");st.session_state.pop("edit_booking_id",None);st.rerun()
    c1,c2=st.columns(2)
    if c1.button("Visszaigazolás újraküldése"):
        with st.spinner("Küldés...",show_time=True):ok,error=send_confirmation(b,"manual")
        st.success("Elküldve") if ok else st.error(error)
    if c2.button("Szerkesztő bezárása"):st.session_state.pop("edit_booking_id",None);st.rerun()

def admin():
    st.title("🔒 Adminnaptár")
    if not admin_login():return
    admin_calendar();st.divider();edit_selected()

admin() if st.query_params.get("admin","0")=="1" else public()
