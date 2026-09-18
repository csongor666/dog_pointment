import os
import streamlit as st
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

def _secret(name: str) -> str:
    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    return value or os.getenv(name, "")

@st.cache_resource
def get_supabase() -> Client:
    url = _secret("SUPABASE_URL")
    key = _secret("SUPABASE_PUBLISHABLE_KEY") or _secret("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Hiányzó SUPABASE_URL vagy SUPABASE_PUBLISHABLE_KEY.")
    return create_client(url, key)
