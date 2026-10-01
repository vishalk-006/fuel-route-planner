from functools import cache

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from fuelplanner.conf import planner_settings


@cache
def http_session() -> requests.Session:
    retry = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=(429, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=10))
    session.mount("http://", HTTPAdapter(max_retries=retry, pool_maxsize=10))
    session.headers["User-Agent"] = planner_settings().http_user_agent
    return session
