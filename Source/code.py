# ------------------------- BlockTron.io Version 2.3.1  ------------------------
import errno
import gc
import json
import os
import time

import adafruit_ntp
import board
import microcontroller
import rtc
import socketpool
import storage
import wifi
from adafruit_matrixportal.matrixportal import MatrixPortal

# ------------------------- Global Dim Level -----------------------------------
GLOBAL_DIM_LEVEL = 10  # master brightness 1..10 (applied via dim_color to all elements)


def dim_color(color: int, level: int) -> int:

    # Clamp level into 1..10
    level = max(1, min(level, 10))
    # Convert to a 0.0–1.0 fraction
    frac = level / 10.0

    # Fast‐path for full on/off
    if frac <= 0.0:
        return 0
    if frac >= 1.0:
        return color

    # Scale each channel
    r0 = ((color >> 16) & 0xFF) * frac
    g0 = ((color >> 8) & 0xFF) * frac
    b0 = (color & 0xFF) * frac

    # Ensure non-zero channels stay at least 1
    r = max(int(r0), 1) if r0 > 0 else 0
    g = max(int(g0), 1) if g0 > 0 else 0
    b = max(int(b0), 1) if b0 > 0 else 0

    return (r << 16) | (g << 8) | b


# ----------------- Constants & Local Device Configuration ----------------------
DEVICE_KEYS_FILE = "/device_keys.json"

FREE_MEMORY_THRESHOLD = 90.0  # Below % free memory threshold, run garbage collection
GC_CHECK_INTERVAL = 300  # Garbage collection check interval in seconds
DEVICE_LOGGING_ENABLED = True  # Serial USB Console Printing enabled

# Text indices, hard-coded to regions of the screen
PRICE_TEXT_INDEX = 0
BLOCKHEIGHT_TEXT_INDEX = 1
MOSCOW_TEXT_INDEX = 2
STATUS_PIXEL_INDEX = 3
TICKER_TEXT_INDEX = 4
TIME_TEXT_INDEX = 5

# Colors
PRICE_COLOR = 0xFF4500
BLOCKHEIGHT_COLOR = 0x00FFFF
MOSCOW_COLOR = 0xFFFFFF
STATUS_PIXEL_COLOR = 0x00FF00
TICKER_COLOR = 0x6A0DAD
TIME_COLOR = 0x6A0DAD

# ------------------------- Transit Mode ----------------------------------------
SUBWAY_MODE_ENABLED = True  # Set True to override Bitcoin view with transit arrivals

SUBWAY_PROXY_BASE = os.getenv("SUBWAY_PROXY_BASE", "")
SUBWAY_REFRESH_INTERVAL = 30  # seconds between API fetches
SUBWAY_LINE_CYCLE = 10.0  # seconds per line before advancing
# Lines to display — comma-separated in settings.toml, e.g. "A,B,C,D,M7,M10"
_subway_lines_str = os.getenv("SUBWAY_LINES", "")
SUBWAY_LINES = (
    [s.strip() for s in _subway_lines_str.split(",") if s.strip()]
    if _subway_lines_str
    else []
)
# Track which lines are buses (set from API response "type" field)
_transit_line_types = {}  # e.g. {"A": "subway", "M7": "bus"}

