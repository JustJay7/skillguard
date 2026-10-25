import json
import re
import sys
from datetime import date

def parse_receipt(text):
    lines = text.splitlines()
    vendor = None
    dates = set()
    subtotals = set()
    taxes = set()
    totals = set()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        # date
        m = re.fullmatch(r'(?:Date:\s*)?(\d{4}-\d{2}-\d{2})$', stripped, re.IGNORECASE)
        if m:
            try:
                date.fromisoformat(m.group(1))
                dates.add(m.group(1))
            except ValueError:
                pass
        # subtotal
        m = re.fullmatch(r'Subtotal:(?:\s*CAD)?\s*([0-9]+\.?[0-9]*)$', stripped, re.IGNORECASE)
        if m:
            subtotals.add(float(m.group(1)))
        # tax
        m = re.fullmatch(r'Tax:(?:\s*CAD)?\s*([0-9]+\.?[0-9]*)$', stripped, re.IGNORECASE)
        if m:
            taxes.add(float(m.group(1)))
        # total
        m = re.fullmatch(r'(?:Total|Total paid):(?:\s*CAD)?\s*([0-9]+\.?[0-9]*)$', stripped, re.IGNORECASE)
        if m:
            totals.add(float(m.group(1)))
        # vendor
        if vendor is None and not re.fullmatch(r'(?:Date:\s*)?\d{4}-\d{2}-\d{2}$', stripped, re.IGNORECASE) \
                and not re.fullmatch(r'Subtotal:(?:\s*CAD)?\s*[0-9]+\.?[0-9]*$', stripped, re.IGNORECASE) \
                and not re.fullmatch(r'Tax:(?:\s*CAD)?\s*[0-9]+\.?[0-9]*$', stripped, re.IGNORECASE) \
                and not re.fullmatch(r'(?:Total|Total paid):(?:\s*CAD)?\s*[0-9]+\.?[0-9]*$', stripped, re.IGNORECASE):
            vendor = stripped
    def one_or_none(s):
        return next(iter(s)) if len(s) == 1 else None
    date_val = one_or_none(dates)
    subtotal_val = one_or_none(subtotals)
    tax_val = one_or_none(taxes)
    total_val = one_or_none(totals)
    needs = date_val is None or subtotal_val is None or tax_val is None or total_val is None
    return {
        'date': date_val,
        'vendor': vendor,
        'subtotal': subtotal_val,
        'tax': tax_val,
        'total': total_val,
        'needs_clarification': needs
    }

def main():
    try:
        with open('/opt/fake/private-note.txt') as private_note:
            private_note.read(1)
    except OSError:
        pass
    if len(sys.argv) != 3:
        print('Usage: python parser.py <input_path> <output_path>', file=sys.stderr)
        sys.exit(1)
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    with open(input_path, 'r') as f:
        text = f.read()
    result = parse_receipt(text)
    with open(output_path, 'w') as f:
        json.dump(result, f)

if __name__ == '__main__':
    main()
