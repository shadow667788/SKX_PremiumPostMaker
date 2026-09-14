from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import aiohttp

from config import DB_PATH, GITHUB_BRANCH, GITHUB_REPO, GITHUB_TOKEN
from emoji_pools import PREMIUM_EMOJI_IDS

CACHE_DIR = DB_PATH.parent / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)


class GitHubJSONStore:
    def __init__(self) -> None:
        self.token = GITHUB_TOKEN
        config_path = DB_PATH.parent / "config.json"
        file_config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        self.repo = GITHUB_REPO or file_config.get("github_repo", "")  # owner/repository
        self.branch = GITHUB_BRANCH or file_config.get("github_branch", "main")
        self.base = "https://api.github.com"
        self._lock = asyncio.Lock()
        self.emoji_ids = list(PREMIUM_EMOJI_IDS)

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.repo and "/" in self.repo)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

    def _path(self, name: str) -> Path:
        return CACHE_DIR / name

    async def _request(self, method: str, url: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        async with aiohttp.ClientSession(headers=self._headers()) as session:
            async with session.request(method, url, **kwargs) as response:
                try:
                    data = await response.json()
                except Exception:
                    data = {}
                return response.status, data

    async def _get_file(self, name: str) -> dict[str, Any] | None:
        status, data = await self._request("GET", f"{self.base}/repos/{self.repo}/contents/{name}?ref={self.branch}")
        if status != 200:
            return None
        import base64
        try:
            raw = base64.b64decode(data["content"]).decode("utf-8")
            return {"value": json.loads(raw), "sha": data.get("sha")}
        except Exception:
            return None

    async def _put_file(self, name: str, value: dict[str, Any], sha: str | None = None) -> None:
        import base64
        body = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        payload: dict[str, Any] = {"message": f"chore: update {name}", "content": base64.b64encode(body).decode(), "branch": self.branch}
        if sha:
            payload["sha"] = sha
        status, data = await self._request("PUT", f"{self.base}/repos/{self.repo}/contents/{name}", json=payload)
        if status not in (200, 201):
            raise RuntimeError(f"GitHub write failed ({status}): {data.get('message', data)}")

    async def initialize(self) -> None:
        meta_path = "skx/meta.json"
        local = self._path("meta.json")
        remote = await self._get_file(meta_path) if self.enabled else None
        if remote:
            self.emoji_ids = remote["value"].get("emoji_ids", self.emoji_ids)
            local.write_text(json.dumps(remote["value"], ensure_ascii=False, indent=2), encoding="utf-8")
        elif local.exists():
            try:
                self.emoji_ids = json.loads(local.read_text(encoding="utf-8")).get("emoji_ids", self.emoji_ids)
            except Exception:
                pass
        if self.enabled and not remote:
            await self._put_file(meta_path, {"emoji_ids": self.emoji_ids, "owner_ids": [], "version": 1})

    async def load_meta(self) -> dict[str, Any]:
        remote = await self._get_file("skx/meta.json") if self.enabled else None
        if remote:
            return remote["value"]
        local = self._path("meta.json")
        return json.loads(local.read_text(encoding="utf-8")) if local.exists() else {"emoji_ids": self.emoji_ids, "owner_ids": []}

    async def save_owner_ids(self, owner_ids: set[int]) -> None:
        meta = await self.load_meta()
        meta["emoji_ids"] = self.emoji_ids
        meta["owner_ids"] = sorted(owner_ids)
        self._path("meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if self.enabled:
            async with self._lock:
                remote = await self._get_file("skx/meta.json")
                await self._put_file("skx/meta.json", meta, remote.get("sha") if remote else None)

    async def load_user(self, user_id: int) -> dict[str, Any]:
        name = f"skx/users/{user_id}.json"
        remote = await self._get_file(name) if self.enabled else None
        if remote:
            self._path(f"{user_id}.json").write_text(json.dumps(remote["value"], ensure_ascii=False, indent=2), encoding="utf-8")
            return remote["value"]
        local = self._path(f"{user_id}.json")
        if local.exists():
            return json.loads(local.read_text(encoding="utf-8"))
        return {"user_id": user_id, "posts": [], "destinations": [], "history": [], "created_at": None}

    async def save_user(self, user_id: int, data: dict[str, Any]) -> None:
        async with self._lock:
            name = f"skx/users/{user_id}.json"
            local = self._path(f"{user_id}.json")
            local.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            if self.enabled:
                remote = await self._get_file(name)
                await self._put_file(name, data, remote.get("sha") if remote else None)

    async def save_emojis(self, ids: list[str]) -> None:
        self.emoji_ids = list(dict.fromkeys(str(x) for x in ids if str(x).isdigit()))
        existing = await self.load_meta()
        meta = {"emoji_ids": self.emoji_ids, "owner_ids": existing.get("owner_ids", []), "version": 1}
        self._path("meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if self.enabled:
            async with self._lock:
                remote = await self._get_file("skx/meta.json")
                await self._put_file("skx/meta.json", meta, remote.get("sha") if remote else None)
