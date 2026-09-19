from unittest.mock import patch

import pytest

from app.backend_http import create_backend_session


@pytest.mark.parametrize("host", ["localhost", "localhost.", "127.0.0.1", "[::1]"])
def test_local_health_generation_and_feedback_bypass_proxy(host):
    base_url = f"http://{host}:8000"
    with patch.dict("os.environ", {"HTTP_PROXY": "http://proxy.invalid:9999"}, clear=True):
        with create_backend_session(base_url) as session:
            for path in ("/health", "/api/runs", "/api/runs/example/feedback"):
                settings = session.merge_environment_settings(base_url + path, {}, None, None, None)
                assert not settings["proxies"]


@pytest.mark.parametrize("host", ["api.example.com", "localhost.example.com", "backend"])
def test_non_local_backends_keep_environment_proxy(host):
    url = f"http://{host}:8000/health"
    with patch.dict("os.environ", {"HTTP_PROXY": "http://proxy.invalid:9999"}, clear=True):
        with create_backend_session(url) as session:
            settings = session.merge_environment_settings(url, {}, None, None, None)
            assert settings["proxies"]["http"] == "http://proxy.invalid:9999"
