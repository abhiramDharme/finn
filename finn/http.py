from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def session() -> requests.Session:
    client = requests.Session()
    client.headers["User-Agent"] = UA
    retry = Retry(total=2, backoff_factor=0.4, status_forcelist=(429, 500, 502, 503))
    client.mount("https://", HTTPAdapter(max_retries=retry))
    return client
