import smtplib
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo
import streamlit as st
from db import get_db
from cancellation import append_cancellation_footer
TZ=ZoneInfo("Europe/Budapest")

def _log(booking_id,email_type,recipient,subject,success,error=None):
    try:
        get_db().table("email_logs").insert({"booking_id":booking_id,"email_type":email_type,"recipient":recipient or "nincs megadva","subject":subject,"success":success,"error_message":str(error)[:2000] if error else None}).execute()
    except Exception as exc: print("Email log error:",exc)

def send_confirmation(booking,email_type="confirmation"):
    recipient=(booking.get("email") or "").strip(); subject="Foglalás visszaigazolása"
    if not recipient: return False,"Nincs e-mail-cím."
    body=f"Kedves {booking['customer_name']}!\n\nFoglalásod rögzítettük:\n{booking['booking_date']} {str(booking['booking_time'])[:5]}\n{booking['service']}\n\nKutyakozmetika Miskolc"
    body=append_cancellation_footer(body, booking)
    msg=EmailMessage(); msg["From"]=st.secrets["GMAIL_ADDRESS"]; msg["To"]=recipient; msg["Subject"]=subject; msg.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com",465,timeout=30) as smtp:
            smtp.login(st.secrets["GMAIL_ADDRESS"],st.secrets["GMAIL_APP_PASSWORD"].replace(" ","")); smtp.send_message(msg)
        _log(booking["id"],email_type,recipient,subject,True)
        get_db().table("bookings").update({"confirmation_sent_at":datetime.now(TZ).isoformat(),"last_email_error":None}).eq("id",booking["id"]).execute()
        return True,None
    except Exception as exc:
        _log(booking["id"],email_type,recipient,subject,False,exc)
        try: get_db().table("bookings").update({"last_email_error":str(exc)[:2000]}).eq("id",booking["id"]).execute()
        except Exception: pass
        return False,str(exc)