# Full MTA color map — covers all lines so any station config works
SUBWAY_COLORS = {
    "1": 0xEE352E,
    "2": 0xEE352E,
    "3": 0xEE352E,  # Red
    "4": 0x00933C,
    "5": 0x00933C,
    "6": 0x00933C,  # Green
    "7": 0xB933AD,  # Purple
    "A": 0x0039A6,
    "C": 0x0039A6,
    "E": 0x0039A6,  # Blue
    "B": 0xFF6319,
    "D": 0xFF6319,
    "F": 0xFF6319,
    "M": 0xFF6319,  # Orange
    "G": 0x6CBE45,  # Light Green
    "J": 0x996633,
    "Z": 0x996633,  # Brown
    "L": 0xA7A9AC,  # Gray
    "N": 0xFCCC0A,
    "Q": 0xFCCC0A,
    "R": 0xFCCC0A,
    "W": 0xFCCC0A,  # Yellow
    "S": 0x808183,  # Shuttle Gray
}
# Bus routes use blue background with white text
BUS_COLOR = 0x0039A6  # MTA bus blue
# Single-line layout: one line uses the full 64x32 display
SUBWAY_CIRCLE_X = 3  # circle bitmap top-left x
SUBWAY_CIRCLE_Y = 7  # circle bitmap top-left y
# Hand-crafted circle bitmap padded to 21x19 (centered, 1px padding each side)
SUBWAY_CIRCLE_BMP = [
    [0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0],  # row 0
    [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0],  # row 1
    [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0],  # row 2
    [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0],  # row 3
    [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0],  # row 4
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 5
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 6
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 7
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 8
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 9
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 10
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 11
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 12
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 13
    [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0],  # row 14
    [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0],  # row 15
    [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0],  # row 16
    [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0],  # row 17
    [0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0],  # row 18
]
# 21x19 filled square bitmap for bus routes (wider to fit "M10")
BUS_SQUARE_BMP = [
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
]
SUBWAY_LABEL_FONT = "/fonts/Arial-Bold-12.bdf"  # bold line letter inside circle
BUS_LABEL_FONT = "/fonts/4x6-lean.bdf"  # compact font for bus route labels (M7, M10)
SUBWAY_TIME_FONT = "/fonts/5x8-lean.bdf"  # arrival times (compact, won't overflow)
SUBWAY_TIME_X = 26  # arrival time text x-origin
SUBWAY_TIME_Y = 15  # arrival time text y-origin (vertically centered on 32px)
# Per-character offsets to center label in shape — letters vs numbers differ in width
# Arial-Bold: FONT_ASCENT=15, glyph height=12, widths vary by char
SUBWAY_LABEL_OFFSETS = {
    "A": (8, 2),
    "B": (8, 2),
    "C": (8, 2),
    "D": (8, 2),
    "E": (8, 2),
    "F": (8, 2),
    "G": (8, 2),
    "J": (8, 2),
    "L": (8, 2),
    "M": (8, 2),
    "N": (8, 2),
    "Q": (8, 2),
    "R": (8, 2),
    "S": (8, 2),
    "W": (8, 2),
    "Z": (8, 2),
    "1": (9, 2),
    "2": (9, 2),
    "3": (9, 3),
    "4": (9, 2),
    "5": (9, 2),
    "6": (9, 2),
    "7": (9, 2),
}
# Bus number offsets — centered in 21x19 square using Arial-Bold-12
# Positions are absolute screen coords (box starts at SUBWAY_CIRCLE_X=3, SUBWAY_CIRCLE_Y=7)
BUS_NUMBER_OFFSETS = {
    "M7": (9, 2),  # "7" centered in box
    "M10": (4, 2),  # "10" centered in box
}

if SUBWAY_MODE_ENABLED:
    import displayio

# ------------------------- Global Variables -----------------------------------

api_failure_count = 0  # Track failure counts for market data API
ticker_failure_count = 0  # Track failure counts for ticker API

last_data_fetch = time.monotonic()
last_ticker_update = time.monotonic()
last_gc_check = time.monotonic()
last_settings_fetch = time.monotonic()
last_time_update = time.monotonic()
last_ota_check = time.monotonic()
current_time_display = "0000"  # Initialize with a default value

last_displayed_btc_price = None
last_displayed_block_height = None
last_displayed_moscow_time = None
ticker_message = None

# Transit mode state
subway_time_index = None  # text layer index for arrival time
subway_label_index = None  # text layer index for subway line label (bold font)
bus_label_index = None  # text layer index for bus route label (compact font)
subway_circle_ref = None  # shape TileGrid reference (circle or square)
_subway_circle_bmp = None  # reusable shape bitmap
_subway_circle_pal = None  # reusable shape palette
_subway_initialized = False  # True after first display setup
_subway_current_shape = None  # "circle" or "square" — tracks current shape type

subway_arrivals_s = []  # cached southbound arrivals (downtown only)
subway_current_line = 0  # index into SUBWAY_LINES
last_line_cycle = time.monotonic()

api_current_base_url = "https://api.blocktron.io/api:2Pxae5kP/live_data_new"
api_current_ticker_url = "https://api.blocktron.io/api:2Pxae5kP/live_data_ticker_new"
api_current_settings_url = "https://api.blocktron.io/api:2Pxae5kP/device/get_settings/"

# Initialize device_id and api_key with default or empty values
device_id = "UNKNOWN_DEVICE"
device_api_key = "UNKNOWN_KEY"

# Default configuration values
conf_device_timezone_utc_offset = -5
conf_api_btc_price_refresh_interval = 30
conf_api_ticker_refresh_interval = 120
api_settings_refresh_interval = 180
device_max_failures_before_reboot = 3
conf_display_ticker_speed = 0.03
conf_device_boot_text_top = ""
conf_device_boot_text_bottom = "BlockTron"
conf_display_enable_moscow_time = True
conf_display_ticker_enabled = True
conf_status_pixel_enabled = True
conf_display_enable_clock = True
conf_display_update_pixel_duration = 0.01
device_button_check_interval = 0.1

# ------------------------- Hardware Setup -------------------------------------

# Create MatrixPortal object for handling display and network connection
matrixportal = MatrixPortal(
    status_neopixel=board.NEOPIXEL,
    bit_depth=6,
    width=64,
    height=32,
    color_order="RGB",
    debug=False,
)


# -------------- NTP Sync With Timed Print and Local Time Functions --------------------
def sync_time(retries=3, delay=1):
    """Attempt to set RTC from NTP. On failure, fall back gracefully."""
    pool = socketpool.SocketPool(wifi.radio)
    ntp = adafruit_ntp.NTP(pool, server="pool.ntp.org", port=123)
    for attempt in range(1, retries + 1):
        try:
            rtc.RTC().datetime = ntp.datetime
            timed_print("Time synced via NTP on attempt", attempt)
            return True
        except OSError as e:
            timed_print(f"NTP sync attempt {attempt} failed:", e)
            time.sleep(delay)
    timed_print("All NTP sync attempts failed; continuing without accurate time")
    return False


