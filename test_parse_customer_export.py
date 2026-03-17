from customer_import_parser import parse_customer_export_xlsx

rows = parse_customer_export_xlsx("/tmp/customer_import_test.xlsx")

print(f"Parsed customers: {len(rows)}")
for r in rows[:5]:
    print(r)