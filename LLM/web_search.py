from typing import List, Dict, Any, Optional
try:
    # 新パッケージ名
    from ddgs import DDGS  # type: ignore
except Exception:
    # 後方互換
    from duckduckgo_search import DDGS  # type: ignore


def search_text(query: str, region: str = "jp-jp", max_results: int = 10, safesearch: str = "moderate", timelimit: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    DuckDuckGo 検索（テキスト）。
    - region: 'jp-jp' で日本向け
    - safesearch: off|moderate|strict
    - timelimit: None|'d'|'w'|'m'|'y'
    戻り値: [{title, href, body}]
    """
    with DDGS() as ddgs:
        try:
            # ddgs (new) signature: text(query, region=..., safesearch=..., timelimit=..., max_results=...)
            results = list(ddgs.text(
                query,
                region=region,
                safesearch=safesearch,
                timelimit=timelimit,
                max_results=max_results,
            ))
        except TypeError:
            # fallback for older duckduckgo_search: keywords=...
            results = list(ddgs.text(
                keywords=query,
                region=region,
                safesearch=safesearch,
                timelimit=timelimit,
                max_results=max_results,
            ))
    # 正規化
    out: List[Dict[str, Any]] = []
    for r in results:
        out.append({
            "title": r.get("title"),
            "url": r.get("href"),
            "snippet": r.get("body"),
            "source": "duckduckgo",
        })
    return out
