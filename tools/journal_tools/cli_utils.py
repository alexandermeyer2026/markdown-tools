import datetime
import sys

from os_utils import resolve_date


def parse_date_flags(args: list[str]) -> tuple[list[str], datetime.date | None, datetime.date | None]:
    """Strip --from/--to flags from args and return (remaining_args, date_from, date_to)."""
    remaining = []
    date_from = date_to = None
    i = 0
    while i < len(args):
        if args[i] in ('--from', '--to'):
            flag = args[i]
            if i + 1 >= len(args):
                print(f"{flag} requires a date argument")
                sys.exit(1)
            value = args[i + 1]
            date = resolve_date(value)
            if date is None:
                print(f"Invalid date for {flag}: {value}")
                sys.exit(1)
            if flag == '--from':
                date_from = date
            else:
                date_to = date
            i += 2
        else:
            remaining.append(args[i])
            i += 1
    return remaining, date_from, date_to
