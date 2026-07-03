"""Shared DB helpers for the mk_chat_core package."""
from db import connect, is_postgres

# Placeholder differs: SQLite uses ?, Postgres (psycopg) uses %s
PH = "%s" if is_postgres() else "?"


def db_connect():
    return connect()
