from functools import lru_cache
import streamlit as st
from supabase import Client, create_client

@st.cache_resource
def get_db() -> Client:
    url=st.secrets.get("SUPABASE_URL","")
    key=st.secrets.get("SUPABASE_SECRET_KEY","")
    if not url or not key:
        raise RuntimeError("Hiányzó SUPABASE_URL vagy SUPABASE_SECRET_KEY.")
    return create_client(url,key)
