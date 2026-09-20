import os,smtplib
from datetime import datetime,timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo
from supabase import create_client
TZ=ZoneInfo("Europe/Budapest");db=create_client(os.environ["SUPABASE_URL"],os.environ["SUPABASE_SECRET_KEY"]);target=(datetime.now(TZ).date()+timedelta(days=1)).isoformat()
rows=db.table("bookings").select("id,booking_date,booking_time,service,customer_name,email").eq("booking_date",target).eq("status","active").is_("reminder_sent_at","null").execute().data or []
failed=0
for b in rows:
 try:
  msg=EmailMessage();msg["From"]=os.environ["GMAIL_ADDRESS"];msg["To"]=b["email"];msg["Subject"]="Emlékeztető a holnapi időpontról";msg.set_content(f"Kedves {b['customer_name']}!\n\nHolnap {str(b['booking_time'])[:5]}-kor várunk.\n{b['service']}\n\nKutyakozmetika Miskolc")
  with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:s.login(os.environ["GMAIL_ADDRESS"],os.environ["GMAIL_APP_PASSWORD"].replace(" ",""));s.send_message(msg)
  db.table("bookings").update({"reminder_sent_at":datetime.now(TZ).isoformat(),"last_email_error":None}).eq("id",b["id"]).execute();db.table("email_logs").insert({"booking_id":b["id"],"email_type":"reminder","recipient":b["email"],"subject":msg["Subject"],"success":True}).execute()
 except Exception as e: failed+=1; print(e)
print(f"sent={len(rows)-failed}, failed={failed}");raise SystemExit(1 if failed else 0)
