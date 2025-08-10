from web_search import search_text

if __name__ == "__main__":
    query = "吉沢亮 国宝 映画 site:.jp"
    hits = search_text(query, region="jp-jp", max_results=8, safesearch="moderate")
    for i, h in enumerate(hits, 1):
        title = (h.get("title") or "").strip()
        url = (h.get("url") or "").strip()
        snippet = (h.get("snippet") or "").strip()
        print(f"{i}. {title} :: {url} :: {snippet}")
