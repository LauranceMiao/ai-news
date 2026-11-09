"""RAG 切分与 Prompt 组装的单元测试（不依赖数据库与模型）。"""
from services import rag


def test_split_short_text_returns_single_chunk():
    chunks = rag.split_text("今天天气不错。")
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].text == "今天天气不错。"


def test_split_long_text_covers_content_and_respects_size():
    text = "。".join(["这是第%d条测试新闻内容，用于验证切分逻辑是否稳定可靠" % i for i in range(40)]) + "。"
    chunks = rag.split_text(text, size=200, overlap=40)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= 200
        assert chunk.index >= 0
    # 相邻切片有重叠，保证语义连续
    assert chunks[0].end > chunks[1].start
    # 首尾内容都被覆盖
    assert chunks[0].start == 0
    assert chunks[-1].end >= len(text) - 1


def test_split_empty_text_returns_no_chunks():
    assert rag.split_text("") == []


def test_build_context_numbers_sources():
    hits = [
        {"newsId": 1, "title": "标题一", "content": "内容一"},
        {"newsId": 2, "title": "标题二", "content": "内容二"},
    ]
    context = rag.build_context(hits)
    assert "[1] 《标题一》" in context
    assert "[2] 《标题二》" in context


def test_build_messages_keeps_history_and_context():
    hits = [{"newsId": 1, "title": "标题一", "content": "内容一"}]
    history = [{"role": "user", "content": "上一个问题"},
               {"role": "assistant", "content": "上一个回答"}]
    messages = rag.build_messages("测试问题", hits, history)
    assert messages[0]["role"] == "system"
    assert any("[1] 《标题一》" in m["content"] for m in messages)
    assert messages[-1]["content"].endswith("测试问题")
    assert len(messages) == 4
