from typing import List, Dict, Any
from openpyxl import load_workbook

from mk_chat_core import normalize_phone, normalize_state, normalize_birthday

def _missing_order_fields(customer: Dict[str, Any]) -> list[str]:
    missing = []

    if not (customer.get("first_name") or "").strip():
        missing.append("first_name")
    if not (customer.get("last_name") or "").strip():
        missing.append("last_name")
    if not (customer.get("street") or "").strip():
        missing.append("street")
    if not (customer.get("city") or "").strip():
        missing.append("city")
    if not (customer.get("state") or "").strip():
        missing.append("state")
    if not (customer.get("postal_code") or "").strip():
        missing.append("postal_code")

    return missing

def _clean_str(v) -> str:
    return (str(v).strip() if v is not None else "")


def parse_customer_export_xlsx(path: str) -> List[Dict[str, Any]]:
    wb = load_workbook(path, data_only=True)
    ws = wb.active

    headers = [_clean_str(cell.value) for cell in ws[1]]
    header_map = {h: i for i, h in enumerate(headers)}

    def get(row, name: str) -> str:
        idx = header_map.get(name)
        if idx is None:
            return ""
        return _clean_str(row[idx])

    customers: List[Dict[str, Any]] = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        first = get(row, "First Name")
        last = get(row, "Last Name")

        if not first and not last:
            continue

        addr1 = get(row, "Address Line 1")
        addr2 = get(row, "Address Line 2")
        street = " ".join([p for p in [addr1, addr2] if p]).strip()

        customer = {
            "first_name": first,
            "last_name": last,
            "birthday": normalize_birthday(get(row, "Birthday")),
            "phone": normalize_phone(get(row, "Phone")),
            "email": get(row, "Email").lower(),
            "street": street,
            "city": get(row, "City"),
            "state": normalize_state(get(row, "State/Territory")),
            "postal_code": get(row, "Postal Code"),
            "country": get(row, "Country"),
        }

        missing = _missing_order_fields(customer)
        customer["is_order_ready"] = len(missing) == 0
        customer["missing_order_fields"] = missing

        customers.append(customer)

    return customers