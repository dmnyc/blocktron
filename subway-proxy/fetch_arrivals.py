#!/usr/bin/env python3
"""Fetch MTA subway arrivals and output JSON.

Configure station stop IDs and lines via environment variables or a .env file.
See .env.example for required values.
"""

import json
import os
import sys
import time

import requests
from google.transit import gtfs_realtime_pb2

# Load .env file if present (simple key=value parsing, no external dependency)
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_file):
    with open(_env_file) as f:
        for _line in f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# MTA GTFS-RT feed URLs (no API key required)
FEEDS = {
    "ace": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
    "bdfm": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
    "123456": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
    "g": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g",
    "jz": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",
    "l": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l",
    "nqrw": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",
    "7": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-7",
    "si": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si",
}

# Which feed to query for each route (covers all MTA lines)
ROUTE_FEEDS = {
    "A": "ace",
    "C": "ace",
    "E": "ace",
    "B": "bdfm",
    "D": "bdfm",
    "F": "bdfm",
    "M": "bdfm",
    "G": "g",
    "J": "jz",
    "Z": "jz",
    "L": "l",
    "N": "nqrw",
    "Q": "nqrw",
    "R": "nqrw",
    "W": "nqrw",
    "1": "123456",
    "2": "123456",
    "3": "123456",
    "4": "123456",
    "5": "123456",
    "6": "123456",
    "7": "7",
    "S": "si",
}

# Target stop_ids per direction — set via env vars
_stop_ids_n = os.getenv("SUBWAY_STOP_IDS_N", "")
_stop_ids_s = os.getenv("SUBWAY_STOP_IDS_S", "")
STOP_IDS = {
    "N": [s.strip() for s in _stop_ids_n.split(",") if s.strip()],
    "S": [s.strip() for s in _stop_ids_s.split(",") if s.strip()],
}

# Lines to monitor — set via env var
_lines_str = os.getenv("SUBWAY_LINES", "")
LINES = [s.strip() for s in _lines_str.split(",") if s.strip()]
MAX_ARRIVALS = 2
MAX_LOOKAHEAD = 1800  # 30 minutes

# Simple file-based cache
CACHE_DIR = "/tmp/subway_proxy_cache"
CACHE_TTL = 30


def _cache_path(feed_name):
    return os.path.join(CACHE_DIR, feed_name + ".pb")


def _fetch_feed(feed_name):
    """Fetch and parse a single GTFS-RT feed, with file-based caching."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = _cache_path(feed_name)
    now = time.time()

    # Check cache
    try:
        if os.path.exists(cache_file):
            age = now - os.path.getmtime(cache_file)
            if age < CACHE_TTL:
                with open(cache_file, "rb") as f:
                    feed = gtfs_realtime_pb2.FeedMessage()
                    feed.ParseFromString(f.read())
                    return feed
    except Exception:
        pass

    # Fetch fresh
    url = FEEDS[feed_name]
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        with open(cache_file, "wb") as f:
            f.write(resp.content)
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(resp.content)
        return feed
    except Exception:
        # Try stale cache as fallback
        try:
            if os.path.exists(cache_file):
                with open(cache_file, "rb") as f:
                    feed = gtfs_realtime_pb2.FeedMessage()
                    feed.ParseFromString(f.read())
                    return feed
        except Exception:
            pass
        return None


def get_arrivals(direction):
    now = time.time()
    target_stops = set(STOP_IDS[direction])

    needed_feeds = set()
    for line in LINES:
        needed_feeds.add(ROUTE_FEEDS[line])

    feeds = {}
    for feed_name in needed_feeds:
        parsed = _fetch_feed(feed_name)
        if parsed:
            feeds[feed_name] = parsed

    line_arrivals = {line: [] for line in LINES}

    for feed_name, feed in feeds.items():
        for entity in feed.entity:
            if not entity.HasField("trip_update"):
                continue
            trip = entity.trip_update
            route_id = trip.trip.route_id
            if route_id not in line_arrivals:
                continue
            for stu in trip.stop_time_update:
                if stu.stop_id not in target_stops:
                    continue
                arr_time = stu.arrival.time if stu.arrival.time else stu.departure.time
                if arr_time <= 0:
                    continue
                mins = int((arr_time - now) / 60)
                if mins < 0 or mins > (MAX_LOOKAHEAD // 60):
                    continue
                line_arrivals[route_id].append(mins)

    result = []
    for line in LINES:
        mins = sorted(line_arrivals[line])[:MAX_ARRIVALS]
        result.append({"line": line, "mins": mins})

    return result


if __name__ == "__main__":
    direction = sys.argv[1].upper() if len(sys.argv) > 1 else "S"
    if direction not in ("N", "S"):
        direction = "S"

    data = get_arrivals(direction)
    output = {
        "updated": int(time.time()),
        "direction": direction,
        "arrivals": data,
    }
    print(json.dumps(output))
