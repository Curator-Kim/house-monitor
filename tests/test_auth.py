import json
from pathlib import Path

import requests
from house_monitor.auth import apply_auth, load_auth, parse_cookie_header, save_auth


def test_parse_cookie_header():
    assert parse_cookie_header("a=1; b=two; empty=") == {"a": "1", "b": "two", "empty": ""}
    assert parse_cookie_header("bad; x=y") == {"x": "y"}


def test_save_load_and_apply_auth(tmp_path):
    result = save_auth(tmp_path, "lianjia", cookie="lianjia_uuid=abc; token=xyz",
                       headers=["X-Test: yes"])
    assert result["cookies"] == 2
    assert Path(result["auth_file"]).exists()
    payload = load_auth(tmp_path, "lianjia")
    assert payload["cookies"]["lianjia_uuid"] == "abc"
    assert payload["headers"]["X-Test"] == "yes"

    class Client:
        config = {"data_dir": str(tmp_path)}

        def __init__(self):
            self.session = requests.Session()

    client = Client()
    assert apply_auth(client, "lianjia") is True
    assert client.session.cookies.get("token") == "xyz"
    assert client.session.headers["X-Test"] == "yes"
    assert apply_auth(client, "missing") is False


def test_auth_file_can_merge_cookies(tmp_path):
    source = tmp_path / "auth.json"
    source.write_text(json.dumps({"cookies": {"a": "1"}, "headers": {"X-A": "1"}}), encoding="utf-8")
    save_auth(tmp_path / "data", "lianjia", auth_file=source, cookie="b=2")
    payload = load_auth(tmp_path / "data", "lianjia")
    assert payload["cookies"] == {"a": "1", "b": "2"}
    assert payload["headers"] == {"X-A": "1"}