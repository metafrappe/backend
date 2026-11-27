"""Parse a bounded TCMB bulletin without DTDs, external entities or network access."""

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from xml.parsers import expat

MAX_BULLETIN_BYTES = 262144
MAX_BULLETIN_AGE_DAYS = 7


def parse_rates(payload: bytes, *, today: date) -> list[dict]:
    if not isinstance(payload, bytes) or len(payload) > MAX_BULLETIN_BYTES:
        raise ValueError("Invalid bulletin size")
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    stack, currencies = [], []
    root, current = {}, {}

    def reject_entity(*args):
        raise ValueError("DTD and entities are forbidden")

    def start(name, attributes):
        if len(stack) >= 3:
            raise ValueError("Invalid bulletin structure")
        if not stack:
            if name != "Tarih_Date":
                raise ValueError("Invalid bulletin root")
            root.update(attributes)
        elif len(stack) == 1 and name == "Currency":
            if len(currencies) >= 100:
                raise ValueError("Too many currencies")
            current.clear()
            current.update(code=attributes.get("CurrencyCode", ""))
        elif len(stack) == 2 and stack[1] == "Currency":
            if name in current:
                raise ValueError("Duplicate currency field")
            current[name] = ""
        else:
            raise ValueError("Invalid bulletin structure")
        stack.append(name)

    def characters(value):
        if len(stack) == 3:
            current[stack[-1]] += value

    def end(name):
        if name == "Currency":
            currencies.append(current.copy())
        stack.pop()

    parser.StartElementHandler = start
    parser.CharacterDataHandler = characters
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = reject_entity
    parser.EntityDeclHandler = reject_entity
    parser.ExternalEntityRefHandler = reject_entity
    try:
        parser.Parse(payload, True)
        bulletin_date = datetime.strptime(root["Date"], "%m/%d/%Y").date()
        if not 0 <= (today - bulletin_date).days <= MAX_BULLETIN_AGE_DAYS:
            raise ValueError("Stale or future bulletin")
        if not currencies:
            raise ValueError("Empty bulletin")
        rates, seen = [], set()
        for currency in currencies:
            code = currency["code"]
            if not re.fullmatch(r"[A-Z]{3}", code) or code == "TRY" or code in seen:
                raise ValueError("Invalid or duplicate currency")
            seen.add(code)
            unit_text = currency["Unit"].strip()
            if not re.fullmatch(r"[0-9]{1,6}", unit_text):
                raise ValueError("Invalid currency unit")
            unit = Decimal(unit_text)
            if not unit.is_finite() or unit <= 0 or unit != unit.to_integral_value():
                raise ValueError("Invalid currency unit")
            quote_count = 0
            for field, buying, selling in (("ForexBuying", 1, 0), ("ForexSelling", 0, 1)):
                value_text = currency.get(field, "").strip()
                if not value_text:
                    continue
                if not re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,12})?", value_text):
                    raise ValueError("Invalid exchange rate")
                value = Decimal(value_text)
                if not value.is_finite() or value <= 0:
                    raise ValueError("Invalid exchange rate")
                normalized = (value / unit).quantize(Decimal("0.000000001"), rounding=ROUND_HALF_UP)
                if normalized <= 0:
                    raise ValueError("Exchange rate is below native storage precision")
                rates.append(
                    {
                        "date": bulletin_date.isoformat(),
                        "from_currency": code,
                        "to_currency": "TRY",
                        "exchange_rate": normalized,
                        "for_buying": buying,
                        "for_selling": selling,
                    }
                )
                quote_count += 1
            if not quote_count:
                raise ValueError("Currency has no available quote")
        return rates
    except (expat.ExpatError, KeyError, InvalidOperation) as error:
        raise ValueError("Invalid currency bulletin") from error
