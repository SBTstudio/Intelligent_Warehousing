"""应用内更新检查测试。"""

from __future__ import annotations

from app.core import updater


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, chunks=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self._chunks = chunks or []
        self.headers = headers or {}
        self.text = ""
        self._closed = False

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise updater.requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1024):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._closed = True


def test_version_parsing_and_compare():
    assert updater.parse_version("v1.0.5") == (1, 0, 5)
    assert updater.is_newer("v1.0.5", "1.0.4") is True
    assert updater.is_newer("v1.0.4", "1.0.4") is False
    assert updater.is_newer("v1.0.3", "1.0.4") is False


def test_asset_for_platform():
    assets = [
        {"name": "SmartWMS-Windows-x64.exe", "browser_download_url": "win"},
        {"name": "SmartWMS-macOS-arm64.dmg", "browser_download_url": "mac"},
    ]
    assert updater.asset_for_platform(assets, "win32")["browser_download_url"] == "win"
    assert updater.asset_for_platform(assets, "darwin")["browser_download_url"] == "mac"
    assert updater.asset_for_platform(assets, "linux") is None


def test_check_for_update_selects_release_asset(monkeypatch):
    payload = {
        "tag_name": "v1.0.5",
        "name": "v1.0.5",
        "body": "更新内容",
        "html_url": "https://github.com/SBTstudio/Intelligent_Warehousing/releases/tag/v1.0.5",
        "published_at": "2026-11-17T00:00:00Z",
        "assets": [
            {
                "name": "SmartWMS-Windows-x64.exe",
                "browser_download_url": "https://example.com/win.exe",
                "url": "https://api.github.com/assets/1",
                "size": 123,
            },
            {
                "name": "SmartWMS-macOS-arm64.dmg",
                "browser_download_url": "https://example.com/mac.dmg",
                "url": "https://api.github.com/assets/2",
                "size": 456,
            },
        ],
    }
    monkeypatch.setattr(
        updater.requests, "get", lambda *args, **kwargs: _FakeResponse(200, payload)
    )
    info = updater.check_for_update("1.0.4", platform="darwin")
    assert info.has_update is True
    assert info.tag == "v1.0.5"
    assert info.asset_name in {
        "SmartWMS-Windows-x64.exe",
        "SmartWMS-macOS-arm64.dmg",
    }
    assert info.asset_url.startswith("https://example.com/")


def test_check_for_update_same_version(monkeypatch):
    monkeypatch.setattr(
        updater.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse(200, {"tag_name": "v1.0.4", "assets": []}),
    )
    info = updater.check_for_update("1.0.4", platform="darwin")
    assert info.has_update is False


def test_download_update_streams_file(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "update_dir", lambda: tmp_path)
    payload = b"fake installer bytes"
    response = _FakeResponse(
        200,
        chunks=[payload[:5], payload[5:]],
        headers={"Content-Length": str(len(payload))},
    )
    monkeypatch.setattr(updater.requests, "get", lambda *args, **kwargs: response)
    info = updater.UpdateInfo(
        current="1.0.4",
        latest="1.0.5",
        tag="v1.0.5",
        name="test",
        notes="",
        html_url="",
        asset_name="SmartWMS-Windows-x64.exe",
        asset_url="https://example.com/win.exe",
        asset_size=len(payload),
        has_update=True,
    )
    path = updater.download_update(info)
    assert path.exists()
    assert path.read_bytes() == payload
    assert path.name == "SmartWMS-1.0.5.exe"
