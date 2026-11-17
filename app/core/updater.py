"""应用内检查更新 / 下载安装包。

只访问 GitHub 官方 Releases API，不需要 token：
    GET https://api.github.com/repos/<owner>/<repo>/releases/latest

支持：
    · 比较 v1.0.5 这类 tag 与当前版本；
    · 按平台选择 Windows exe / macOS dmg；
    · 流式下载到用户数据目录 updates/，带进度回调；
    · 下载完成后调用系统默认方式打开安装包。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from app.paths import user_data_dir
from app.version import APP_VERSION, GITHUB_REPO

API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
USER_AGENT = "SmartWMS-Updater/1.0"


class UpdateError(RuntimeError):
    """检查或下载更新失败。"""


class UpdateCancelled(UpdateError):
    """用户取消下载。"""


@dataclass
class UpdateInfo:
    current: str
    latest: str
    tag: str
    name: str
    notes: str
    html_url: str
    asset_name: str = ""
    asset_url: str = ""
    asset_api_url: str = ""
    asset_size: int = 0
    has_update: bool = False
    published_at: str = ""

    @property
    def version(self) -> str:
        return self.tag.lstrip("vV")


def parse_version(value: str) -> tuple[int, ...]:
    """把 v1.0.5 / 1.0.5-beta 解析成可比较的整数元组。"""
    numbers = [int(part) for part in re.findall(r"\d+", str(value or ""))]
    return tuple(numbers) if numbers else (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def asset_for_platform(assets: list[dict], platform: str | None = None) -> dict | None:
    """从 release assets 中选择当前平台安装包。"""
    platform = platform or sys.platform
    names = [(str(a.get("name", "")).lower(), a) for a in assets]
    if platform == "win32":
        for name, asset in names:
            if "windows" in name and name.endswith(".exe"):
                return asset
        for name, asset in names:
            if name.endswith(".exe"):
                return asset
        return None
    if platform == "darwin":
        for name, asset in names:
            if "macos" in name and name.endswith(".dmg"):
                return asset
        for name, asset in names:
            if name.endswith(".dmg"):
                return asset
        return None
    return None


def _http_get(
    url: str,
    *,
    headers: dict[str, str],
    timeout: int,
    stream: bool = False,
):
    """GET GitHub，并在代理/限流异常时尝试直连。"""
    first_error: Exception | None = None
    try:
        response = requests.get(
            url, headers=headers, timeout=timeout, stream=stream, allow_redirects=True
        )
        if response.status_code not in (403, 407):
            return response
        response.close()
    except requests.RequestException as exc:
        first_error = exc

    # 某些代理出口会被 GitHub 判定为限流（403）；直连通常可用。
    session = requests.Session()
    session.trust_env = False
    try:
        return session.get(
            url, headers=headers, timeout=timeout, stream=stream, allow_redirects=True
        )
    except requests.RequestException as exc:
        raise exc from first_error


def check_for_update(
    current: str = APP_VERSION,
    timeout: int = 12,
) -> UpdateInfo:
    """查询 GitHub 最新 Release。始终返回 UpdateInfo，has_update 表示是否更新。"""
    try:
        response = _http_get(
            API_LATEST,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise UpdateError(f"无法连接 GitHub：{exc}") from exc

    if response.status_code == 403:
        raise UpdateError("GitHub API 访问受限（可能触发限流），请稍后再试")
    if response.status_code == 404:
        raise UpdateError("没有找到 Release，请确认仓库地址")
    if response.status_code >= 400:
        raise UpdateError(f"GitHub 返回 HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError as exc:
        raise UpdateError("GitHub 返回内容不是合法 JSON") from exc

    tag = str(data.get("tag_name", "")).strip()
    if not tag:
        raise UpdateError("Release 缺少 tag_name")

    assets = data.get("assets", []) or []
    asset = asset_for_platform(assets) or {}
    return UpdateInfo(
        current=current,
        latest=tag.lstrip("vV"),
        tag=tag,
        name=str(data.get("name") or tag),
        notes=str(data.get("body") or ""),
        html_url=str(data.get("html_url") or ""),
        asset_name=str(asset.get("name") or ""),
        asset_url=str(asset.get("browser_download_url") or ""),
        asset_api_url=str(asset.get("url") or ""),
        asset_size=int(asset.get("size") or 0),
        has_update=is_newer(tag, current),
        published_at=str(data.get("published_at") or ""),
    )


def update_dir() -> Path:
    path = user_data_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_update(
    info: UpdateInfo,
    progress: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    timeout: int = 120,
) -> Path:
    """下载当前平台安装包，返回本地路径。

    优先走 API asset 地址（对 github.com 网页域名受限的网络更稳），
    失败再回退到 browser_download_url。
    """
    if not info.asset_name:
        raise UpdateError("该 Release 没有当前平台的安装包")
    suffix = Path(info.asset_name).suffix or ".bin"
    target = update_dir() / f"SmartWMS-{info.version}{suffix}"
    part = target.with_suffix(target.suffix + ".part")
    urls = [url for url in (info.asset_api_url, info.asset_url) if url]
    if not urls:
        raise UpdateError("Release 没有可下载地址")

    last_error = ""
    for url in urls:
        headers = {"User-Agent": USER_AGENT}
        if "api.github.com" in url:
            headers["Accept"] = "application/octet-stream"
        try:
            response = _http_get(
                url, headers=headers, timeout=timeout, stream=True
            )
            try:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or info.asset_size or 0)
                downloaded = 0
                with part.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        if cancel_check and cancel_check():
                            raise UpdateCancelled("已取消下载")
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress(downloaded, total)
            finally:
                close = getattr(response, "close", None)
                if close is not None:
                    close()
            if info.asset_size and part.stat().st_size != info.asset_size:
                raise UpdateError("下载文件大小与 Release 不一致")
            part.replace(target)
            return target
        except UpdateCancelled:
            part.unlink(missing_ok=True)
            raise
        except (requests.RequestException, OSError, ValueError) as exc:
            last_error = str(exc)
            part.unlink(missing_ok=True)
            continue

    raise UpdateError(f"下载失败：{last_error or '未知错误'}")


def launch_installer(path: str | Path) -> None:
    """用系统默认方式打开安装包（Windows exe / macOS dmg / Linux 文件）。"""
    target = str(path)
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def open_release_page(url: str) -> None:
    import webbrowser

    if url:
        webbrowser.open(url)
