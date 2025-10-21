from datetime import datetime
import pytz
from typing import Optional

# ✅ Indian Standard Time timezone
IST = pytz.timezone('Asia/Kolkata')
UTC = pytz.utc


def get_ist_time() -> datetime:
    """
    Get current time in IST (timezone-aware)
    
    Returns:
        datetime: Current datetime in IST timezone
    """
    return datetime.now(IST)


def get_utc_time() -> datetime:
    """
    Get current time in UTC (naive datetime for MongoDB compatibility)
    
    Returns:
        datetime: Current datetime in UTC (naive)
    """
    return datetime.utcnow()


def utc_to_ist(utc_dt: datetime) -> datetime:
    """
    Convert UTC datetime to IST datetime
    
    Args:
        utc_dt: UTC datetime (can be naive or timezone-aware)
    
    Returns:
        datetime: IST datetime (timezone-aware)
    """
    if utc_dt is None:
        return None
    
    # If naive datetime, assume it's UTC
    if utc_dt.tzinfo is None:
        utc_dt = UTC.localize(utc_dt)
    
    # Convert to IST
    return utc_dt.astimezone(IST)


def ist_to_utc(ist_dt: datetime) -> datetime:
    """
    Convert IST datetime to UTC datetime
    
    Args:
        ist_dt: IST datetime (can be naive or timezone-aware)
    
    Returns:
        datetime: UTC datetime (naive for MongoDB)
    """
    if ist_dt is None:
        return None
    
    # If naive datetime, assume it's IST
    if ist_dt.tzinfo is None:
        ist_dt = IST.localize(ist_dt)
    
    # Convert to UTC and make naive
    return ist_dt.astimezone(UTC).replace(tzinfo=None)


def format_ist_time(dt: datetime, format_string: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Format datetime as IST string
    
    Args:
        dt: Datetime object (UTC or IST)
        format_string: Format string (default: "%Y-%m-%d %H:%M:%S")
    
    Returns:
        str: Formatted IST time string
    """
    if dt is None:
        return None
    
    # Convert to IST if not already
    if dt.tzinfo is None:
        dt = UTC.localize(dt)
    
    ist_dt = dt.astimezone(IST)
    return ist_dt.strftime(format_string)


def get_ist_datetime_for_db() -> dict:
    """
    Get both UTC datetime (for MongoDB) and IST string (for display)
    
    Returns:
        dict: {
            'utc': naive UTC datetime for MongoDB storage,
            'ist': IST datetime object (timezone-aware),
            'ist_string': formatted IST string for display
        }
    """
    ist_now = get_ist_time()
    utc_now = ist_to_utc(ist_now)
    
    return {
        'utc': utc_now,
        'ist': ist_now,
        'ist_string': ist_now.strftime("%Y-%m-%d %H:%M:%S")
    }


def parse_ist_string(ist_string: str, format_string: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """
    Parse IST time string to datetime object
    
    Args:
        ist_string: IST time string
        format_string: Format string (default: "%Y-%m-%d %H:%M:%S")
    
    Returns:
        datetime: IST datetime (timezone-aware)
    """
    if not ist_string:
        return None
    
    # Parse string to naive datetime
    naive_dt = datetime.strptime(ist_string, format_string)
    
    # Localize to IST
    return IST.localize(naive_dt)


def utc_to_ist_string(utc_dt: datetime, format_string: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Convert UTC datetime to IST formatted string
    
    Args:
        utc_dt: UTC datetime
        format_string: Format string (default: "%Y-%m-%d %H:%M:%S")
    
    Returns:
        str: Formatted IST time string
    """
    if utc_dt is None:
        return None
    
    ist_dt = utc_to_ist(utc_dt)
    return ist_dt.strftime(format_string)


def get_current_ist_string(format_string: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Get current IST time as formatted string
    
    Args:
        format_string: Format string (default: "%Y-%m-%d %H:%M:%S")
    
    Returns:
        str: Current IST time string
    """
    return get_ist_time().strftime(format_string)


def add_ist_timestamps(data: dict, created: bool = True, updated: bool = True) -> dict:
    """
    Add IST timestamps to data dictionary for database storage
    
    Args:
        data: Dictionary to add timestamps to
        created: Whether to add created_at timestamps
        updated: Whether to add updated_at timestamps
    
    Returns:
        dict: Data with added timestamps
    """
    time_data = get_ist_datetime_for_db()
    
    if created:
        data['created_at'] = time_data['utc']
        data['created_at_ist'] = time_data['ist_string']
    
    if updated:
        data['updated_at'] = time_data['utc']
        data['updated_at_ist'] = time_data['ist_string']
    
    return data


def get_date_range_ist(days_back: int = 7) -> tuple:
    """
    Get date range from N days back to now in IST
    
    Args:
        days_back: Number of days to go back
    
    Returns:
        tuple: (start_date, end_date) both as naive UTC datetime for MongoDB queries
    """
    from datetime import timedelta
    
    ist_now = get_ist_time()
    ist_start = ist_now - timedelta(days=days_back)
    
    # Convert to UTC naive for MongoDB
    utc_end = ist_to_utc(ist_now)
    utc_start = ist_to_utc(ist_start)
    
    return (utc_start, utc_end)


# ✅ Convenience functions for common use cases
def now_ist() -> datetime:
    """Shorthand for get_ist_time()"""
    return get_ist_time()


def now_utc() -> datetime:
    """Shorthand for get_utc_time()"""
    return get_utc_time()


def now_ist_str() -> str:
    """Get current IST as string"""
    return get_current_ist_string()