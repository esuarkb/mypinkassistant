# backup_prod_db.py
#
# Nightly local backup of the production Postgres database.
#
# Runs on the iMac via launchd (com.mk.db-backup.plist) at 6:30 AM local,
# after the nightly FULL_SYNC batch on Render finishes (~5:30 AM CDT).
# Safe to run manually anytime: venv/bin/python backup_prod_db.py
#
# - Dumps to ~/MPA_Backups/mpa_YYYY-MM-DD.dump (pg_dump custom format, gzip-9)
# - Verifies the dump with pg_restore --list before trusting it
# - Keeps the last RETENTION_DAYS daily dumps, plus every first-of-month forever
# - Texts via ProjectBroadcast on any failure (same alert path as the worker)
# - Pings BACKUP_HEARTBEAT_URL (Better Stack heartbeat) after a verified backup
#
# Read-only against production. Restore procedure: RESTORE.md

import os
import sys
import subprocess
from datetime import date, datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from dotenv import load_dotenv, dotenv_values

load_dotenv(PROJECT_DIR / ".env")  # PB_API_KEY / PB_CONTACT_ID / BACKUP_HEARTBEAT_URL

PG_BIN = Path("/usr/local/opt/libpq/bin")  # Homebrew libpq (pg_dump 18.x, matches Render)
BACKUP_DIR = Path.home() / "MPA_Backups"
RETENTION_DAYS = 60
MIN_DUMP_BYTES = 1_000_000   # current verified dump is ~5.8 MB; well under this = broken
MIN_TABLE_DATA = 20          # production has 28 data tables today


def _alert(message: str) -> None:
    try:
        from alerts import send_failure_text
        send_failure_text(message)
    except Exception as e:
        print("[Backup] Could not send failure text:", e)


def _fail(stage: str, detail: str) -> None:
    print(f"[Backup] FAILED at {stage}: {detail}")
    _alert(f"Nightly DB backup failed ({stage}): {detail[:300]}")
    sys.exit(1)


def _prune(today: date) -> None:
    for f in sorted(BACKUP_DIR.glob("mpa_*.dump")):
        try:
            d = datetime.strptime(f.name, "mpa_%Y-%m-%d.dump").date()
        except ValueError:
            continue
        if d.day == 1:  # monthly keeper
            continue
        if (today - d).days > RETENTION_DAYS:
            f.unlink()
            print(f"[Backup] Pruned {f.name}")
    # clean up leftovers from any previous failed run
    for f in BACKUP_DIR.glob("mpa_*.part"):
        f.unlink()
        print(f"[Backup] Removed stale partial {f.name}")


def run() -> None:
    db_url = (dotenv_values(PROJECT_DIR / ".env.production").get("DATABASE_URL") or "").strip()
    if not db_url:
        _fail("config", "DATABASE_URL missing from .env.production")

    BACKUP_DIR.mkdir(exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)

    today = date.today()
    final = BACKUP_DIR / f"mpa_{today.isoformat()}.dump"
    part = final.with_suffix(".part")

    print(f"[Backup] {datetime.now():%Y-%m-%d %H:%M:%S} dumping to {final.name}")
    try:
        r = subprocess.run(
            [str(PG_BIN / "pg_dump"), db_url, "--format=custom", "--compress=9",
             "--no-owner", "--no-privileges", "-f", str(part)],
            capture_output=True, text=True, timeout=900,
        )
    except subprocess.TimeoutExpired:
        _fail("pg_dump", "timed out after 15 minutes")
    if r.returncode != 0:
        _fail("pg_dump", r.stderr.strip()[-300:])

    size = part.stat().st_size
    if size < MIN_DUMP_BYTES:
        _fail("size check", f"dump is only {size:,} bytes")

    v = subprocess.run(
        [str(PG_BIN / "pg_restore"), "--list", str(part)],
        capture_output=True, text=True, timeout=120,
    )
    if v.returncode != 0:
        _fail("verify", v.stderr.strip()[-300:])
    table_data = v.stdout.count("TABLE DATA")
    if table_data < MIN_TABLE_DATA:
        _fail("verify", f"only {table_data} TABLE DATA entries in dump TOC")

    os.chmod(part, 0o600)
    part.replace(final)
    print(f"[Backup] OK — {size / 1_000_000:.1f} MB, {table_data} tables verified")

    _prune(today)

    heartbeat = (os.getenv("BACKUP_HEARTBEAT_URL") or "").strip()
    if heartbeat:
        try:
            import requests
            requests.get(heartbeat, timeout=10)
            print("[Backup] Heartbeat pinged")
        except Exception as e:
            print("[Backup] Heartbeat ping failed:", e)
    else:
        print("[Backup] BACKUP_HEARTBEAT_URL not set — skipping heartbeat")


if __name__ == "__main__":
    run()
