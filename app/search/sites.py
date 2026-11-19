from __future__ import annotations

import webbrowser
from urllib.parse import quote

from PySide6.QtCore import QTimer

from app.ai.base import ProductResult
from app.config import SearchConfig


def build_search_urls(product: ProductResult, config: SearchConfig | None = None) -> list[str]:
    config = config or SearchConfig()
    urls = []
    for site in config.sites:
        if not site.enabled or "{q}" not in site.url_template:
            continue
        query = product.query_en if site.query_field == "en" else product.query_zh
        if not query:
            query = product.query_zh or product.query_en
        if config.secondhand_mode and site.id in {"shopee", "ruten"}:
            query = f"{query} 二手"
        try:
            urls.append(site.url_template.format(q=quote(query, safe="")))
        except (KeyError, ValueError):
            continue
    return urls


def open_search_tabs(
    product: ProductResult,
    config: SearchConfig | None = None,
    delay_ms: int = 150,
) -> int:
    """Open enabled search pages with a short gap between browser tabs."""
    urls = build_search_urls(product, config)
    for index, url in enumerate(urls):
        QTimer.singleShot(index * delay_ms, lambda target=url: _open_tab(target))
    return len(urls)


def _open_tab(url: str) -> None:
    try:
        webbrowser.open_new_tab(url)
    except Exception:
        # The GUI reports the completed identification; browser errors should not crash it.
        pass
