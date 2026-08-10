from __future__ import annotations

import re

import aiohttp

from bot.models import OrderCard

# NOTE: Kwork projects page is JS-driven and can change markup frequently.
# This parser is a phase-2 placeholder and returns matches only if static links are present.
PROJECT_LINK_RE = re.compile(r'href="/projects/(\d+)"', re.IGNORECASE)


async def fetch_kwork_orders(url: str) -> list[OrderCard]:
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            html = await response.text()

    results: list[OrderCard] = []
    for project_id in set(PROJECT_LINK_RE.findall(html)):
        link = f"https://kwork.ru/projects/{project_id}"
        results.append(
            OrderCard(
                source="kwork",
                external_id=project_id,
                title=f"Kwork project #{project_id}",
                link=link,
                description="JS-driven listing placeholder",
                price="-",
            )
        )
    return results
