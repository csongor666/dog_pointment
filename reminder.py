import os,smtplib
from datetime import datetime,timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo
from supabase import create_client
TZ=ZoneInfo("Europe/Budapest"); db=create_client(os.environ["SUPABASE_URL"],os.environ["SUPABASE_SECRET_KEY"]); target=(datetime.now(TZ).date()+timedelta(days=1)).isoformat()
rows=db.table("bookings").select("id,booking_date,booking_time,service,customer_name,email,reminder_sent_at").eq("booking_date",target).eq("status","active").is_("reminder_sent_at","null").execute().data or []
for b in rows:
 msg=EmailMessage(); msg["From"]=os.environ["GMAIL_ADDRESS"]; msg["To"]=b["email"]; msg["Subject"]="Emlékeztető a holnapi kutyakozmetikai időpontról"; msg.set_content(f"Kedves {b['customer_name']}!\n\nHolnap {b['booking_time']}-kor várunk. Szolgáltatás: {b['service']}.\n\nKutyakozmetika Miskolc")
 with smtplib.SMTP_SSL("smtp.gmail.com",465) as s: s.login(os.environ["GMAIL_ADDRESS"],os.environ["GMAIL_APP_PASSWORD"]); s.send_message(msg)
 db.table("bookings").update({"reminder_sent_at":datetime.now(TZ).isoformat()}).eq("id",b["id"]).execute()
print(f"Sent: {len(rows)}")
