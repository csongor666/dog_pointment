# Kutyakozmetika Miskolc időpontfoglaló

Streamlit alkalmazás GitHub-alapú JSON adattárolással.

## Funkciók

- szolgáltatás, nap és időpont kiválasztása
- foglalt időpontok tiltása
- GitHub Contents API-alapú mentés
- SHA-ütközés kezelése párhuzamos foglalásoknál
- jelszóval védett adminoldal
- keresés, törlés és CSV-export

## GitHub repository létrehozása

1. Hozz létre egy privát repositoryt, például `kutyakozmetika-foglalas` néven.
2. Töltsd fel a projekt összes fájlját. A `.streamlit/secrets.toml` fájlt soha ne töltsd fel.
3. A repositoryban maradjon meg a `data/bookings.json` fájl.
4. Hozz létre fine-grained personal access tokent, amely csak ehhez a repositoryhoz fér hozzá.
5. A tokennek a **Contents: Read and write** jogosultság szükséges.

## Helyi futtatás

Másold át a mintafájlt:

```bash
cp .streamlit/secrets.example.toml .streamlit/secrets.toml
```

Windows PowerShellben:

```powershell
Copy-Item .streamlit/secrets.example.toml .streamlit/secrets.toml
```

Töltsd ki a valódi adatokat, majd:

```bash
python -m venv .venv
python -m pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud

1. Nyisd meg a `share.streamlit.io` oldalt.
2. Válaszd a **Create app** lehetőséget.
3. Add meg a repositoryt, a `main` ágat és az `app.py` fájlt.
4. Az **Advanced settings / Secrets** mezőbe másold a saját `secrets.toml` tartalmát.
5. Indítsd el a telepítést.

Publikus foglalási oldal:

```text
https://SAJAT-APP.streamlit.app/
```

Adminoldal:

```text
https://SAJAT-APP.streamlit.app/?admin=1
```

A külön adminlink nem biztonsági védelem, ezért az oldal az `ADMIN_PASSWORD` értékét is bekéri.

## Adatvédelem

A rendszer nevet és telefonszámot tárol. Éles használat előtt készíts adatkezelési tájékoztatót, határozz meg törlési időt, korlátozd a GitHub repository hozzáférését, és csak a szükséges adatokat gyűjtsd. A repository legyen privát.

## Korlát

A GitHub JSON-tárolás kis forgalmú induló rendszerhez megfelelő. Nagyobb forgalomnál célszerű tranzakciókat támogató adatbázisra, például PostgreSQL-re áttérni.
