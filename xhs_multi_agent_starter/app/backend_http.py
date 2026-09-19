"""Keep local UI-to-API traffic independent of external HTTP proxies."""
from ipaddress import ip_address
from urllib.parse import urlsplit

import requests


def create_backend_session(base_url: str) -> requests.Session:
    session = requests.Session()
    hostname = (urlsplit(base_url).hostname or "").lower()
    try:
        loopback = ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname in {"localhost", "localhost."}
    if loopback:
        session.trust_env = False
    return session
