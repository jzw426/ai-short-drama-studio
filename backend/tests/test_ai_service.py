"""AI 服务失败语义：全部 provider 失败必须抛 AIUnavailableError，绝不返回假数据。"""
import pytest

from app.services.ai_service import AIUnavailableError, ai_service


@pytest.fixture
def no_provider(monkeypatch):
    async def _fail(*args, **kwargs):
        return None

    monkeypatch.setattr(ai_service, "_chat_completions", _fail)
    return ai_service


@pytest.mark.asyncio
async def test_script_raises_when_all_providers_fail(no_provider):
    with pytest.raises(AIUnavailableError):
        await no_provider.generate_script("写一个开场")


@pytest.mark.asyncio
async def test_character_raises_when_all_providers_fail(no_provider):
    with pytest.raises(AIUnavailableError):
        await no_provider.generate_character("一个冷酷的女总裁")


@pytest.mark.asyncio
async def test_storyboard_raises_when_all_providers_fail(no_provider):
    with pytest.raises(AIUnavailableError):
        await no_provider.generate_storyboard("咖啡厅 白天 男女主对峙")


@pytest.mark.asyncio
async def test_character_raises_on_garbage_json(no_provider, monkeypatch):
    async def _garbage(*args, **kwargs):
        return "这不是 JSON"

    monkeypatch.setattr(no_provider, "_chat_completions", _garbage)
    with pytest.raises(AIUnavailableError):
        await no_provider.generate_character("x")


@pytest.mark.asyncio
async def test_storyboard_raises_on_empty_list(no_provider, monkeypatch):
    async def _empty(*args, **kwargs):
        return '{"shots": []}'

    monkeypatch.setattr(no_provider, "_chat_completions", _empty)
    with pytest.raises(AIUnavailableError):
        await no_provider.generate_storyboard("x")
