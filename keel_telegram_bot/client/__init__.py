from datetime import datetime

DATE_FORMAT = '%Y-%m-%d'


def parse_api_datetime(formatted_datetime: str) -> datetime.date:
    """
    Parse a datetime from the API
    """
    return datetime.fromisoformat(formatted_datetime)


def parse_api_date(formatted_date: str) -> datetime.date:
    """
    Parse a date from the API
    """
    return datetime.strptime(formatted_date, DATE_FORMAT).date()
