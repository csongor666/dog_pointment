# Kutyakozmetika v2

1. Futtasd a `supabase_schema_v2.sql` fájlt a Supabase SQL Editorban.
2. Töltsd fel a fájlokat GitHubra.
3. Streamlit Secrets: a `secrets.example.toml` alapján.
4. GitHub Settings > Secrets and variables > Actions alatt vedd fel ugyanazt a négy szolgáltatási titkot.
5. Actions alatt engedélyezd és kézzel teszteld a Daily reminders workflow-t.

Admin: `?admin=1`. A cron 06:00 UTC-kor fut, ami Berlin/Budapest szerint télen 07:00, nyáron 08:00.
