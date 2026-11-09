"""LLM 路由、Token 估算与成本计算的单元测试（不发真实请求）。"""
from services.llm_client import DeepSeekClient, estimate_tokens, llm_client


def test_model_routing():
    client = DeepSeekClient()
    assert client.model_for("chat") == client.model_for("summary")
    assert client.model_for("digest") != client.model_for("chat")
    assert client.model_for("unknown") == client.model_for("chat")


def test_estimate_tokens_positive():
    assert estimate_tokens("") == 0
    assert estimate_tokens("你好世界") > 0
    assert estimate_tokens("hello world") > 0


def test_cost_uses_price_table():
    client = llm_client
    fast = client.build_usage(client.model_for("chat"), 1_000_000, 1_000_000)
    pro = client.build_usage(client.model_for("digest"), 1_000_000, 1_000_000)
    assert fast.cost > 0
    assert pro.cost > fast.cost
    assert fast.total_tokens == 2_000_000
    assert fast.to_dict()["totalTokens"] == 2_000_000


def test_usage_dict_shape():
    data = llm_client.build_usage("deepseek-flash", 10, 20).to_dict()
    for key in ("promptTokens", "completionTokens", "totalTokens", "model", "cost"):
        assert key in data