def get_local_time_struct():
    utc_now = time.localtime()
    # Convert struct_time to "seconds since epoch"
    utc_seconds = time.mktime(utc_now)
    # Apply UTC offset (in hours)
    local_seconds = utc_seconds + (conf_device_timezone_utc_offset * 3600)
    return time.localtime(local_seconds)


def timed_print(*args, **kwargs):
    if not DEVICE_LOGGING_ENABLED:
        return
    local_struct = get_local_time_struct()
    time_str = "{:04d}/{:02d}/{:02d} {:02d}:{:02d}:{:02d}".format(
        local_struct.tm_year,
        local_struct.tm_mon,
        local_struct.tm_mday,
        local_struct.tm_hour,
        local_struct.tm_min,
        local_struct.tm_sec,
    )
    message = " ".join(str(a) for a in args)
    print(f"[{time_str}] {message}", **kwargs)


sync_time()


# ------------------------- Import Cloud Settings -----------------------------------
def load_device_keys():
    global device_id, device_api_key, settings_url
    try:
        with open(DEVICE_KEYS_FILE, "r") as f:
            data = json.load(f)
            device_id = data.get("deviceId", device_id)
            device_api_key = data.get("apiKey", device_api_key)
            timed_print(f"Loaded device_id: {device_id}")
            timed_print(f"Loaded device_api_key: {device_api_key}")
    except Exception as e:
        timed_print(f"Error loading device keys: {e}")
    settings_url = f"{api_current_settings_url}{device_id}"


def fetch_cloud_settings():
    global api_failure_count
    global conf_device_timezone_utc_offset
    global conf_api_btc_price_refresh_interval
    global conf_api_ticker_refresh_interval
    global api_settings_refresh_interval
    global device_max_failures_before_reboot
    global conf_display_ticker_speed
    global conf_device_boot_text_top
    global conf_device_boot_text_bottom
    global conf_display_enable_moscow_time
    global conf_display_ticker_enabled
    global conf_status_pixel_enabled
    global conf_display_enable_clock
    global conf_display_update_pixel_duration
    global device_button_check_interval

    try:
        timed_print(f"Fetching settings from {settings_url}...")
        response = matrixportal.network.fetch(settings_url)
        if response.status_code == 200:
            settings_json = response.json()
            timed_print("Settings fetched successfully from cloud.")

            # Map JSON data to local variables with defaults if keys are missing
            conf_device_timezone_utc_offset = settings_json.get(
                "conf_device_timezone_utc_offset", conf_device_timezone_utc_offset
            )
            conf_api_btc_price_refresh_interval = settings_json.get(
                "conf_api_btc_price_refresh_interval",
                conf_api_btc_price_refresh_interval,
            )
            conf_api_ticker_refresh_interval = settings_json.get(
                "conf_api_ticker_refresh_interval", conf_api_ticker_refresh_interval
            )
            api_settings_refresh_interval = settings_json.get(
                "api_settings_refresh_interval", api_settings_refresh_interval
            )
            device_max_failures_before_reboot = settings_json.get(
                "device_max_failures_before_reboot", device_max_failures_before_reboot
            )
            conf_display_ticker_speed = settings_json.get(
                "conf_display_ticker_speed", conf_display_ticker_speed
            )
            conf_device_boot_text_top = str(
                settings_json.get(
                    "conf_device_boot_text_top", conf_device_boot_text_top
                )
            )
            conf_device_boot_text_bottom = str(
                settings_json.get(
                    "conf_device_boot_text_bottom", conf_device_boot_text_bottom
                )
            )
            conf_display_enable_moscow_time = settings_json.get(
                "conf_display_enable_moscow_time", conf_display_enable_moscow_time
            )
            conf_display_ticker_enabled = settings_json.get(
                "conf_display_ticker_enabled", conf_display_ticker_enabled
            )
            conf_display_enable_clock = settings_json.get(
                "conf_display_enable_clock", conf_display_enable_clock
            )
            conf_status_pixel_enabled = settings_json.get(
                "conf_status_pixel_enabled", conf_status_pixel_enabled
            )
            conf_display_update_pixel_duration = settings_json.get(
                "conf_display_update_pixel_duration", conf_display_update_pixel_duration
            )
            device_button_check_interval = settings_json.get(
                "device_button_check_interval", device_button_check_interval
            )

            timed_print("Cloud settings have been updated.")
        else:
            timed_print(
                f"Failed to fetch settings. Status code: {response.status_code}"
            )
    except Exception as e:
        timed_print(f"Error fetching cloud settings: {e}")
        api_failure_count += 1
        if api_failure_count >= device_max_failures_before_reboot:
            timed_print("Exceeded API errors while fetching settings, rebooting...")
            microcontroller.reset()
    finally:
        try:
            response.close()
        except NameError:
            pass


# Load device keys and fetch initial cloud settings
load_device_keys()
fetch_cloud_settings()

