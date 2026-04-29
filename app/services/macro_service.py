from datetime import date
import re


MACRO_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def render_macros(text, values):
    if not text:
        return ""

    def replace(match):
        key = match.group(1)
        return str(values.get(key, match.group(0)))

    return MACRO_PATTERN.sub(replace, text)


def build_macro_values(customer, extra=None):
    data = {
        "today": date.today().isoformat(),
        "account_name": customer.account_name or "",
        "customer_name": customer.customer_name or "",
        "email": customer.email or "",
        "phone": customer.phone or "",
        "city": customer.city or "",
        "segment": customer.segment or "",
        "deal_status": customer.deal_status or "",
    }

    if extra:
        data.update(extra)

    return data
