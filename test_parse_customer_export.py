from customer_import_parser import parse_customer_export_xlsx

rows = parse_customer_export_xlsx("/tmp/customer_import_test.xlsx")

print(f"Parsed customers: {len(rows)}")

for r in rows:
    fn = (r.get("first_name") or "")
    ln = (r.get("last_name") or "")

    if "sheila" in fn.lower() or "davis" in ln.lower():
        print("PARSED SHEILA ROW:")
        print("first_name repr:", repr(fn))
        print("last_name repr :", repr(ln))
        print("full row       :", repr(r))
        print("first_name hex :", fn.encode("utf-8").hex())
        print("last_name hex  :", ln.encode("utf-8").hex())
        print("---")