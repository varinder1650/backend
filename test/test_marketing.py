# backend/test/test_marketing.py
import pytest
from httpx import AsyncClient
from main import app


@pytest.mark.asyncio
async def test_get_marketing_banners_returns_list():
    """GET /marketing/banners returns a list (empty or populated)"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/marketing/banners")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_marketing_banners_only_active():
    """Each returned banner has is_active=True"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/marketing/banners")

    assert response.status_code == 200
    for banner in response.json():
        assert banner.get("is_active") is True
