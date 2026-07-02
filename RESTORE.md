# Production database restore runbook

Backups: `~/MPA_Backups/mpa_YYYY-MM-DD.dump` on the iMac — nightly at 6:30 AM
local via launchd (`com.mk.db-backup.plist`), created by `backup_prod_db.py`.
Custom-format `pg_dump`, gzip-compressed, verified with `pg_restore --list`
before being kept. Last 60 days retained, plus every 1st-of-month forever.

The Postgres client tools live at `/usr/local/opt/libpq/bin/` (not on PATH).

## Scenario A — Render database lost or corrupted (full disaster recovery)

1. **Pause the job queue** (admin panel) so workers don't write mid-restore.
2. In the Render dashboard, create a **new Postgres instance** (same region,
   Postgres 18+). Copy its **External Database URL**.
3. Restore the most recent dump into it:

   ```
   /usr/local/opt/libpq/bin/pg_restore \
       --no-owner --no-privileges \
       --dbname="<NEW_EXTERNAL_DATABASE_URL>" \
       ~/MPA_Backups/mpa_YYYY-MM-DD.dump
   ```

   Takes a few minutes at current size. `--no-owner` is required because the
   new instance has a different DB user than the one that made the dump.
4. Spot-check the restored data:

   ```
   /usr/local/opt/libpq/bin/psql "<NEW_EXTERNAL_DATABASE_URL>" \
       -c "SELECT COUNT(*) FROM customers;" \
       -c "SELECT COUNT(*) FROM order_items;" \
       -c "SELECT email, billing_status FROM consultants ORDER BY id DESC LIMIT 5;"
   ```
5. Update the `DATABASE_URL` env var on **both** the web service and the
   worker service in Render (use the **Internal** Database URL there), and in
   `.env.production` on the iMac (External URL).
6. Wait for both services to redeploy, then **unpause the job queue**.
7. Note: anything that happened between the backup time (6:30 AM) and the
   failure is lost — new customers/orders entered that day may need to be
   re-entered, and the next nightly FULL_SYNC will re-pull InTouch data.

## Scenario B — inspect an old backup / fire-drill test restore

The iMac has only Postgres client tools, no server. To restore locally:

```
brew install postgresql@18
brew services start postgresql@18
/usr/local/opt/postgresql@18/bin/createdb mpa_restore_test
/usr/local/opt/libpq/bin/pg_restore --no-owner --no-privileges \
    --dbname=mpa_restore_test ~/MPA_Backups/mpa_YYYY-MM-DD.dump
/usr/local/opt/libpq/bin/psql mpa_restore_test -c "SELECT COUNT(*) FROM customers;"
```

Drop it afterward: `dropdb mpa_restore_test`. Worth doing once a quarter.

## What the dump does NOT contain

- **Env vars / secrets** — `MK_ENC_KEY` (decrypts `intouch_password_enc` in the
  dump), Stripe, OpenAI, Resend, ProjectBroadcast keys. These live in the local
  `.env` and in the Render dashboard. Without `MK_ENC_KEY`, restored InTouch
  credentials are undecryptable and every consultant would have to re-enter
  them in Settings.
- **The application itself** — code is in git; Render services rebuild from
  the repo.

## Monitoring

- Any failure (dump, size check, verify) sends a ProjectBroadcast text, same
  path as worker failure alerts.
- After a verified backup the script pings `BACKUP_HEARTBEAT_URL` (Better
  Stack heartbeat) if set in `.env` — Better Stack alerts if a day's ping
  never arrives.
- Log: `logs/backup.log`.
