from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from urllib.parse import quote

from PySide6.QtCore import QTimer

from app.ai.base import ProductResult


@dataclass(frozen=True)
class SearchSite:
    name: str
    template: str
    language: str


SEARCH_SITES = (
    SearchSite("Google Shopping", "https://www.google.com/search?tbm=shop&q={q}", "en"),
    SearchSite("BigGo", "https://biggo.com.tw/s/?q={q}", "zh"),
    SearchSite("feebee 飛比", "https://feebee.com.tw/s/?q={q}", "zh"),
    SearchSite("momo", "https://www.momoshop.com.tw/search/searchShop.jsp?keyword={q}", "zh"),
    SearchSite("PChome 24h", "https://24h.pchome.com.tw/search/?q={q}", "zh"),
    SearchSite("Shopee 蝦皮", "https://shopee.tw/search?keyword={q}", "zh"),
    SearchSite("Ruten 露天", "https://www.ruten.com.tw/find/?q={q}", "zh"),
)


def build_search_urls(product: ProductResult) -> list[str]:
    urls = []
    for site in SEARCH_SITES:
        query = product.query_en if site.language == "en" else product.query_zh
        if not query:
            query = product.query_zh or product.query_en
        urls.append(site.template.format(q=quote(query, safe="")))
    return urls


def open_search_tabs(product: ProductResult, delay_ms: int = 150) -> int:
    """Open the seven configured searches with a short gap between browser tabs."""
    urls = build_search_urls(product)
    for index, url in enumerate(urls):
        QTimer.singleShot(index * delay_ms, lambda target=url: _open_tab(target))
    return len(urls)


def _open_tab(url: str) -> None:
    try:
        webbrowser.open_new_tab(url)
    except Exception:
        # The GUI reports the completed identification; browser errors should not crash it.
        pass