# ------------------------- Display Setup --------------------------------------
matrixportal.add_text(
    text_position=(2, -6),
    text_color=dim_color(PRICE_COLOR, GLOBAL_DIM_LEVEL),
    text_scale=1,
    is_data=True,
    text_font="/fonts/Arial-Bold-12.bdf",
    text=conf_device_boot_text_top,
)

matrixportal.add_text(
    text_position=(2, 25),
    text_color=dim_color(BLOCKHEIGHT_COLOR, GLOBAL_DIM_LEVEL),
    text_scale=1,
    is_data=True,
    text_font="/fonts/5x8-lean.bdf",
    text=conf_device_boot_text_bottom,
)

matrixportal.add_text(
    text_position=(43, 25),
    text_color=dim_color(MOSCOW_COLOR, GLOBAL_DIM_LEVEL),
    text_scale=1,
    is_data=True,
    text_font="/fonts/5x8-lean.bdf",
    text="",
)

matrixportal.add_text(
    text_position=(60, -2),
    text_color=dim_color(STATUS_PIXEL_COLOR, GLOBAL_DIM_LEVEL),
    text_scale=1,
    is_data=True,
    text_font="/fonts/4x6-lean.bdf",
    text="",
)

matrixportal.add_text(
    text_position=(0, 18),
    text_color=dim_color(TICKER_COLOR, GLOBAL_DIM_LEVEL),
    text_scale=1,
    is_data=True,
    scrolling=True,
    text_font="/fonts/5x8-lean.bdf",
)

matrixportal.add_text(
    text_position=(43, 17),
    text_color=dim_color(TIME_COLOR, GLOBAL_DIM_LEVEL),
    text_scale=1,
    is_data=True,
    text_font="/fonts/5x8-lean.bdf",
    text="",
)


# -----------------------------------------------------------------------------
#                              HELPER FUNCTIONS
# -----------------------------------------------------------------------------
def flash_status_pixel():
    matrixportal.set_text(".", STATUS_PIXEL_INDEX)
    time.sleep(conf_display_update_pixel_duration)
    matrixportal.set_text("", STATUS_PIXEL_INDEX)


def fetch_data_from_api():
    """Fetch main metrics, authenticating via device_id and api_key."""
    global api_failure_count
    try:
        # Build JSON payload
        body = json.dumps(
            {
                "device_id": device_id,
                "device_key": device_api_key,
            }
        )
        # POST via the underlying requests session, with a timeout
        response = matrixportal.network.requests.post(
            api_current_base_url,
            data=body,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )

        # If server returns something other than HTTP 200, bail out early
        if response.status_code != 200:
            timed_print("Bad HTTP status:", response.status_code, "↔", response.text)
            response.close()
            return None, None, None

        # Attempt to parse JSON, logging raw text on failure
        try:
            data = response.json()
        except ValueError as e:
            timed_print("JSON parse error:", e)
            timed_print("Raw response:", response.text)
            response.close()
            return None, None, None

        btc_price = None
        block_height = None
        moscow_time = None

        for metric in data:
            name = metric.get("metric_name")
            value_str = metric.get("metric_value")
            try:
                value = int(value_str)
            except (ValueError, TypeError):
                value = None
            if name == "block_height":
                block_height = value
            elif name == "btc_price":
                btc_price = value
            elif name == "moscow_time":
                moscow_time = value
        if btc_price is None or block_height is None or moscow_time is None:
            raise ValueError("Missing required metrics")
        api_failure_count = 0
        if conf_status_pixel_enabled:
            flash_status_pixel()
        return btc_price, block_height, moscow_time
    except OSError as e:
        # Retry once if connect still in progress
        if getattr(e, "errno", None) == errno.EINPROGRESS:
            timed_print("Connect in progress; retrying…")
            time.sleep(1)
            return fetch_data_from_api()
        timed_print("Market Data Err:", e)
        api_failure_count += 1
        if api_failure_count >= device_max_failures_before_reboot:
            timed_print("Exceeded API errors, rebooting…")
            microcontroller.reset()
    finally:
        try:
            response.close()
        except NameError:
            pass
    return None, None, None


