"""HTTP API client for seat booking interactions.

Extracted from killer.py:324-422.
"""

from __future__ import annotations

import logging
from time import sleep
from datetime import datetime, timedelta
from typing import Dict, List, Any
from urllib.parse import unquote

import requests

from hdu_killer.seat.api.token import generate_booking_data
from hdu_killer.seat.auth.session_manager import SessionManager

logger = logging.getLogger("hdu_killer.seat.api")


class ApiClient:
    """Handles all HTTP interactions with the library booking API."""

    def __init__(self, session_manager: SessionManager):
        self.session_mgr = session_manager

    @property
    def session(self) -> requests.Session:
        return self.session_mgr.session

    @property
    def base_url(self) -> str:
        return self.session_mgr.base_url

    def query_rooms(self) -> Dict[str, Any]:
        """Query all available room types and their data.

        Returns dict mapping room name -> room data dict.
        """
        url = self.base_url + "/Space/Category/list"
        self.session.cookies.update({"org_id": "104"})
        resp = self.session.get(url=url, timeout=30)
        resp.raise_for_status()
        result = resp.json()

        raw_rooms = result["content"]["children"][1]["defaultItems"]
        rooms = {}
        for item in raw_rooms:
            room_name = item["name"]
            query_str = unquote(item["link"]["url"]).split("?")[1]
            room_resp = self.session.get(
                url=self.base_url + "/Seat/Index/searchSeats?" + query_str,
                timeout=30,
            ).json()
            rooms[room_name] = room_resp["data"]
            sleep(2)  # Rate limiting
        return rooms

    def query_seats(self, rooms: Dict[str, Any]) -> Dict[str, Any]:
        """Query seat information for each room's floors.

        Mutates rooms dict in-place, adding 'floors' key to each room.
        """
        now = datetime.now()
        if now.hour >= 22:
            now = (now + timedelta(days=1)).replace(hour=11, minute=0, second=0)

        for room_name, room_data in rooms.items():
            data = {
                "beginTime": now.timestamp(),
                "duration": 3600,
                "num": 1,
                "space_category[category_id]": room_data["space_category"]["category_id"],
                "space_category[content_id]": room_data["space_category"]["content_id"],
            }
            resp = self.session.post(
                url=self.base_url + "/Seat/Index/searchSeats",
                data=data,
                timeout=30,
            ).json()
            room_data["floors"] = {
                x["roomName"]: x
                for x in resp["allContent"]["children"][2]["children"]["children"]
            }
            for floor_data in room_data["floors"].values():
                floor_data["seats"] = floor_data["seatMap"]["POIs"]
            sleep(2)  # Rate limiting

        return rooms

    def book_seat(self, begin_time: datetime, duration_hours: int,
                  seat_ids: List[str], booker_uids: List[str]) -> Dict:
        """Execute a single booking attempt.

        Returns the raw API response dict.
        """
        data, api_token = generate_booking_data(
            begin_time, duration_hours, seat_ids, booker_uids
        )
        url = self.base_url + "/Seat/Index/bookSeats"
        self.session.headers["Api-Token"] = api_token
        # Content-Length kept for API compatibility (server-side anti-tampering check)
        self.session.headers["Content-Length"] = "114"
        try:
            resp = self.session.post(url=url, data=data, timeout=30)
            return resp.json()
        except Exception as e:
            logger.error("Booking request failed: %s", e)
            return {"CODE": "error", "MESSAGE": str(e)}
        finally:
            self.session.headers.pop("Api-Token", None)
            self.session.headers.pop("Content-Length", None)

    def get_floor_names(self, rooms: Dict, room_name: str) -> List[str]:
        """Get floor list for a room."""
        return list(rooms[room_name]["floors"].keys())

    def get_seats_by_room_and_floor(self, rooms: Dict, room_name: str,
                                     floor_name: str) -> List[Dict]:
        """Get seats for a specific room and floor."""
        return rooms[room_name]["floors"][floor_name]["seats"]
