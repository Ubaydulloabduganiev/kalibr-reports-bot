from __future__ import annotations

import asyncio
import weakref
from datetime import UTC, datetime
from typing import Any

import httpx
from aiolimiter import AsyncLimiter
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.core.config import settings
from app.schemas import DealMatch


class AmoCRMError(RuntimeError):
    pass


class AmoCRMClient:
    def __init__(self) -> None:
        self._limiters: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

    def _limiter(self) -> AsyncLimiter:
        loop = asyncio.get_running_loop()
        limiter = self._limiters.get(loop)
        if limiter is None:
            limiter = AsyncLimiter(6, 1)
            self._limiters[loop] = limiter
        return limiter

    @property
    def configured(self) -> bool:
        return bool(settings.amocrm_access_token and settings.amocrm_base_url)

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, AmoCRMError)),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.configured:
            raise AmoCRMError("amoCRM is not configured")
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {settings.amocrm_access_token}"
        headers["Content-Type"] = "application/json"
        async with self._limiter():
            async with httpx.AsyncClient(base_url=settings.amocrm_base_url, timeout=30) as client:
                response = await client.request(method, path, headers=headers, **kwargs)
        if response.status_code == 429 or response.status_code >= 500:
            retry_after = int(response.headers.get("Retry-After", "1"))
            await asyncio.sleep(min(retry_after, 30))
            raise AmoCRMError(f"Temporary amoCRM error {response.status_code}: {response.text[:500]}")
        if response.status_code >= 400:
            raise AmoCRMError(f"amoCRM error {response.status_code}: {response.text[:1000]}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def create_report_lead(
        self,
        *,
        name: str,
        responsible_user_id: int | None,
        critical: bool,
        tags: list[str],
        custom_fields_values: list[dict[str, Any]] | None = None,
    ) -> int:
        payload: dict[str, Any] = {"name": name, "_embedded": {"tags": [{"name": tag} for tag in tags]}}
        if settings.amocrm_pipeline_id:
            payload["pipeline_id"] = settings.amocrm_pipeline_id
        stage_id = settings.amocrm_critical_stage_id if critical else settings.amocrm_new_stage_id
        if stage_id:
            payload["status_id"] = stage_id
        if responsible_user_id:
            payload["responsible_user_id"] = responsible_user_id
        if custom_fields_values:
            payload["custom_fields_values"] = custom_fields_values
        data = await self.request("POST", "/api/v4/leads", json=[payload])
        return int(data["_embedded"]["leads"][0]["id"])

    async def add_lead_note(self, lead_id: int, text: str) -> int:
        data = await self.request(
            "POST",
            f"/api/v4/leads/{lead_id}/notes",
            json=[{"note_type": "common", "params": {"text": text}}],
        )
        return int(data["_embedded"]["notes"][0]["id"])

    async def create_task(
        self,
        *,
        entity_id: int,
        responsible_user_id: int | None,
        text: str,
        complete_till: datetime,
    ) -> int:
        item: dict[str, Any] = {
            "entity_id": entity_id,
            "entity_type": "leads",
            "task_type_id": 1,
            "text": text,
            "complete_till": int(complete_till.astimezone(UTC).timestamp()),
        }
        if responsible_user_id:
            item["responsible_user_id"] = responsible_user_id
        data = await self.request("POST", "/api/v4/tasks", json=[item])
        return int(data["_embedded"]["tasks"][0]["id"])

    async def find_leads(self, query: str, limit: int = 10) -> list[DealMatch]:
        data = await self.request("GET", "/api/v4/leads", params={"query": query, "limit": limit})
        leads = (data or {}).get("_embedded", {}).get("leads", [])
        return [
            DealMatch(
                id=item["id"],
                name=item.get("name") or f"Lead {item['id']}",
                responsible_user_id=item.get("responsible_user_id"),
                price=item.get("price"),
                status_id=item.get("status_id"),
            )
            for item in leads
        ]

    async def mark_resolved(self, lead_id: int) -> None:
        if not settings.amocrm_resolved_stage_id:
            return
        await self.request("PATCH", "/api/v4/leads", json=[{"id": lead_id, "status_id": settings.amocrm_resolved_stage_id}])


amocrm_client = AmoCRMClient()
