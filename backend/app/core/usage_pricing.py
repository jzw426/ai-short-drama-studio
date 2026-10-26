"""AI 调用价格表（估算用，非结算依据）。

**单价全部是占位值**：供应商报价尚未经商务确认，这里只给一个数量级，
用于在 /api/v1/ops/usage 里观察"成本趋势"与"哪个 operation 最烧钱"。
真实账单以供应商后台为准；确认价格后只改本文件，不动业务代码。

配置方式（优先级从高到低）：

1. 环境变量 `AI_USAGE_PRICING_JSON`：JSON 对象，键为 "provider/model"
   或 "provider/*"（通配该 provider 的所有模型），值同下面的 price dict。
   例：`'{"agnes/agnes-2.0-flash": {"input_per_1k_usd": 0.0004, "output_per_1k_usd": 0.0012}}'`
2. `DEFAULT_PRICING` 中按 (provider, model) 精确匹配。
3. `DEFAULT_PRICING` 中按 (provider, "*") 匹配。
4. `FALLBACK_PRICING`（全 0）——未知 provider/model 不臆造价格。

计费口径：
- 文本类（script/character/storyboard）按 token 计价：prompt/completion 分别乘输入/输出单价。
- 视频/图片类（video）供应商通常按次计价：响应没有 usage 时用 `per_call_usd`。
"""
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# 单位：美元 / 1K tokens（token 类）、美元 / 次（per_call_usd）。
# ⚠️ 占位值，待商务与供应商确认后替换。
DEFAULT_PRICING: dict = {
    # ---- 文本 ----
    ("agnes", "agnes-2.0-flash"): {
        "input_per_1k_usd": 0.0002,
        "output_per_1k_usd": 0.0006,
        "per_call_usd": 0.0,
    },
    ("deepseek", "deepseek-chat"): {
        "input_per_1k_usd": 0.00027,
        "output_per_1k_usd": 0.0011,
        "per_call_usd": 0.0,
    },
    ("gemini", "gemini-2.0-flash"): {
        "input_per_1k_usd": 0.0001,
        "output_per_1k_usd": 0.0004,
        "per_call_usd": 0.0,
    },
    # ---- 图片 ----
    ("agnes", "agnes-image-2.1-flash"): {
        "input_per_1k_usd": 0.0,
        "output_per_1k_usd": 0.0,
        "per_call_usd": 0.002,
    },
    ("hf", "black-forest-labs/FLUX.1-schnell"): {
        "input_per_1k_usd": 0.0,
        "output_per_1k_usd": 0.0,
        "per_call_usd": 0.002,
    },
    # ---- 视频（按次，价格量级差异最大，务必尽快确认）----
    ("agnes", "agnes-video-v2.0"): {
        "input_per_1k_usd": 0.0,
        "output_per_1k_usd": 0.0,
        "per_call_usd": 0.05,
    },
    ("kling", "kling-v1.6"): {
        "input_per_1k_usd": 0.0,
        "output_per_1k_usd": 0.0,
        "per_call_usd": 0.10,
    },
    ("seedance", "seedance"): {
        "input_per_1k_usd": 0.0,
        "output_per_1k_usd": 0.0,
        "per_call_usd": 0.08,
    },
    # ---- provider 通配兜底（模型升级/新增时至少不至于 0 成本）----
    ("agnes", "*"): {
        "input_per_1k_usd": 0.0002,
        "output_per_1k_usd": 0.0006,
        "per_call_usd": 0.01,
    },
}

FALLBACK_PRICING: dict = {
    "input_per_1k_usd": 0.0,
    "output_per_1k_usd": 0.0,
    "per_call_usd": 0.0,
}

PRICING_ENV_VAR = "AI_USAGE_PRICING_JSON"

# 最近一次成功解析的环境变量原文，避免每条记账都 json.loads
_env_cache: dict = {"raw": None, "parsed": {}}


def _env_overrides() -> dict:
    """环境变量里的价格覆盖表：{"provider/model": {...}} 或 {"provider/*": {...}}。"""
    raw = (os.environ.get(PRICING_ENV_VAR) or "").strip()
    if not raw:
        return {}
    if _env_cache["raw"] == raw:
        return _env_cache["parsed"]
    parsed: dict = {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            parsed = {str(k).strip(): v for k, v in data.items() if isinstance(v, dict)}
        else:
            logger.warning("%s 必须是 JSON 对象，已忽略（当前类型 %s）", PRICING_ENV_VAR, type(data).__name__)
    except (ValueError, TypeError) as exc:
        logger.warning("%s 解析失败，已忽略：%s", PRICING_ENV_VAR, exc)
        parsed = {}
    _env_cache["raw"] = raw
    _env_cache["parsed"] = parsed
    return parsed


def _normalize(price: Optional[dict]) -> dict:
    """缺字段补 0、转 float；非法值忽略（价格表配置错误不能拖垮业务）。"""
    result = dict(FALLBACK_PRICING)
    if not isinstance(price, dict):
        return result
    for key in result:
        try:
            value = price.get(key, result[key])
            result[key] = float(value or 0.0)
        except (TypeError, ValueError):
            logger.warning("价格表字段 %s 非法（%r），按 0 处理", key, price.get(key))
            result[key] = 0.0
    return result


def get_price(provider: str = "", model: str = "") -> dict:
    """取 (provider, model) 的单价；未知组合返回全 0，绝不臆造价格。"""
    provider = (provider or "").strip()
    model = (model or "").strip()
    if not provider and not model:
        return dict(FALLBACK_PRICING)

    overrides = _env_overrides()
    for key in (f"{provider}/{model}", f"{provider}/*", f"*/{model}", "*/*"):
        if key in overrides:
            return _normalize(overrides[key])

    exact = DEFAULT_PRICING.get((provider, model))
    if exact is not None:
        return _normalize(exact)
    return _normalize(DEFAULT_PRICING.get((provider, "*")))


def estimate_cost(
    provider: str = "",
    model: str = "",
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    operation: Optional[str] = None,
) -> float:
    """估算一次 AI 调用成本（美元，保留 6 位小数）。

    - 有 token 时：prompt_tokens/1000*输入单价 + completion_tokens/1000*输出单价。
    - 没有任何 token（图片/视频等按次计费）时：用 per_call_usd。
    """
    price = get_price(provider, model)
    try:
        prompt = max(0, int(prompt_tokens or 0))
    except (TypeError, ValueError):
        prompt = 0
    try:
        completion = max(0, int(completion_tokens or 0))
    except (TypeError, ValueError):
        completion = 0

    if prompt or completion:
        cost = (
            prompt / 1000.0 * price["input_per_1k_usd"]
            + completion / 1000.0 * price["output_per_1k_usd"]
        )
    else:
        cost = price["per_call_usd"]
    return round(float(cost), 6)
