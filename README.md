# Miskolci Kutyakozmetika MVP

Streamlit frontend, Supabase adatbázis és hitelesítés, nyilvános GitHub repóhoz előkészítve.

## Funkciók
- nyilvános szolgáltatáslista
- időpontkérés Supabase-be
- admin belépés e-mail/jelszóval
- időpontok szűrése és állapotkezelése
- Row Level Security szabályok
- titkok kizárása Gitből

## 1. Supabase
1. Hozz létre projektet.
2. SQL Editorban futtasd a `supabase_schema.sql` fájlt.
3. Authentication > Users alatt hozz létre admin felhasználót.
4. Futtasd az SQL-fájl végén lévő admin-profil beszúrást a saját e-mail-címeddel.
5. Project Settings > API alatt másold ki a Project URL-t és a publishable key-t. Soha ne tedd a service role kulcsot a Streamlit alkalmazásba.

## 2. Helyi futtatás
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
streamlit run app.py
```
Windows alatt a `secrets.toml.example` kézzel is lemásolható `secrets.toml` néven. Töltsd ki a Supabase URL-t és publishable key-t.

## 3. GitHub
```bash
git init
git add .
git commit -m "Initial Streamlit Supabase MVP"
git branch -M main
git remote add origin https://github.com/FELHASZNALO/REPO.git
git push -u origin main
```
A `.gitignore` miatt a valódi titkok nem kerülnek a nyilvános repóba.

## 4. Streamlit Community Cloud
1. New app, majd válaszd ki a GitHub repót és az `app.py` fájlt.
2. App settings > Secrets alatt add meg:
```toml
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_REPLACE_ME"
```
3. Deploy.

## Élesítés előtt
- valós árak, cím, nyitvatartás és elérhetőség
- adatkezelési tájékoztató és törlési folyamat
- spamvédelem vagy rate limit
- e-mailes visszaigazolás Edge Functionnel vagy tranzakciós e-mail szolgáltatóval
- időpontütközések és üzleti nyitvatartás szerveroldali ellenőrzése
