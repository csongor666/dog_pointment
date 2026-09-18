# Kutyakozmetika Miskolc, Streamlit + Supabase

## Mi változott?

A foglalások már nem GitHub JSON-fájlba, hanem Supabase PostgreSQL-adatbázisba kerülnek. A publikus GitHub repository csak a programkódot tartalmazza.

## 1. Adatbázis

A Supabase SQL Editorban futtasd a `supabase_schema.sql` fájlt.

## 2. Streamlit Secrets

A `.streamlit/secrets.example.toml` fájlt másold `.streamlit/secrets.toml` néven, majd töltsd ki. A valódi fájlt ne töltsd fel GitHubra.

Ehhez a verzióhoz **secret key** szükséges, nem publishable key. A secret key a Streamlit szerveroldali Secrets-ben marad, és nem kerül a böngészőbe vagy a nyilvános repositoryba.

## 3. Helyi futtatás

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

## 4. Streamlit Community Cloud

- Repository: a publikus GitHub repository
- Branch: `main`
- Main file: `app.py`
- App settings / Secrets: másold be a kitöltött `secrets.toml` tartalmát

Foglalási oldal:

```text
https://SAJAT-APP.streamlit.app/
```

Admin:

```text
https://SAJAT-APP.streamlit.app/?admin=1
```

## Biztonság

- A `SUPABASE_SECRET_KEY` soha ne kerüljön GitHubra.
- A `.streamlit/secrets.toml` szerepel a `.gitignore` fájlban.
- A `bookings` táblán RLS aktív, és nincs anon olvasási policy.
- A publikus látogató csak a Streamlit felület által visszaadott szabad/foglalt állapotot látja.
- Az adminoldalt külön URL és jelszó védi.
- Éles használathoz készíts adatkezelési tájékoztatót és törlési szabályt.
