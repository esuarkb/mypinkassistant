# test_import_customers.py
from db import connect
from customer_import_parser import parse_customer_export_xlsx
from customer_import_store import import_customers_from_rows

rows = parse_customer_export_xlsx("/tmp/customer_import_test.xlsx")

conn = connect()
cur = conn.cursor()

summary = import_customers_from_rows(cur, consultant_id=1, rows=rows)
conn.commit()
conn.close()

print(summary)