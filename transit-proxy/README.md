# Subway Proxy Server

A lightweight proxy that fetches real-time MTA subway arrival data and serves it as JSON for the BlockTron device.

The BlockTron (CircuitPython on MatrixPortal S3) can't parse GTFS protobuf feeds directly, so this proxy handles the heavy lifting on a web server and returns simple JSON.

## Architecture

```
BlockTron Device  -->  arrivals.php  -->  fetch_arrivals.py  -->  MTA GTFS-RT Feeds
   (HTTP GET)          (PHP wrapper)      (Python, protobuf)      (real-time data)
```

## Requirements

- Web server with PHP (Apache/Nginx)
- Python 3.8+
- pip

## Setup

### 1. Install Python dependencies

```bash
cd subway-proxy
pip3 install -r requirements.txt
```

### 2. Configure your station

Copy the example env file and edit it with your station's MTA stop IDs:

```bash
cp .env.example .env
```

Edit `.env` with your station's stop IDs and lines:

```
# Uptown / Bronx / Queens-bound (MTA "N" direction)
SUBWAY_STOP_IDS_N=your-uptown-stop-ids

# Downtown / Brooklyn-bound (MTA "S" direction)
SUBWAY_STOP_IDS_S=your-downtown-stop-ids

SUBWAY_LINES=your-comma-separated-lines
```

The MTA GTFS feeds use `N` for uptown/Bronx/Queens-bound and `S` for downtown/Brooklyn-bound, regardless of the actual compass direction of the tracks.

**Finding your stop IDs:** Stop IDs follow the format `{station}{direction}` (e.g., `R01N` for Times Square uptown). You can find station IDs in the [MTA GTFS Static data](https://new.mta.info/developers) under `stops.txt`, or search the [MTA Subway Stations dataset](https://data.ny.gov/Transportation/MTA-Subway-Stations/39hk-dx4f). Stations served by lines from different divisions (e.g., IND and IRT) will have multiple stop IDs — include all of them comma-separated.

### 3. Deploy to your web server

Copy `arrivals.php`, `fetch_arrivals.py`, `.env`, and `requirements.txt` to a directory served by your web server. Ensure:

- PHP can execute `shell_exec()` (not disabled in `php.ini`)
- Python 3 is available at `python3` in the server's PATH
- The `.env` file is readable by the web server process

### 4. Test

```bash
# Test the Python script directly
python3 fetch_arrivals.py N

# Test via the PHP endpoint
curl "https://your-server.com/arrivals.php?direction=N"
```

Expected response:

```json
{
  "updated": 1707400000,
  "direction": "N",
  "arrivals": [
    {"line": "A", "mins": [3, 12]},
    {"line": "C", "mins": []},
    {"line": "B", "mins": [7]},
    {"line": "D", "mins": [5, 18]},
    {"line": "2", "mins": [1, 9]},
    {"line": "3", "mins": [4]}
  ]
}
```

### 5. Configure the BlockTron device

On the device's `settings.toml`:

```toml
SUBWAY_PROXY_BASE="https://your-server.com/arrivals.php"
SUBWAY_LINES="A,C,B,D,2,3"
```

## Caching

The proxy caches raw GTFS-RT feed data in `/tmp/subway_proxy_cache/` for 30 seconds to avoid hammering the MTA API. Stale cache is used as fallback if a fresh fetch fails.

## API

### `GET /arrivals.php?direction={N|S}`

| Parameter | Required | Values | Description |
|-----------|----------|--------|-------------|
| direction | No | `N`, `S` | Train direction. Defaults to `S`. |

Returns JSON with arrival times in minutes for each configured line.
