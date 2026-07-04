"""
Read-only production query runner — THE way to query prod Postgres.

All sessions (Fable, Opus, Sonnet, subagents) must use this instead of raw
psycopg2 against DATABASE_URL: it physically cannot write.

Two enforcement layers:
  1. Validation — single statement, must start with SELECT or WITH,
     write keywords refused.
  2. Server-side — the connection opens with default_transaction_read_only=on,
     so even a write smuggled past validation (e.g. inside a CTE) is rejected
     by Postgres itself: "cannot execute ... in a read-only transaction".

Usage:
    venv/bin/python mpa_query.py "SELECT COUNT(*) FROM consultants"
    venv/bin/python mpa_query.py -            # read the query from stdin
    venv/bin/python mpa_query.py --csv "..."  # CSV output instead of table

Row cap: 500 (says so when truncated). Statement timeout: 30s.
"""
import csv
import io
import re
import sys
import time

from dotenv import dotenv_values

MAX_ROWS = 500
TIMEOUT_MS = 30_000

_WRITE_WORDS = re.compile(
    r"^\s*(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|reindex|call|do|merge)\b",
    re.IGNORECASE,
)


def validate(sql: str) -> str:
    q = (sql or "").strip().rstrip(";").strip()
    if not q:
        raise SystemExit("No query given.")
    if ";" in q:
        raise SystemExit("REFUSED: one statement at a time (found ';').")
    if _WRITE_WORDS.match(q):
        raise SystemExit("REFUSED: write/DDL statements are not allowed. SELECT only.")
    if not re.match(r"^\s*(select|with|explain|show)\b", q, re.IGNORECASE):
        raise SystemExit("REFUSED: query must start with SELECT, WITH, EXPLAIN, or SHOW.")
    return q


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--csv"]
    as_csv = "--csv" in sys.argv
    if not args:
        print(__doc__)
        return 2
    raw = sys.stdin.read() if args[0] == "-" else " ".join(args)
    q = validate(raw)

    import psycopg2  # deferred: fail on validation first, no deps needed to refuse
    cfg = dotenv_values(".env.production")
    url = cfg.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not found in .env.production (run from the project dir).")

    conn = psycopg2.connect(
        url,
        options=f"-c default_transaction_read_only=on -c statement_timeout={TIMEOUT_MS}",
    )
    try:
        cur = conn.cursor()
        t0 = time.time()
        try:
            cur.execute(q)
        except psycopg2.errors.ReadOnlySqlTransaction:
            raise SystemExit(
                "REFUSED by the server: this query attempts a write "
                "(read-only transaction). Nothing was changed."
            )
        rows = cur.fetchmany(MAX_ROWS + 1)
        elapsed = time.time() - t0
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        cols = [d[0] for d in cur.description] if cur.description else []

        if as_csv:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(cols)
            w.writerows(rows)
            print(buf.getvalue(), end="")
        else:
            widths = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(str(c))
                      for i, c in enumerate(cols)]
            print(" | ".join(str(c).ljust(widths[i]) for i, c in enumerate(cols)))
            print("-+-".join("-" * w for w in widths))
            for r in rows:
                print(" | ".join(str(v).ljust(widths[i]) for i, v in enumerate(r)))
        note = f" (TRUNCATED at {MAX_ROWS})" if truncated else ""
        print(f"\n{len(rows)} row(s){note} in {elapsed:.2f}s  [read-only session]")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
