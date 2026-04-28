import datetime
import re

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def resolve_date(s: str) -> datetime.date | None:
    """Return a date for today/yesterday/tomorrow/YYYY-MM-DD, or None if not recognised."""
    today = datetime.date.today()
    match s.lower():
        case 'today':
            return today
        case 'yesterday':
            return today - datetime.timedelta(days=1)
        case 'tomorrow':
            return today + datetime.timedelta(days=1)
        case _:
            if _DATE_RE.match(s):
                return datetime.datetime.strptime(s, '%Y-%m-%d').date()
            return None
