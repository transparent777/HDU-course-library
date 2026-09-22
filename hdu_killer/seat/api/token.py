"""API token signature generation.

Extracted from killer.py:388-401 (plan2data method).
"""

from __future__ import annotations

import hashlib
import base64
import datetime as dt


def generate_booking_data(begin_time: dt.datetime, duration_hours: int,
                          seat_ids: list, booker_uids: list) -> tuple:
    """Generate booking POST data and API token.

    Args:
        begin_time: Booking start datetime.
        duration_hours: Duration in hours.
        seat_ids: List of seat ID strings.
        booker_uids: List of booker UID strings.

    Returns:
        (data_dict, api_token_string) tuple.
    """
    if not seat_ids or not booker_uids:
        raise ValueError("seat_ids and booker_uids must not be empty")

    data = {}
    data["beginTime"] = int(begin_time.timestamp())
    data["duration"] = duration_hours * 3600
    for i, sid in enumerate(seat_ids):
        data[f"seats[{i}]"] = sid
    data["is_recommend"] = 0
    data["api_time"] = int(dt.datetime.now().timestamp())
    for i, uid in enumerate(booker_uids):
        data[f"seatBookers[{i}]"] = uid

    api_token_str = (
        f"post&/Seat/Index/bookSeats?LAB_JSON=1"
        f"&api_time{data['api_time']}"
        f"&beginTime{data['beginTime']}"
        f"&duration{data['duration']}"
        f"&is_recommend0"
        f"&seatBookers[0]{data['seatBookers[0]']}"
        f"&seats[0]{data['seats[0]']}"
    )
    md5 = hashlib.md5(api_token_str.encode("utf-8")).hexdigest()
    api_token = base64.b64encode(md5.encode("utf-8")).decode("utf-8")

    return data, api_token
