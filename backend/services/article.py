"""抓取新闻原文：RSS 只给几十字摘要，正文和配图要回源站取。

只做「通用正文抽取」：定位常见正文容器 → 取 <p> 段落 → 取容器内第一张图。
失败不抛异常，返回 None，由调用方保留原摘要。
"""
from __future__ import annotations

import logging
import re
from html import unescape
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 正文容器候选（按优先级）
BODY_CLASS_HINTS = ("left_zw", "article-content", "article_content", "post-content",
                    "content_desc", "rich_media_content", "entry-content")
SKIP_TAGS = {"script", "style", "noscript", "iframe"}
VOID_TAGS = {"img", "br", "hr", "meta", "input", "link", "source", "area", "base", "col", "embed", "param", "track", "wbr"}
# 明显不是新闻配图的资源
BAD_IMAGE_RE = re.compile(r"(logo|icon|qr|avatar|emoji|blank|spacer|loading|default)", re.I)
OG_IMAGE_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.I)


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0            # 进入正文字容器后的嵌套深度
        self.in_body = False
        self.skip_depth = 0
        self.paragraphs: list[str] = []
        self.buffer: list[str] = []
        self.image: Optional[str] = None
        self._image_score = 0
        self.title: str = ""

    # --- 容器判断 ---
    @staticmethod
    def _is_body(tag: str, attrs: dict) -> bool:
        if tag != "div":
            return False
        klass = (attrs.get("class") or "") + " " + (attrs.get("id") or "")
        return any(hint in klass for hint in BODY_CLASS_HINTS)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        # 自闭合标签不参与层级计数，否则 depth 永远回不到 0
        if tag in VOID_TAGS:
            if self.in_body and tag == "img":
                self._consider_image(attrs)
            return

        if self.in_body:
            self.depth += 1
        elif self._is_body(tag, attrs):
            self.in_body = True
            self.depth = 1

        if tag in SKIP_TAGS:
            self.skip_depth += 1

        if self.in_body and tag == "p":
            self.buffer = []

    def handle_startendtag(self, tag, attrs):
        # <img ... /> 这类，只当图片候选，不影响层级
        if tag == "img" and self.in_body:
            self._consider_image(dict(attrs))

    def _consider_image(self, attrs: dict) -> None:
        src = attrs.get("src") or attrs.get("data-src") or ""
        if not src or src.startswith("data:") or BAD_IMAGE_RE.search(src):
            return
        try:
            width = int(str(attrs.get("width") or "0").replace("px", ""))
            height = int(str(attrs.get("height") or "0").replace("px", ""))
        except ValueError:
            width = height = 0
        if width and height and (width < 200 or height < 120):
            return
        score = width * height or 1
        if score >= self._image_score:
            self.image = src
            self._image_score = score

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1

        if tag in VOID_TAGS or not self.in_body:
            return

        if tag == "p":
            text = "".join(self.buffer).strip()
            if len(text) >= 12:
                self.paragraphs.append(text)
            self.buffer = []

        # 每个非自闭合标签都要减，否则层级会一直涨，正文容器永远关不掉
        self.depth -= 1
        if self.depth <= 0:
            self.in_body = False
            self.depth = 0

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.in_body and self.buffer is not None:
            self.buffer.append(data)

    def get_text(self) -> str:
        lines = []
        for text in self.paragraphs:
            cleaned = re.sub(r"[ \t\u3000]+", " ", text).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n\n".join(lines)


def _clean_image(url: str, base: str) -> Optional[str]:
    if not url:
        return None
    url = url.strip().split()[0] if url.strip() else ""
    if not url or BAD_IMAGE_RE.search(url) or "ghs.png" in url.lower():
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urljoin(base, url)
    return url


async def fetch_article(url: str, timeout: float = 10.0) -> Optional[dict]:
    """返回 {'content': 正文, 'image': 首图, 'charset': ...}；失败返回 None。"""
    if not url or not url.startswith("http"):
        return None

    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True,
                                     timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        logger.debug("抓正文失败 %s：%s", url, exc)
        return None

    parser = _ArticleParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.debug("解析正文失败 %s：%s", url, exc)
        return None

    content = unescape(parser.get_text()).strip()
    if len(content) < 150:
        return None

    # 优先 og:image（官方大图），但它常被站点写成默认占位图，校验不过就用正文图
    og = OG_IMAGE_RE.search(html)
    image = _clean_image(og.group(1), url) if og else None
    if not image:
        image = _clean_image(parser.image or "", url)

    return {
        "content": content[:20000],
        "image": image,
    }
