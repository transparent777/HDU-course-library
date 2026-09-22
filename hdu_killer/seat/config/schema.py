"""V2 configuration schema and defaults."""

from __future__ import annotations

CONFIG_TEMPLATE = """
user:
  login_name: ""
  password: ""
  org_id: "104"

plans: []

schedules: []

settings:
  interval: 5
  max_try_times: 10
  auto_relogin: true

api:
  base_url: "https://hdu.huitu.zhishulib.com"

session:
  headers:
    Accept: '*/*'
    Accept-Encoding: gzip, deflate, br
    Accept-Language: en-US,en;q=0.5
    Cache-Control: no-cache
    Connection: keep-alive
    Pragma: no-cache
    Referer: https://hdu.huitu.zhishulib.com/
    Sec-Fetch-Dest: empty
    Sec-Fetch-Mode: no-cors
    Sec-Fetch-Site: same-origin
    User-Agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
  params:
    LAB_JSON: '1'
  trust_env: false
  verify: false
"""

# V1 config keys that indicate we need migration
V1_INDICATORS = ["seat_list", "urls", "data", "user_info"]


def get_default_config() -> dict:
    """Return the default V2 configuration as a dict."""
    import yaml
    return yaml.safe_load(CONFIG_TEMPLATE)


# API endpoint paths relative to base_url
API_ENDPOINTS = {
    "query_rooms": "/Space/Category/list",
    "query_seats": "/Seat/Index/searchSeats",
    "book_seat": "/Seat/Index/bookSeats",
    "login": "/User/Index/login",
    "index": "/",
}
