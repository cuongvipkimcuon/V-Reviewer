# utils/web_search.py - Web search (Tavily / Google) for intent web_search
"""Tích hợp Tavily hoặc Google API cho tra cứu thời gian thực. Cấu hình API key trong secrets."""
from typing import List, Dict, Optional

def _get_tavily_key():
    """Lấy Tavily API key từ .streamlit/secrets.toml ([tavily] API_KEY) hoặc Streamlit Cloud secret TAVILY_API_KEY."""
    try:
        import streamlit as st
        key = ""
        # [tavily] API_KEY trong secrets.toml — Streamlit section có thể là dict hoặc object (SafeAttributeDict)
        section = st.secrets.get("tavily")
        if section is not None:
            key = getattr(section, "API_KEY", None)  # object-style (st.secrets.tavily.API_KEY)
            if key is None and hasattr(section, "get"):
                key = section.get("API_KEY", "")  # dict-style
            key = (key or "").strip()
        if not key:
            key = st.secrets.get("TAVILY_API_KEY", "") or ""
        return (key or "").strip()
    except Exception:
        return ""


def web_search_tavily(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Gọi Tavily Search API. Trả về list [{"title", "url", "content"}].
    Nếu không cấu hình API key hoặc lỗi -> trả về [].
    """
    api_key = _get_tavily_key()
    if not api_key or not query or not query.strip():
        return []
    try:
        import requests
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query.strip()[:500],
                "search_depth": "basic",
                "max_results": min(10, max_results),
                "include_answer": False,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            try:
                err_body = resp.text[:500] if resp.text else ""
                print(f"web_search_tavily API error: status={resp.status_code} body={err_body}")
            except Exception:
                print(f"web_search_tavily API error: status={resp.status_code}")
            return []
        data = resp.json()
        results = data.get("results") or []
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": (r.get("content") or "")[:2000],
            }
            for r in results[:max_results]
        ]
    except Exception as e:
        print(f"web_search_tavily error: {e}")
        return []


def web_search_google_custom(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Google Custom Search JSON API (cần API key + search engine id).
    secrets: google_search: { API_KEY, SEARCH_ENGINE_ID }
    """
    try:
        import streamlit as _st
        api_key = _st.secrets.get("google_search", {}).get("API_KEY", "") or _st.secrets.get("GOOGLE_SEARCH_API_KEY", "")
        cx = _st.secrets.get("google_search", {}).get("SEARCH_ENGINE_ID", "") or _st.secrets.get("GOOGLE_CX", "")
    except Exception:
        api_key = ""
        cx = ""
    if not api_key or not cx or not query or not query.strip():
        return []
    try:
        import requests
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": api_key,
            "cx": cx,
            "q": query.strip()[:500],
            "num": min(10, max_results),
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        items = data.get("items") or []
        return [
            {
                "title": i.get("title", ""),
                "url": i.get("link", ""),
                "content": (i.get("snippet") or "")[:2000],
            }
            for i in items[:max_results]
        ]
    except Exception as e:
        print(f"web_search_google_custom error: {e}")
        return []


def web_search(query: str, max_results: int = 5) -> str:
    """
    Thử Tavily trước, không có thì Google. Trả về chuỗi format để inject vào context.
    """
    results = web_search_tavily(query, max_results)
    if not results:
        try:
            results = web_search_google_custom(query, max_results)
        except Exception:
            pass
    if not results:
        return "[WEB SEARCH] Chưa cấu hình Tavily/Google API hoặc không có kết quả. Trả lời dựa trên kiến thức có sẵn nếu có thể."
    lines = ["[WEB SEARCH - Kết quả tra cứu thời gian thực]"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        content = (r.get("content") or "").strip()
        lines.append(f"{i}. {title}\n   URL: {url}\n   {content[:1500]}")
    return "\n\n".join(lines)