def fetch_ticker_data():
    """Fetch scrolling ticker text, authenticating via device_id and api_key."""
    global ticker_failure_count
    try:
        # Build the auth payload
        body = json.dumps(
            {
                "device_id": device_id,
                "device_key": device_api_key,
            }
        )

        # 1) POST and check HTTP status
        response = matrixportal.network.requests.post(
            api_current_ticker_url,
            data=body,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code != 200:
            # Log non-200 pages (HTML error, etc.) and bail
            timed_print("Bad ticker status:", response.status_code, "↔", response.text)
            response.close()
            return None

        # 2) Extract and validate text, catching our own ValueError
        try:
            ticker_text = response.text.strip()
            # Strip surrounding quotes if present
            if ticker_text.startswith('"') and ticker_text.endswith('"'):
                ticker_text = ticker_text.strip('"')
            if not ticker_text:
                raise ValueError("Ticker Data Empty")
        except ValueError as e:
            timed_print("Ticker parse error:", e)
            timed_print("Raw ticker payload:", response.text)
            response.close()
            return None

        # On success, reset failure count and flash the status pixel
        ticker_failure_count = 0
        if conf_status_pixel_enabled:
            flash_status_pixel()
        return ticker_text

    except OSError as e:
        # Existing retry/reboot logic remains unchanged
        if getattr(e, "errno", None) == errno.EINPROGRESS:
            timed_print("Ticker connect in progress; retrying…")
            time.sleep(1)
            return fetch_ticker_data()
        timed_print("Ticker Data Err:", e)
        ticker_failure_count += 1
        if ticker_failure_count >= device_max_failures_before_reboot:
            timed_print("Exceeded API errors, rebooting…")
            microcontroller.reset()

    finally:
        try:
            response.close()
        except NameError:
            pass

    return None


def update_time_display(force=False):
    global current_time_display
    try:
        # Get the current local time
        local_time = get_local_time_struct()
        hour = local_time.tm_hour
        minute = local_time.tm_min

        # Format time as HHMM
        formatted_time = f"{hour:02d}{minute:02d}"

        # Update the display only if the time has changed or if forced
        if force or (formatted_time != current_time_display):
            current_time_display = formatted_time
            matrixportal.set_text(formatted_time, TIME_TEXT_INDEX)
            timed_print(f"Updated Time Display: {formatted_time}")
    except Exception as e:
        # In case of error, display a placeholder and log the error
        matrixportal.set_text("", TIME_TEXT_INDEX)
        timed_print(f"Time Update Error: {e}")


def maybe_collect_garbage(current_time):
    global last_gc_check
    if current_time - last_gc_check >= GC_CHECK_INTERVAL:
        free_mem = gc.mem_free()
        allocated = gc.mem_alloc()
        total = free_mem + allocated
        if total > 0:
            free_percent = (free_mem / total) * 100.0
            timed_print(f"Memory Check: {free_percent:.2f}% free")
            if free_percent < FREE_MEMORY_THRESHOLD:
                gc.collect()
                timed_print(f"GC processed. Current Mem {gc.mem_free()} bytes.")
        last_gc_check = current_time


# -------- OTA CONFIG (edit repo info only) --------
OTA_ENABLED = True
OTA_CHECK_INTERVAL = 3600  # seconds
OTA_REPO_BASE = (
    "https://raw.githubusercontent.com/GingerSherpa/BlockTron/main/Source/"  # <-- set
)
OTA_TARGETS = {
    "code.py": f"{OTA_REPO_BASE}/code.py",
    "boot.py": f"{OTA_REPO_BASE}/boot.py",
    "version_history.txt": f"{OTA_REPO_BASE}/version_history.txt",
}
_OTA_STAGE_FILE = "/ota_stage.json"
_OTA_CONFIRM_FILE = "/ota_confirmed"


def _ota_exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False


def ota_mark_success():
    try:
        if microcontroller.nvm[0] == 2:
            microcontroller.nvm[0] = 0
            microcontroller.nvm[1] = 0
            timed_print("OTA: confirmed restarting in 5 seconds")
            time.sleep(5)
            microcontroller.reset()
    except Exception as e:
        timed_print("OTA confirm err:", e)


def _http_get(url, stream=False, timeout=10):
    # Use the same session your code already uses
    resp = matrixportal.network.requests.get(url, timeout=timeout)
    return resp


def _download_to_temp(name, url):
    resp = None
    try:
        resp = _http_get(url, timeout=20)
        if resp.status_code != 200:
            timed_print("OTA GET fail", name, resp.status_code)
            return False
        data = resp.content  # small text files; safe to buffer
        if not data or len(data) < 32:
            timed_print("OTA too small", name, len(data))
            return False
        # very light sanity check on code files
        if name.endswith(".py") and (b"import " not in data):
            timed_print("OTA sanity fail", name)
            return False
        with open(name + ".new", "wb") as f:
            f.write(data)
        timed_print("OTA fetched", name, len(data), "bytes")
        return True
    except Exception as e:
        timed_print("OTA fetch err:", name, e)
        return False
    finally:
        try:
            if resp:
                resp.close()
        except Exception:
            pass


def _local_version_txt():
    try:
        with open("/version_history.txt", "rb") as f:
            return f.read()
    except Exception:
        return b""


def _remote_version_txt():
    resp = None
    try:
        url = OTA_TARGETS["version_history.txt"]
        resp = _http_get(url, timeout=10)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        pass
    finally:
        try:
            if resp:
                resp.close()
        except Exception:
            pass
    return None


def check_for_update_and_stage():
    if not OTA_ENABLED:
        return
    remote = _remote_version_txt()
    if not remote or remote == _local_version_txt():
        timed_print("OTA: No version change detected")
        return
    timed_print("OTA: version change detected; rebooting into download mode")
    microcontroller.nvm[0] = 1  # tell boot.py to disable MSC on next boot
    microcontroller.reset()


def ota_download_stage_if_needed():
    if microcontroller.nvm[0] != 1:
        return
    # MSC is already off (boot.py). Now we can write.
    try:
        storage.remount("/", False)
    except Exception as e:
        timed_print("OTA: remount RW failed:", e)
        microcontroller.nvm[0] = 0
        return

    ok = True
    for name, url in OTA_TARGETS.items():
        ok &= _download_to_temp(name, url)
    if not ok:
        timed_print("OTA: download failed; aborting")
        for name in OTA_TARGETS.keys():
            try:
                os.remove(name + ".new")
            except Exception:
                pass
        microcontroller.nvm[0] = 0
        try:
            storage.remount("/", True)
        except Exception:
            pass
        return

    with open(_OTA_STAGE_FILE, "w") as f:
        json.dump({"files": list(OTA_TARGETS.keys())}, f)
    try:
        storage.remount("/", True)
    except Exception:
        pass

    timed_print("OTA: staged; rebooting for atomic swap")
    microcontroller.nvm[0] = 3  # boot.py will atomically swap and set verify
    microcontroller.reset()


# -----------------------------------------------------------------------------
#                            SUBWAY MODE FUNCTIONS
# -----------------------------------------------------------------------------


def _is_bus_line(line_name):
    """Check if a line is a bus route based on API response type data."""
    return _transit_line_types.get(line_name) == "bus"


def _get_shape_bitmap(line_name):
    """Return the appropriate shape bitmap data (circle for subway, square for bus)."""
    if _is_bus_line(line_name):
        return BUS_SQUARE_BMP
    return SUBWAY_CIRCLE_BMP


def _get_shape_type(line_name):
    """Return 'square' for bus, 'circle' for subway."""
    return "square" if _is_bus_line(line_name) else "circle"


def _get_shape_color(line_name):
    """Return the shape background color for a line."""
    if _is_bus_line(line_name):
        return dim_color(BUS_COLOR, GLOBAL_DIM_LEVEL)
    return dim_color(SUBWAY_COLORS.get(line_name, 0xFFFFFF), GLOBAL_DIM_LEVEL)


def _update_label(label_idx, text, lx, ly):
    """Reposition and update a text label, removing the old one from splash first."""
    text_entry = matrixportal._text[label_idx]
    old_label = text_entry.get("label")
    if old_label is not None:
        for i in range(len(matrixportal.splash) - 1, 0, -1):
            if matrixportal.splash[i] is old_label:
                matrixportal.splash.pop(i)
                break
        text_entry["label"] = None
    text_entry["position"] = (lx, ly)
    matrixportal.set_text(text, label_idx)


def subway_setup_display():
    """Clear the Bitcoin display and set up single-line transit layout.

    Bitmap object (21x19) is created once and reused for both circle and square
    by rewriting pixels in place. Two label text layers are created at init —
    one with bold font (subway) and one with compact font (bus). Only one is
    visible at a time; the other is set to blank.
    """
    global subway_time_index, subway_label_index, bus_label_index, subway_circle_ref
    global _subway_circle_bmp, _subway_circle_pal, _subway_initialized
    global _subway_current_shape

    # Clear all 6 Bitcoin text layers
    for i in range(6):
        matrixportal.set_text("", i)

    line_name = SUBWAY_LINES[subway_current_line]
    is_bus = _is_bus_line(line_name)
    color = _get_shape_color(line_name)
    shape_type = _get_shape_type(line_name)
    shape_bmp_data = _get_shape_bitmap(line_name)

    if not _subway_initialized:
        # First-time setup: create all objects once

        # Remove all splash children except the base display bitmap (index 0)
        while len(matrixportal.splash) > 1:
            matrixportal.splash.pop()

        # Shape bitmap (21x19, created once, reused via palette swap and pixel rewrite)
        h = len(shape_bmp_data)
        w = len(shape_bmp_data[0])
        _subway_circle_bmp = displayio.Bitmap(w, h, 2)
        _subway_circle_pal = displayio.Palette(2)
        _subway_circle_pal.make_transparent(0)
        _subway_circle_pal[1] = color
        for row in range(h):
            for col in range(w):
                _subway_circle_bmp[col, row] = shape_bmp_data[row][col]
        subway_circle_ref = displayio.TileGrid(
            _subway_circle_bmp,
            pixel_shader=_subway_circle_pal,
            x=SUBWAY_CIRCLE_X,
            y=SUBWAY_CIRCLE_Y,
        )
        matrixportal.splash.append(subway_circle_ref)
        _subway_current_shape = shape_type

        # Bold label (Arial-Bold-12) — subway letter, or bus route number
        if is_bus:
            slx, sly = BUS_NUMBER_OFFSETS.get(line_name, (9, 2))
            bold_text = line_name[1:]  # e.g. "7" or "10"
        else:
            slx, sly = SUBWAY_LABEL_OFFSETS.get(line_name, (8, 2))
            bold_text = line_name
        subway_label_index = matrixportal.add_text(
            text_position=(slx, sly),
            text_color=dim_color(0xFFFFFF, GLOBAL_DIM_LEVEL),
            text_font=SUBWAY_LABEL_FONT,
            is_data=True,
            text=bold_text,
        )

        # Compact label (4x6-lean) — unused now, kept as blank placeholder
        bus_label_index = matrixportal.add_text(
            text_position=(4, 14),
            text_color=dim_color(0xFFFFFF, GLOBAL_DIM_LEVEL),
            text_font=BUS_LABEL_FONT,
            is_data=True,
            text="",
        )

        # Arrival time — created once, index reused forever
        subway_time_index = matrixportal.add_text(
            text_position=(SUBWAY_TIME_X, SUBWAY_TIME_Y),
            text_color=dim_color(0xFFFFFF, GLOBAL_DIM_LEVEL),
            text_font=SUBWAY_TIME_FONT,
            is_data=True,
            text="",
        )

        _subway_initialized = True
    else:
        # Subsequent calls: minimal allocations

        # If shape type changed (circle <-> square), rewrite bitmap pixels
        if shape_type != _subway_current_shape:
            h = len(shape_bmp_data)
            w = len(shape_bmp_data[0])
            for row in range(h):
                for col in range(w):
                    _subway_circle_bmp[col, row] = shape_bmp_data[row][col]
            _subway_current_shape = shape_type

        # Update shape color
        _subway_circle_pal[1] = color

        # Show the appropriate label in the bold slot
        if is_bus:
            nlx, nly = BUS_NUMBER_OFFSETS.get(line_name, (9, 2))
            _update_label(subway_label_index, line_name[1:], nlx, nly)
        else:
            slx, sly = SUBWAY_LABEL_OFFSETS.get(line_name, (8, 2))
            _update_label(subway_label_index, line_name, slx, sly)
        # Compact slot always blank (no "M" prefix)
        _update_label(bus_label_index, "", 4, 14)

        # Clear and re-set arrival time (position doesn't change)
        matrixportal.set_text("", subway_time_index)

    gc.collect()
    timed_print(
        f"Transit display: {line_name} ({shape_type}) (mem: {gc.mem_free()} bytes)"
    )


def subway_cycle_line():
    """Advance to the next line with data, rebuild display."""
    global subway_current_line
    original = subway_current_line
    # Try each line in order, skip lines with no arrival data
    for _ in range(len(SUBWAY_LINES)):
        candidate = (subway_current_line + 1) % len(SUBWAY_LINES)
        subway_current_line = candidate
        line_name = SUBWAY_LINES[subway_current_line]
        if _subway_line_has_data(line_name):
            break
    else:
        # No lines have data — stay on current line
        subway_current_line = original
    # Rebuild display for the new line (handles per-char centering)
    subway_setup_display()


def _subway_line_has_data(line_name):
    """Check if a line has any arrival data (downtown/southbound only)."""
    for entry in subway_arrivals_s:
        if entry["line"] == line_name and len(entry.get("mins", [])) > 0:
            return True
    return False


def subway_fetch_arrivals():
    """Fetch arrival data (downtown/southbound only) from the proxy server."""
    global subway_arrivals_s, api_failure_count, _transit_line_types

    try:
        url = SUBWAY_PROXY_BASE
        response = matrixportal.network.requests.get(url, timeout=10)
        if response.status_code != 200:
            timed_print("Transit proxy err:", response.status_code)
            response.close()
            return
        data = response.json()
        response.close()
        arrivals = data.get("arrivals", [])
        subway_arrivals_s = arrivals
        # Update line type map from API response
        for entry in arrivals:
            line = entry.get("line", "")
            ltype = entry.get("type", "subway")
            if line:
                _transit_line_types[line] = ltype
        api_failure_count = 0
        timed_print("Transit data fetched (S)")
        gc.collect()
    except Exception as e:
        timed_print("Transit fetch err:", e)
        api_failure_count += 1
        if api_failure_count >= device_max_failures_before_reboot:
            timed_print("Exceeded transit API errors, rebooting...")
            microcontroller.reset()
        try:
            response.close()
        except Exception:
            pass


def subway_update_display():
    """Update the arrival time text for the current line (downtown only)."""
    line_name = SUBWAY_LINES[subway_current_line]

    # Find arrival times for current line
    mins = []
    for entry in subway_arrivals_s:
        if entry["line"] == line_name:
            mins = entry.get("mins", [])
            break

    if len(mins) >= 2:
        text = f"{mins[0]},{mins[1]}m"
    elif len(mins) == 1:
        text = f"{mins[0]}m"
    else:
        text = ""
    matrixportal.set_text(text, subway_time_index)


# Call once early on successful startup to confirm new build, if any
ota_mark_success()
ota_download_stage_if_needed()

# Initialize subway mode if enabled
if SUBWAY_MODE_ENABLED:
    subway_setup_display()
    subway_fetch_arrivals()
    subway_update_display()
    last_data_fetch = time.monotonic()
    last_line_cycle = time.monotonic()
    timed_print("Transit mode initialized (downtown only)")

# -----------------------------------------------------------------------------
#                                   MAIN LOOP
# -----------------------------------------------------------------------------
while True:
    current_time = time.monotonic()

    # ---- Transit Mode (downtown/southbound only) ----
    if SUBWAY_MODE_ENABLED:
        # Fetch southbound arrivals every SUBWAY_REFRESH_INTERVAL seconds
        if current_time - last_data_fetch >= SUBWAY_REFRESH_INTERVAL:
            subway_fetch_arrivals()
            subway_update_display()
            last_data_fetch = current_time

        # Cycle to next line every SUBWAY_LINE_CYCLE seconds
        if current_time - last_line_cycle >= SUBWAY_LINE_CYCLE:
            subway_cycle_line()
            subway_update_display()
            last_line_cycle = current_time

        # Keep settings and OTA running
        if current_time - last_settings_fetch >= api_settings_refresh_interval:
            fetch_cloud_settings()
            last_settings_fetch = current_time
        if OTA_ENABLED and (current_time - last_ota_check) >= OTA_CHECK_INTERVAL:
            check_for_update_and_stage()
            last_ota_check = current_time

        # Aggressive GC every loop iteration to keep memory stable
        gc.collect()

        time.sleep(0.5)
        continue

    # ---- Bitcoin Mode (existing logic) ----

    # Fetch market data periodically
    if (
        (current_time - last_data_fetch >= conf_api_btc_price_refresh_interval)
        or (last_displayed_btc_price is None)
        or (last_displayed_block_height is None)
    ):
        btc_price, block_height, moscow_time = fetch_data_from_api()
        if (
            btc_price is not None
            and block_height is not None
            and moscow_time is not None
        ):
            # Update display if the values have changed
            if btc_price != last_displayed_btc_price:
                matrixportal.set_text(f"{btc_price}", PRICE_TEXT_INDEX)
                last_displayed_btc_price = btc_price
            if block_height != last_displayed_block_height:
                matrixportal.set_text(f"{block_height}", BLOCKHEIGHT_TEXT_INDEX)
                last_displayed_block_height = block_height
            if conf_display_enable_moscow_time:
                if moscow_time != last_displayed_moscow_time:
                    matrixportal.set_text(f"{moscow_time}", MOSCOW_TEXT_INDEX)
                    last_displayed_moscow_time = moscow_time
            else:
                matrixportal.set_text("", MOSCOW_TEXT_INDEX)
                last_displayed_moscow_time = None
            timed_print(
                f"Fetched Data: BTC={btc_price}, BlockHeight={block_height}, MoscowTime={moscow_time}"
            )
        else:
            # Display errors if data is missing, and force a repaint on next good fetch
            if btc_price is None:
                matrixportal.set_text("Price Err", PRICE_TEXT_INDEX)
                last_displayed_btc_price = None
            if block_height is None:
                matrixportal.set_text("Blk Err", BLOCKHEIGHT_TEXT_INDEX)
                last_displayed_block_height = None
            if moscow_time is None:
                matrixportal.set_text("Err", MOSCOW_TEXT_INDEX)
                last_displayed_moscow_time = None
        last_data_fetch = current_time
    # **Conditional Display: Ticker or Time**
    if conf_display_ticker_enabled:
        # Check if it's time to fetch and scroll the ticker
        if current_time - last_ticker_update >= conf_api_ticker_refresh_interval:
            # Fetch and set the ticker message
            new_ticker_message = fetch_ticker_data()
            if new_ticker_message:
                ticker_message = new_ticker_message
                # **Clear the time display before scrolling the ticker**
                matrixportal.set_text("", TIME_TEXT_INDEX)

                matrixportal.set_text(f"{ticker_message}", TICKER_TEXT_INDEX)
                timed_print(f"Updated Ticker: {ticker_message}")
            else:
                if ticker_message is None:
                    matrixportal.set_text("Ticker Err", TICKER_TEXT_INDEX)
                else:
                    timed_print("Keeping old ticker due to fetch error.")
                ticker_message = None
            # Scroll the ticker text (blocking call)
            matrixportal.scroll_text(conf_display_ticker_speed)
            last_ticker_update = current_time

            # **Re-display the time after scrolling**
            if conf_display_enable_clock:
                update_time_display(force=True)
                last_time_update = current_time  # Reset time update timer
    if conf_display_enable_clock:
        # If we've just re‐enabled (current_time_display was cleared),
        # or 5 seconds have passed, redraw the clock:
        if current_time_display is None or (current_time - last_time_update) >= 5:
            update_time_display()
            last_time_update = current_time
    else:
        # If disabling, clear the display once:
        if current_time_display is not None:
            matrixportal.set_text("", TIME_TEXT_INDEX)
            current_time_display = None
    # Periodically fetch cloud settings
    if current_time - last_settings_fetch >= api_settings_refresh_interval:
        fetch_cloud_settings()
        last_settings_fetch = current_time
    # Check for garbage collection
    maybe_collect_garbage(current_time)

    # Periodic OTA check
    if OTA_ENABLED and (current_time - last_ota_check) >= OTA_CHECK_INTERVAL:
        check_for_update_and_stage()
        last_ota_check = current_time

    time.sleep(device_button_check_interval)
