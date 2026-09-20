# Kutyakozmetika V5

Felhasználói és admin heti naptár, színezett sávok, kapacitás és közvetlen szerkesztés.

## Frissítés
1. A V3 és V4 migrációk legyenek telepítve.
2. Futtasd a supabase_v5_migration.sql fájlt.
3. Töltsd fel a fájlokat GitHubra.
4. Rebootold a Streamlit appot.


## V5.1 teljesítményjavítás
- Hetenként egy publikus Supabase-lekérdezéscsomag, nem naponként több kérés.
- 20 másodperces cache csak a személyes adatot nem tartalmazó publikus naptárhoz.
- Adminnaptár fragmentként fut, így a szerkesztési kattintás nem építi újra a teljes appot.
- A szerkesztő azonnal valódi párbeszédablakban nyílik meg.
- A szabad időpontok zöld háttérrel, a foglaltak sárga, a nem foglalhatók szürke háttérrel jelennek meg.
