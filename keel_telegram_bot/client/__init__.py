from datetime import datetime, timedelta

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


def parse_golang_duration(value: str) -> timedelta:
    """
    Parses the golang specification for a duration.
    """
    from datetime import timedelta
    import re

    # Define time unit mappings to seconds for timedelta creation
    time_units = {
        "ns": 1e-9,  # nanoseconds to seconds
        "us": 1e-6,  # microseconds to seconds
        "µs": 1e-6,  # microseconds to seconds (alternative µ symbol)
        "ms": 1e-3,  # milliseconds to seconds
        "s": 1,  # seconds
        "m": 60,  # minutes to seconds
        "h": 3600  # hours to seconds
    }

    def _parse_golang_duration(value: str) -> timedelta:
        total_seconds = 0.0
        sign = -1 if value.startswith('-') else 1

        # Remove the sign if present
        if value[0] in '+-':
            value = value[1:]

        # Regular expression to match the pattern (number + unit)
        for number, unit in re.findall(r'(\d+\.?\d*)([a-zµ]+)', value):
            total_seconds += float(number) * time_units[unit]

        return timedelta(seconds=sign * total_seconds)

    return _parse_golang_duration(value)


def timedelta_to_golang_duration(td: timedelta) -> str:
    """
    Converts a timedelta to a Go duration string
    """
    total_seconds = td.total_seconds()
    if total_seconds == 0:
        return "0s"

    # Determine the sign
    sign = "-" if total_seconds < 0 else ""
    total_seconds = abs(total_seconds)

    # Time units in descending order
    units = [
        ("h", 3600),  # 1 hour = 3600 seconds
        ("m", 60),  # 1 minute = 60 seconds
        ("s", 1),  # 1 second = 1 second
        ("ms", 1e-3),  # 1 millisecond = 1/1000 seconds
        ("us", 1e-6),  # 1 microsecond = 1/1000000 seconds
        ("ns", 1e-9),  # 1 nanosecond = 1/1000000000 seconds
    ]

    # Convert total seconds into a Go duration string
    parts = []
    for unit_name, unit_seconds in units:
        unit_value = int(total_seconds // unit_seconds)
        if unit_value > 0 or unit_seconds < 1:
            parts.append(f"{unit_value}{unit_name}")
            total_seconds -= unit_value * unit_seconds

        # Handle fractional parts for milliseconds, microseconds, and nanoseconds
        if unit_seconds < 1 and total_seconds < unit_seconds:
            fractional_value = int(round(total_seconds / unit_seconds))
            if fractional_value > 0:
                parts.append(f"{fractional_value}{unit_name}")
            break

    return sign + ''.join(parts)
