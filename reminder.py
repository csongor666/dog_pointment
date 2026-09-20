import os, smtplib, sys
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo
from supabase import create_client
TZ=ZoneInfo("Europe/Budapest")
def env(name):
    value=os.environ.get(name,"").strip()
    if not value: raise RuntimeError(f"Hiányzó secret: {name}")
    return value
def main():
    try:
        url,key,address,password=[env(x) for x in ("SUPABASE_URL","SUPABASE_SECRET_KEY","GMAIL_ADDRESS","GMAIL_APP_PASSWORD")]
        db=create_client(url,key); target=(datetime.now(TZ).date()+timedelta(days=1)).isoformat()
        rows=(db.table("bookings").select("id,booking_date,booking_time,service,customer_name,email")
              .eq("booking_date",target).eq("status","active").eq("is_demo",False).is_("reminder_sent_at","null").execute().data or [])
        print(f"[INFO] Küldendő emlékeztetők: {len(rows)}")
        failed=0
        for b in rows:
            try:
                msg=EmailMessage(); msg["From"]=address; msg["To"]=b["email"]; msg["Subject"]="Emlékeztető a holnapi időpontról"; msg.set_content(f"Kedves {b['customer_name']}!\n\nHolnap {b['booking_time']}-kor várunk. Szolgáltatás: {b['service']}.\n\nKutyakozmetika Miskolc")
                with smtplib.SMTP_SSL("smtp.gmail.com",465,timeout=30) as smtp: smtp.login(address,password); smtp.send_message(msg)
                db.table("bookings").update({"reminder_sent_at":datetime.now(TZ).isoformat()}).eq("id",b["id"]).execute(); print(f"[OK] {b['id']}")
            except Exception as exc: failed+=1; print(f"[ERROR] {b['id']}: {type(exc).__name__}: {exc}",file=sys.stderr)
        return 1 if failed else 0
    except Exception as exc:
        print(f"[FATAL] {type(exc).__name__}: {exc}",file=sys.stderr); return 1
if __name__=="__main__": raise SystemExit(main())
