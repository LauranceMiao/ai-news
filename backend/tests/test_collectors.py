"""采集器纯函数测试（不联网、不写库）。"""
from services import collectors


def test_guess_category_rules():
    assert collectors.guess_category("曝iPhone20按键将调整") == 7      # 科技
    assert collectors.guess_category("东契奇后场压哨三分") == 6        # 体育
    assert collectors.guess_category("巴拉圭前总统在家中被逮捕") == 4   # 国际
    assert collectors.guess_category("某地发生火灾事故") == 2           # 社会
    assert collectors.guess_category("一部新电影票房破亿") == 5         # 娱乐
    assert collectors.guess_category("今天发生了什么") == 1            # 默认头条


def test_guess_category_uses_default_when_no_keyword():
    assert collectors.guess_category("随便一段标题", default=3) == 3


def test_html_to_text_strips_tags_and_unescapes():
    raw = "<p>第一段&nbsp;内容</p><p>第二段<br/>内容</p>"
    text = collectors.html_to_text(raw)
    assert "<p>" not in text
    assert "第一段" in text
    assert "第二段" in text


def test_parse_published_falls_back_to_now():
    from datetime import datetime
    value = collectors.parse_published({})
    assert isinstance(value, datetime)


def test_extract_image_from_html():
    html = '<div><img src="https://example.com/a.jpg"/></div>'
    assert collectors.extract_image({}, html) == "https://example.com/a.jpg"
    assert collectors.extract_image({}, "") is None
