import os
from datetime import datetime
import json
import re
import asyncio
import httpx
import sqlite3
from typing import Any, Dict, List, Optional, Callable
from urllib.parse import urlparse

from character_manager import CharacterManager
from llm_factory import LLMFactory
from llm_instance_manager import LLMInstanceManager
from log_manager import write_operation_log
from readiness_checker import ensure_ollama_model_ready_sync
from web_search import search_text

# KB ingestion
import sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KB_DIR = os.path.join(BASE_DIR, "..", "KB")
if KB_DIR not in sys.path:
    sys.path.append(KB_DIR)
try:
    from ingest import ingest_payload  # type: ignore
except Exception:
    ingest_payload = None  # type: ignore


def ensure_dirs():
    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "..", "logs"), exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "..", "logs", "person"), exist_ok=True)


def build_extractor_prompt(domain: str) -> str:
    template = """あなたは事実収集アシスタントです。以下の対象ドメインに限定し、確度の高い事実のみを抽出します。
対象ドメイン: {DOMAIN}

厳格な出力規則（絶対遵守）:
- 出力は JSON オブジェクト 1個のみ。前置き・後置き・説明文・見出し・箇条書き・Markdown（``` 等）一切禁止。
- 最初に必ず <<<JSON_START>>> を出力し、最後に <<<JSON_END>>> を出力。JSONはその間のみ。
- 未確定情報は入れない。わからない項目は null または空配列。
- 許可キーのみ使用: persons, works, credits, external_ids, unified, note, next_queries
- credits.role は次のみ: actor, voice, director, author, screenplay, composer, theme_song, sound_effects, producer
- 文字列は過剰な修飾語を避け、短く正確に。
- next_queries は日本語の短い検索語を最大5件。重複不可。

スキーマ:
{{
  "persons": [ {{ "name": "", "aliases": [""] }} ],
  "works": [ {{ "title": "", "category": "映画", "year": 2024, "subtype": null, "summary": null }} ],
  "credits": [ {{ "work": "", "person": "", "role": "actor", "character": null }} ],
  "external_ids": [ {{ "entity": "work", "name": "", "source": "eiga.com", "value": "", "url": null }} ],
  "unified": [ {{ "name": "", "work": "", "relation": "adaptation" }} ],
  "note": null,
  "next_queries": [ "" ]
}}

出力テンプレート（例、構造イメージのみ）:
<<<JSON_START>>>
{{
  "persons": [],
  "works": [],
  "credits": [],
  "external_ids": [],
  "unified": [],
  "note": null,
  "next_queries": []
}}
<<<JSON_END>>>
"""
    return template.replace("{DOMAIN}", str(domain))

def build_repair_prompt(domain: str) -> str:
    return (
        "以下の入力テキストを、指定スキーマに合致する有効なJSONに修復してください。\n"
        "- 前置き・説明・Markdown禁止。<<<JSON_START>>> と <<<JSON_END>>> で囲み、JSONのみ出力。\n"
        "- 許可キーのみ: persons, works, credits, external_ids, unified, note, next_queries\n"
        "- credits.role は actor, voice, director, author, screenplay, composer, theme_song, sound_effects, producer のみ\n"
        "- わからない値は null または空配列。対象ドメイン: " + str(domain)
    )

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    def _try_parse_relaxed(src: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(src)
        except Exception:
            pass
        # trailing comma を緩和（",}\n" → "}\n", ",]\n" → "]\n"）
        try:
            trimmed = re.sub(r",\s*([}\]])", r"\1", src)
            return json.loads(trimmed)
        except Exception:
            return None
    if not text:
        return None
    s = text.strip()
    # まずはマーカー優先
    start_tag = "<<<JSON_START>>>"
    end_tag = "<<<JSON_END>>>"
    if start_tag in s and end_tag in s:
        try:
            frag = s.split(start_tag, 1)[1].split(end_tag, 1)[0]
            parsed = _try_parse_relaxed(frag)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    # 次に、コードフェンス ```json ... ``` / ``` ... ``` を検出して中身をJSONとして解釈
    try:
        code_blocks = re.findall(r"```(?:json|JSON)?\s*([\s\S]*?)```", s)
        for block in code_blocks:
            candidate = block.strip()
            # フェンス内の先頭/末尾に余計な行があれば緩やかに除去
            # 先頭付近の説明行を1-2行だけ落として試す
            variants = [candidate]
            lines = candidate.splitlines()
            if len(lines) >= 2:
                variants.append("\n".join(lines[1:]).strip())
            if len(lines) >= 3:
                variants.append("\n".join(lines[2:]).strip())
            for v in variants:
                parsed = _try_parse_relaxed(v)
                if isinstance(parsed, dict):
                    return parsed
                # フェンス内から最外括弧抽出を試す
                m1b = v.find("{")
                m2b = v.rfind("}")
                if m1b != -1 and m2b != -1 and m2b > m1b:
                    inner = v[m1b:m2b+1]
                    parsed2 = _try_parse_relaxed(inner)
                    if isinstance(parsed2, dict):
                        return parsed2
    except Exception:
        pass
    # 最初の { から最後の } までを抜く簡易抽出
    m1 = s.find("{")
    m2 = s.rfind("}")
    if m1 == -1 or m2 == -1 or m2 <= m1:
        return None
    frag = s[m1 : m2 + 1]
    parsed = _try_parse_relaxed(frag)
    if isinstance(parsed, dict):
        return parsed
    # フォールバック: 何も解析できない
    return None


def sanitize_query(query: str) -> str:
    """検索クエリからメタ指示や余計な句点以降を除去し、端的な語に整える。
    例: "吉沢亮 国宝 映画。JSONのみで出力、前置き禁止。」" → "吉沢亮 国宝 映画"
    """
    if not query:
        return ""
    q = str(query)
    # 句点以降を落とす（説明やメタが続きがちなため）
    if "。" in q:
        q = q.split("。", 1)[0]
    # よく混入するメタ表現を除去
    bad_frags = [
        "JSON", "json", "出力", "前置き", "禁止", "マークダウン", "Markdown",
        "コード", "フェンス", "<<<JSON_START>>>", "<<<JSON_END>>>"
    ]
    for b in bad_frags:
        q = q.replace(b, "")
    # 末尾の全角/半角引用符や記号をトリム
    q = q.strip().strip('\"\'”’』」】)').strip('「『（(“')
    # 連続空白を単一化
    q = re.sub(r"\s+", " ", q).strip()
    return q


# ---- 検索/ヒント強化用ユーティリティ ----
MAX_RESULTS_PER_QUERY = 12  # 1クエリあたり取得件数（従来: 8）
MAX_HITS_TOTAL = 8          # まとめて採用する最大件数（従来: 8）
MAX_DEEP_FETCH = 6          # 精読する最大件数
FETCH_TIMEOUT_SEC = 8.0
FETCH_BYTES_LIMIT = 100000  # 過大ページの取り過ぎ防止（詳細抽出向けに拡大）

ROLE_KEYWORDS = {
    "監督": "director",
    "主演": "actor",
    "出演": "actor",
    "キャスト": "actor",
    "声優": "voice",
    "脚本": "screenplay",
    "原作": "author",
    "音楽": "composer",
}

# 役割語プリフィックス（先頭に付いていたら除去/除外対象）
ROLE_PREFIXES = [
    "出演", "主演", "監督", "脚本", "原作", "音楽", "声優", "主題歌", "音響効果", "プロデューサー",
]

# ステータス系プリフィックス（作品名の前に付く見出し語）
STATUS_PREFIXES = [
    "上映中", "配信中",
]

def _remove_role_prefix(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return s
    for pref in ROLE_PREFIXES:
        # パターン: 先頭が 役割語 [：:・\s] のいずれかで続く
        if re.match(rf"^{re.escape(pref)}[：:・\s]", s):
            s = re.sub(rf"^{re.escape(pref)}[：:・\s]+", "", s, count=1).strip()
            break
        # 役割語のみ
        if s == pref:
            return ""
    return s

def _is_pure_role_word(text: str) -> bool:
    t = str(text or "").strip()
    return t in ROLE_PREFIXES

def _remove_status_prefix(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return s
    changed = True
    while changed:
        changed = False
        for pref in STATUS_PREFIXES:
            if re.match(rf"^{re.escape(pref)}[：:・\s]", s):
                s = re.sub(rf"^{re.escape(pref)}[：:・\s]+", "", s, count=1).strip()
                changed = True
    return s

def _clean_title_token(text: str) -> str:
    # ステータス → 役割 の順に除去
    s = _remove_status_prefix(text)
    s = _remove_role_prefix(s)
    return s.strip()

def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for it in items or []:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out

def extract_candidates_from_text(title: str, snippet: str) -> Dict[str, List[str]]:
    """ヒットのタイトル/スニペットから簡易に候補を抽出。
    - 作品候補: 「」「」/『』内の文字列
    - 年候補: 19xx/20xx（"年" を含む形も許容）
    - 役割候補: ROLE_KEYWORDS にマッチする日本語語句
    - 人物候補: '○○が主演' / '監督：○○' などの単純パターンから抽出（過剰抽出は許容し、後段で正規化）
    """
    persons: List[str] = []
    works: List[str] = []
    years: List[str] = []
    roles: List[str] = []

    text = f"{title} {snippet}"
    # 作品名候補（日本語引用符）
    for m in re.findall(r"[「『]([^「『」』]{1,40})[」』]", text):
        s = sanitize_query(m)
        if s and s not in works:
            works.append(s)
    # 年候補
    for m in re.findall(r"((?:19|20)\d{2})\s*年?", text):
        if m not in years:
            years.append(m)
    # 役割候補
    for jp, role in ROLE_KEYWORDS.items():
        if jp in text and role not in roles:
            roles.append(role)
    # 人物候補（緩い抽出）
    # パターン1: 「Xが主演」「X主演」
    for m in re.findall(r"([\u4E00-\u9FFFぁ-んァ-ンA-Za-z0-9]{1,15})が主演", text):
        s = sanitize_query(m)
        if s and s not in persons:
            persons.append(s)
    for m in re.findall(r"([\u4E00-\u9FFFぁ-んァ-ンA-Za-z0-9]{1,15})主演", text):
        s = sanitize_query(m)
        if s and s not in persons:
            persons.append(s)
    # パターン2: 「監督：X」「監督 X」
    for m in re.findall(r"監督[：: ]([\u4E00-\u9FFFぁ-んァ-ンA-Za-z0-9]{1,20})", text):
        s = sanitize_query(m)
        if s and s not in persons:
            persons.append(s)
    return {"persons": persons, "works": works, "years": years, "roles": roles}

def _split_names(s: str) -> List[str]:
    # 日本語の区切り（、，・/／ と空白）で分割
    parts = re.split(r"[、，・/／\s]+", s)
    return [sanitize_query(p) for p in parts if sanitize_query(p)]

def extract_credit_candidates(title: str, snippet: str, works: List[str], years: List[str]) -> List[Dict[str, str]]:
    """タイトル/スニペットから (person, role, work?, year?) の候補を抽出。
    過剰抽出を許容し、後段の正規化/LLMでの確定に委ねる。
    """
    text = f"{title} {snippet}"
    credits: List[Dict[str, str]] = []
    work0 = works[0] if works else ""
    year0 = years[0] if years else ""

    # 監督：X / 監督 X
    for m in re.findall(r"監督[：:\s]([\u4E00-\u9FFFぁ-んァ-ンA-Za-z0-9・ー\s]{1,30})", text):
        for name in _split_names(m):
            credits.append({"person": name, "role": "director", "work": work0, "year": year0})
    # 脚本 / 原作 / 音楽
    for jp, role in (("脚本", "screenplay"), ("原作", "author"), ("音楽", "composer")):
        for m in re.findall(fr"{jp}[：:\s]([\u4E00-\u9FFFぁ-んァ-ンA-Za-z0-9・ー\s]{1,30})", text):
            for name in _split_names(m):
                credits.append({"person": name, "role": role, "work": work0, "year": year0})
    # 出演：A、B、C / キャスト：...
    for kw in ("出演", "キャスト", "声優", "声の出演"):
        for m in re.findall(fr"{kw}[：:\s]([\u4E00-\u9FFFぁ-んァ-ンA-Za-z0-9・ー\s]{1,60})", text):
            for name in _split_names(m):
                role = "voice" if "声" in kw else "actor"
                credits.append({"person": name, "role": role, "work": work0, "year": year0})
    # Xが主演 / X主演
    for m in re.findall(r"([\u4E00-\u9FFFぁ-んァ-ンA-Za-z0-9・ー]{1,20})が主演", text):
        name = sanitize_query(m)
        if name:
            credits.append({"person": name, "role": "actor", "work": work0, "year": year0})
    for m in re.findall(r"主演([\u4E00-\u9FFFぁ-んァ-ンA-Za-z0-9・ー]{1,20})", text):
        name = sanitize_query(m)
        if name:
            credits.append({"person": name, "role": "actor", "work": work0, "year": year0})

    # 去重
    seen = set()
    uniq: List[Dict[str, str]] = []
    for c in credits:
        key = (c["person"], c["role"], c.get("work", ""))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq

def build_structured_hints(hits: List[Dict[str, Any]]) -> str:
    """ヒット一覧から構造化ヒントを生成。候補語を去重し適量に整える。"""
    all_persons: List[str] = []
    all_works: List[str] = []
    all_years: List[str] = []
    all_roles: List[str] = []
    for h in hits:
        title = str(h.get("title") or "")
        snippet = str(h.get("snippet") or "")
        c = extract_candidates_from_text(title, snippet)
        for k, acc, limit in (
            ("persons", all_persons, 20),
            ("works", all_works, 20),
            ("years", all_years, 20),
            ("roles", all_roles, 10),
        ):
            for v in c.get(k, []):
                if v and v not in acc:
                    acc.append(v)
                if len(acc) >= limit:
                    break
    lines: List[str] = []
    if all_persons:
        lines.append("- 人物候補: " + ", ".join(all_persons[:20]))
    if all_works:
        lines.append("- 作品候補: " + ", ".join(all_works[:20]))
    if all_years:
        lines.append("- 年候補: " + ", ".join(all_years[:20]))
    if all_roles:
        lines.append("- 役割候補: " + ", ".join(all_roles[:10]))
    return "\n".join(lines)


def _clean_title_token(token: str) -> str:
    s = str(token or "").strip()
    # 役割語/状態ラベル（上映中/配信中/出演 等）を先頭から削除
    s = re.sub(r"^(上映中|配信中)\s+", "", s)
    s = _remove_role_prefix(s)
    # 余計な空白の正規化
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out

def _strip_html(html: str) -> str:
    s = html
    # 取り回し簡易のため、ごく簡単にタグ除去
    s = re.sub(r"<script[\s\S]*?</script>", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.IGNORECASE)
    s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    s = re.sub(r"</p>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\u00A0", " ", s)  # nbsp
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _jp_text_score(s: str) -> int:
    """日本語テキストらしさの簡易スコア。ひらがな/カタカナ/漢字の数を加点。"""
    score = 0
    for ch in s or "":
        o = ord(ch)
        if (0x3040 <= o <= 0x309F) or (0x30A0 <= o <= 0x30FF) or (0x4E00 <= o <= 0x9FFF):
            score += 1
    return score


def _extract_long_paragraph_from_html(html: str) -> Optional[str]:
    """<p>～</p> から本文っぽい長文段落を抽出（日本語スコアと長さで選択）。"""
    try:
        paras = re.findall(r"<p[^>]*>([\s\S]*?)</p>", html, re.IGNORECASE)
        best: Optional[str] = None
        best_score = -1
        for inner in paras:
            txt = _strip_html(inner)
            if len(txt) < 60 or "。" not in txt:
                continue
            score = _jp_text_score(txt) + len(txt) // 10
            if score > best_score:
                best_score = score
                best = txt.strip()
        return best
    except Exception:
        return None


def _extract_bio_from_text(text: str) -> Optional[str]:
    """句点で区切って、年表/作品名が並ぶ略歴らしい文を組み立てる。
    条件: 全体長>=120, 年/括弧年表(（11）等)が2箇所以上含まれる。
    """
    try:
        s = (text or "").strip()
        # 連続空白を圧縮
        s = re.sub(r"\s+", " ", s)
        # 文に分割（句点保持）
        parts = re.split(r"(。)", s)
        # parts は [文, '。', 文, '。', ...]
        sentences: List[str] = []
        i = 0
        while i < len(parts):
            seg = parts[i].strip()
            if i + 1 < len(parts) and parts[i+1] == "。":
                seg = (seg + "。").strip()
                i += 2
            else:
                i += 1
            if seg:
                sentences.append(seg)
        # 先頭から順に、年パターンを十分含む塊を見つける
        buf: List[str] = []
        count_year = 0
        for sent in sentences[:40]:  # 上位40文以内で探す
            buf.append(sent)
            # 年: 19xx/20xx または （11）等の括弧年
            count_year += len(re.findall(r"(?:19|20)\d{2}", sent))
            count_year += len(re.findall(r"（\d{2}）", sent))
            joined = "".join(buf)
            if len(joined) >= 120 and count_year >= 2:
                return joined[:1200].strip()
        # 見つからなければ先頭から長めの文を返す
        joined = "".join(sentences[:8])
        return joined[:400].strip() if joined else None
    except Exception:
        return None


def _jp_text_score(s: str) -> int:
    """日本語のひらがな/カタカナ/漢字の出現数でスコアリング。高いほど日本語として妥当。"""
    score = 0
    for ch in s:
        o = ord(ch)
        if (0x3040 <= o <= 0x309F) or (0x30A0 <= o <= 0x30FF) or (0x4E00 <= o <= 0x9FFF):
            score += 1
    return score


async def _fetch_text(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (IngestBot/1.0)"}
    async with httpx.AsyncClient(follow_redirects=True, timeout=FETCH_TIMEOUT_SEC, headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        # eiga.com は UTF-8 固定でデコード（誤判定時の文字化けを防止）
        try:
            host = urlparse(url).netloc.lower()
        except Exception:
            host = ""
        if "eiga.com" in host:
            content = r.content.decode("utf-8", errors="ignore")
        else:
            # httpx の推定に委ねる
            content = r.text
        if len(content) > FETCH_BYTES_LIMIT:
            content = content[:FETCH_BYTES_LIMIT]
        return content


def _extract_meta_title(html: str) -> str:
    m = re.search(r"<meta[^>]*property=\"og:title\"[^>]*content=\"([^\"]+)\"", html, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
    return m2.group(1).strip() if m2 else ""


def _iter_json_ld(html: str) -> List[Dict[str, Any]]:
    """<script type="application/ld+json"> ... を列挙してJSONを返す（壊れに強く）。"""
    objs: List[Dict[str, Any]] = []
    try:
        blocks = re.findall(r"<script[^>]*type=\"application/ld\+json\"[^>]*>([\s\S]*?)</script>", html, re.IGNORECASE)
        for b in blocks:
            txt = b.strip()
            # JSONの前後にHTMLコメントや余計なテキストが混ざる場合があるので緩く整形
            try:
                data = json.loads(txt)
            except Exception:
                try:
                    # 最初の { から最後の } まで
                    i1, i2 = txt.find('{'), txt.rfind('}')
                    if i1 != -1 and i2 != -1 and i2 > i1:
                        data = json.loads(txt[i1:i2+1])
                    else:
                        continue
                except Exception:
                    continue
            # data が配列や@graphを含む場合をフラット化
            def _flatten(x: Any):
                if isinstance(x, list):
                    for it in x:
                        _flatten(it)
                elif isinstance(x, dict):
                    if '@graph' in x and isinstance(x['@graph'], list):
                        for it in x['@graph']:
                            _flatten(it)
                    else:
                        objs.append(x)
            _flatten(data)
    except Exception:
        pass
    return objs


def deep_extract_from_page(url: str, html: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"director": [], "actor": [], "voice": [], "screenplay": [], "author": [], "composer": [], "year": [], "work": [], "synopsis": "", "title": "", "cast_pairs": []}
    meta_title = _extract_meta_title(html)
    if meta_title:
        wt = sanitize_query(meta_title)
        if wt:
            result["work"].append(wt)
            if not result.get("title"):
                result["title"] = wt
    text = _strip_html(html)
    # JSON-LD優先（Movieがあれば信頼）
    try:
        for obj in _iter_json_ld(html):
            ty = obj.get("@type")
            # @type が配列のこともある
            types = [ty] if isinstance(ty, str) else (ty or [])
            if (isinstance(types, list) and ("Movie" in types)) or ty == "Movie":
                name = (obj.get("name") or obj.get("headline") or "").strip()
                if name:
                    result["title"] = result["title"] or name
                    if name not in result["work"]:
                        result["work"].append(name)
                # 年/公開日
                for k in ("datePublished", "releaseDate"):
                    v = str(obj.get(k) or "")
                    m = re.search(r"(19|20)\d{2}", v)
                    if m and m.group(0) not in result["year"]:
                        result["year"].append(m.group(0))
                # あらすじ
                desc = (obj.get("description") or "").strip()
                if desc and (len(desc) > len(result.get("synopsis") or "")):
                    result["synopsis"] = desc
                # スタッフ/キャスト
                def _collect_people(field: str, key: str):
                    val = obj.get(field)
                    if not val:
                        return
                    items = val if isinstance(val, list) else [val]
                    for it in items:
                        if isinstance(it, dict):
                            nm = (it.get("name") or it.get("title") or "").strip()
                        else:
                            nm = str(it).strip()
                        if nm and nm not in result[key]:
                            result[key].append(nm)
                _collect_people("actor", "actor")
                _collect_people("director", "director")
                _collect_people("author", "author")
                _collect_people("creator", "author")
                _collect_people("musicBy", "composer")
    except Exception:
        pass
    # 年
    for y in re.findall(r"((?:19|20)\d{2})\s*年", text):
        if y not in result["year"]:
            result["year"].append(y)
    # 役割ごとに抽出
    def _add_names(after: str, role_key: str):
        # 区切り: 、,，,/／・ など
        parts = re.split(r"[、,，/／・\s]+", after)
        for p in parts:
            n = sanitize_query(p)
            if n and n not in result[role_key] and len(n) <= 30:
                result[role_key].append(n)
    # 監督
    for m in re.findall(r"監督[：: ]([^。\n]+)", text):
        _add_names(m, "director")
    # 脚本
    for m in re.findall(r"脚本[：: ]([^。\n]+)", text):
        _add_names(m, "screenplay")
    # 原作
    for m in re.findall(r"原作[：: ]([^。\n]+)", text):
        _add_names(m, "author")
    # 音楽
    for m in re.findall(r"音楽[：: ]([^。\n]+)", text):
        _add_names(m, "composer")
    # 出演/キャスト/主演
    for m in re.findall(r"(?:出演|キャスト|主演)[：: ]([^。\n]+)", text):
        _add_names(m, "actor")
    # "Xが主演" の緩い形も追加
    for m in re.findall(r"([\u4E00-\u9FFFぁ-んァ-ンA-Za-z0-9・]{1,20})が主演", text):
        n = sanitize_query(m)
        if n and n not in result["actor"]:
            result["actor"].append(n)
    # og:description を synopsis として補完
    try:
        mdesc = re.search(r"<meta[^>]*name=\"description\"[^>]*content=\"([^\"]*)\"", html, re.IGNORECASE)
        if mdesc:
            d = mdesc.group(1).strip()
            if d and len(d) > len(result.get("synopsis") or ""):
                result["synopsis"] = d
    except Exception:
        pass
    # personリンクを cast_pairs として収集（/person/NNNN/ の aタグテキスト）
    try:
        for a, href in re.findall(r"<a[^>]*href=\"(/person/\d+/)\"[^>]*>([\s\S]*?)</a>", html, re.IGNORECASE):
            name = sanitize_query(_strip_html(href))
            if name and len(name) <= 40:
                pid = _parse_eiga_person_id(a)
                if pid:
                    result.setdefault("cast_pairs", []).append({"name": name, "person_id": pid})
    except Exception:
        pass
    return result


async def build_deep_hints(hits: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    count = 0
    for h in hits:
        if count >= MAX_DEEP_FETCH:
            break
        url = (h.get("url") or h.get("href") or "").strip()
        if not url:
            continue
        host = urlparse(url).netloc.lower()
        # eiga.com はメイン作品ページ (/movie/<id>/) のみ対象にする
        if host == "eiga.com":
            pr = urlparse(url)
            if not re.match(r"^/movie/\d+/?$", pr.path):
                continue
        elif host != "movies.yahoo.co.jp":
            continue
        try:
            html = await _fetch_text(url)
            data = deep_extract_from_page(url, html)
            # 役割ごとに1行ずつ
            for label, key, limit in (
                ("監督", "director", 5),
                ("脚本", "screenplay", 5),
                ("原作", "author", 5),
                ("音楽", "composer", 5),
                ("出演/主演", "actor", 12),
            ):
                vals = data.get(key) or []
                if vals:
                    lines.append(f"- {label}: " + ", ".join(vals[:limit]))
            if data.get("year"):
                lines.append("- 年: " + ", ".join(data["year"][:5]))
            if data.get("title") or data.get("work"):
                ttl = data.get("title") or (", ".join(data["work"][:1]))
                lines.append("- タイトル: " + ttl)
            if data.get("synopsis"):
                lines.append("- あらすじ: " + (data["synopsis"][:300] + ("..." if len(data["synopsis"])>300 else "")))
            count += 1
        except Exception:
            continue
    return "\n".join(lines)

def build_structured_credit_hints(hits: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    total = 0
    for h in hits:
        title = str(h.get("title") or "")
        snippet = str(h.get("snippet") or "")
        c = extract_candidates_from_text(title, snippet)
        credits = extract_credit_candidates(title, snippet, c.get("works", []), c.get("years", []))
        if not credits:
            continue
        for cr in credits:
            work = cr.get("work") or "-"
            yr = cr.get("year") or "-"
            person = cr.get("person") or "?"
            role = cr.get("role") or "?"
            lines.append(f"- {work} ({yr}) : {person} [{role}]")
            total += 1
            if total >= 20:
                break
        if total >= 20:
            break
    return "\n".join(lines)


def _select_main_eiga_url(hits: List[Dict[str, Any]]) -> Optional[str]:
    for h in hits:
        url = (h.get("url") or h.get("href") or "").strip()
        if not url:
            continue
        pr = urlparse(url)
        if pr.netloc.lower() == "eiga.com" and re.match(r"^/movie/\d+/?$", pr.path):
            return url
    return None


def _select_person_base_url(hits: List[Dict[str, Any]]) -> Optional[str]:
    """eiga.com/person/<id>/ のベースURLを返す。movie/ 等の下位ページでもIDを拾い、ベースに正規化する。"""
    for h in hits:
        url = (h.get("url") or h.get("href") or "").strip()
        if not url:
            continue
        pr = urlparse(url)
        if pr.netloc.lower() != "eiga.com":
            continue
        # /person/<id>/, /person/<id>, /person/<id>/movie/... いずれも許容
        m = re.match(r"^/person/(\d+)(?:/|$)", pr.path)
        if m:
            pid = m.group(1)
            return f"https://eiga.com/person/{pid}/"
    return None


async def _search_eiga_person_url(query: str, log: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """eiga.com のサイト内検索を直接叩き、/person/<id>/ を一件返すフォールバック。"""
    try:
        q = sanitize_query(query)
        if not q:
            return None
        variants = [
            f"https://eiga.com/search/?q={q}",
            f"https://eiga.com/search/?s=person&k={q}",
            f"https://eiga.com/search/?s=1&k={q}",
        ]
        for url in variants:
            if log:
                log(f"Person direct search (eiga.com): {url}")
            html = await _fetch_text(url)
            # 最初に出現する /person/<id>/ を採用
            m = re.search(r"href=\"(/person/(\d+)/?)\"", html)
            if m:
                pid = m.group(2)
                pb = f"https://eiga.com/person/{pid}/"
                if log:
                    log(f"Person direct resolved: {pb}")
                return pb
    except Exception as e:
        if log:
            log(f"Person direct search failed: {e}")
    return None


async def perform_web_search_and_hints(current_query: str, domain: str) -> tuple[
    List[Dict[str, Any]],  # hits (effective later)
    List[Dict[str, Any]],  # merged_hits
    List[Dict[str, Any]],  # main_eiga_hits (movie pages)
    str,  # hints_list
    str,  # structured
    str,  # structured_credits
    str,  # deep
    str,  # raw_dump_path (file path where raw search results were saved)
]:
    """DuckDuckGo検索→ヒント生成を行う（ログ出力はしない）。"""
    # 検索計画
    search_plan: List[str] = []
    dom = str(domain or "")
    if "映画" in dom:
        search_plan = [
            f"{current_query} site:eiga.com/person",
            f"{current_query} site:eiga.com",
            f"{current_query} 映画.com",
            f"{current_query} 映画com",
            f"{current_query} site:movies.yahoo.co.jp",
            f"{current_query} site:.jp",
        ]
    else:
        search_plan = [f"{current_query} site:.jp"]

    allowed_hosts = {"movies.yahoo.co.jp", "eiga.com"}
    deny_hosts = {"youtube.com", "www.youtube.com", "tiktok.com", "www.tiktok.com", "jp.mercari.com"}

    merged_hits: List[Dict[str, Any]] = []
    per_query_results: List[Dict[str, Any]] = []
    seen_urls = set()
    for q in search_plan:
        if len(merged_hits) >= MAX_HITS_TOTAL:
            break
        partial = search_text(q, region="jp-jp", max_results=MAX_RESULTS_PER_QUERY, safesearch="moderate")
        # クエリごとの生結果を保持（search_textの戻り値を「そのまま」保存）
        try:
            per_query_results.append({
                "plan_query": q,
                "results": partial,
            })
        except Exception:
            pass
        for h in partial:
            url = (h.get("url") or h.get("href") or "").strip()
            if not url:
                continue
            if url in seen_urls:
                continue
            host = urlparse(url).netloc.lower()
            if host in deny_hosts:
                continue
            if "映画" in dom:
                if host in allowed_hosts:
                    seen_urls.add(url)
                    merged_hits.append(h)
                else:
                    if q.endswith("site:.jp") and host.endswith(".jp"):
                        seen_urls.add(url)
                        merged_hits.append(h)
            else:
                seen_urls.add(url)
                merged_hits.append(h)
            if len(merged_hits) >= MAX_HITS_TOTAL:
                break

    # 収集段では narrow せず、統合ヒットをそのまま使う
    main_eiga_hits: List[Dict[str, Any]] = []
    hits = merged_hits
    # ヒント構築
    hints_list = "\n".join([f"- {h.get('title')} :: {h.get('url') or h.get('href')} :: {h.get('snippet')}" for h in hits])
    structured = build_structured_hints(hits)
    structured_credits = build_structured_credit_hints(hits)
    deep = await build_deep_hints(hits)

    # 生検索結果をファイルに保存（logs/search）
    raw_dump_path = ""
    try:
        root_logs = os.path.abspath(os.path.join(BASE_DIR, "..", "logs"))
        target_dir = os.path.join(root_logs, "search")
        os.makedirs(target_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        qsafe = sanitize_query(current_query)[:50].replace(" ", "_")
        fname = f"search_{ts}_{qsafe or 'query'}.json"
        raw_dump_path = os.path.join(target_dir, fname)
        payload_dump = {
            "topic": current_query,
            "domain": domain,
            "timestamp": ts,
            "search_plan": search_plan,
            "per_query_results": per_query_results,  # ddgs結果をそのまま
            "merged_hits": merged_hits,
        }
        with open(raw_dump_path, "w", encoding="utf-8") as f:
            json.dump(payload_dump, f, ensure_ascii=False, indent=2)
    except Exception:
        raw_dump_path = ""

    return hits, merged_hits, main_eiga_hits, hints_list, structured, structured_credits, deep, raw_dump_path


async def resolve_person_base_url_from_hits(current_query: str, merged_hits: List[Dict[str, Any]], logf: Callable[[str], None]) -> Optional[str]:
    """merged_hits やフォールバック検索/直検索から人物ベースURLを決定する。"""
    person_base_url: Optional[str] = _select_person_base_url(merged_hits)
    if person_base_url:
        return person_base_url
    # フォールバック検索（DDG）
    fb_queries = [
        f"{current_query} site:eiga.com/person",
        f'"{current_query}" site:eiga.com/person',
    ]
    fallback_hits: List[Dict[str, Any]] = []
    for fbq in fb_queries:
        try:
            logf(f"Person fallback search: {fbq}")
            partial = search_text(fbq, region="jp-jp", max_results=12, safesearch="moderate")
        except Exception:
            partial = []
        if partial:
            logf("Person fallback hints begin")
            for h in partial:
                logf(f"- {h.get('title')} :: {h.get('url') or h.get('href')} :: {h.get('snippet')}")
            logf("Person fallback hints end")
        for h in partial:
            url = (h.get("url") or h.get("href") or "").strip()
            if not url:
                continue
            host = urlparse(url).netloc.lower()
            if host != "eiga.com":
                continue
            fallback_hits.append(h)
    if fallback_hits:
        pb = _select_person_base_url(fallback_hits)
        if pb:
            logf(f"Person base resolved: {pb}")
            return pb
    # 直検索（サイト内検索）
    try:
        pb2 = await _search_eiga_person_url(current_query, logf)
    except Exception:
        pb2 = None
    return pb2


def log_hints_and_build_block(logf: Callable[[str], None], hints_list: str, structured: str, structured_credits: str, deep: str, hits: List[Dict[str, Any]]) -> str:
    hint_block = ""
    if hints_list:
        hint_block += f"\n\n## 参考ヒント(検索結果)\n{hints_list}\n"
    if structured:
        hint_block += f"\n## 抽出候補(自動)\n{structured}\n"
    if structured_credits:
        hint_block += f"\n## クレジット候補(自動)\n{structured_credits}\n"
    if deep:
        hint_block += f"\n## 詳細抽出(サイト精読)\n{deep}\n"
    # ログ出力
    if hints_list:
        logf("Hints dump begin")
        for ln in hints_list.splitlines():
            logf(ln)
        logf("Hints dump end")
    if structured:
        logf("Candidates dump begin")
        for ln in structured.splitlines():
            logf(ln)
        logf("Candidates dump end")
    if structured_credits:
        logf("Credit candidates dump begin")
        for ln in structured_credits.splitlines():
            logf(ln)
        logf("Credit candidates dump end")
    if deep:
        logf("Deep candidates dump begin")
        for ln in deep.splitlines():
            logf(ln)
        logf("Deep candidates dump end")
    logf(f"Hints: {len(hits) if hints_list else 0} items")
    return hint_block


def _person_movie_page_urls(person_base_url: str, max_pages: int = 20) -> List[str]:
    """person/<id>/movie/ のページURL群を生成（1,2,3...）。"""
    urls = [person_base_url.rstrip('/') + '/movie/']
    for p in range(2, max_pages + 1):
        urls.append(person_base_url.rstrip('/') + f"/movie/{p}/")
    return urls


def _extract_movie_titles_from_person_movie_html(html: str) -> List[str]:
    """person/<id>/movie(/page)/ のHTMLから /movie/NNNNNN/ のテキスト（作品名）を抽出。
    ネストしたタグにも対応するため、a要素の内側HTMLをstripしてテキスト化してから抽出する。
    """
    titles: List[str] = []
    for inner in re.findall(r"<a[^>]+href=\"/movie/\d+/\"[^>]*>([\s\S]*?)</a>", html, re.IGNORECASE):
        text = sanitize_query(_strip_html(inner))
        if text and text not in titles:
            titles.append(text)
    return titles


def _extract_movie_entries_from_person_movie_html(html: str) -> List[Dict[str, Any]]:
    """人物の映画一覧HTMLから (title, movie_id) のエントリを抽出する。"""
    entries: List[Dict[str, Any]] = []
    seen = set()
    for href, mid, inner in re.findall(r"<a[^>]+href=\"(/movie/(\d+)/)\"[^>]*>([\s\S]*?)</a>", html, re.IGNORECASE):
        movie_id = mid
        title = sanitize_query(_strip_html(inner))
        key = (title, movie_id)
        if title and key not in seen:
            seen.add(key)
            entries.append({"title": title, "movie_id": movie_id})
    return entries


async def _fetch_person_all_movies(person_base_url: str) -> tuple[List[str], int]:
    titles: List[str] = []
    seen = set()
    pages = 0
    for url in _person_movie_page_urls(person_base_url):
        try:
            html = await _fetch_text(url)
        except Exception:
            break
        page_titles = _extract_movie_titles_from_person_movie_html(html)
        pages += 1
        new_any = False
        for t in page_titles:
            if t not in seen:
                seen.add(t)
                titles.append(t)
                new_any = True
        # 新規が無ければ以降は打ち切り
        if not new_any:
            break
    return titles, pages


async def _fetch_person_all_movie_entries(person_base_url: str) -> tuple[List[Dict[str, Any]], int]:
    entries: List[Dict[str, Any]] = []
    seen = set()
    pages = 0
    for url in _person_movie_page_urls(person_base_url):
        try:
            html = await _fetch_text(url)
        except Exception:
            break
        page_entries = _extract_movie_entries_from_person_movie_html(html)
        pages += 1
        new_any = False
        for e in page_entries:
            title = e.get("title")
            mid = e.get("movie_id")
            key = (title, mid)
            if title and key not in seen:
                seen.add(key)
                entries.append({"title": title, "movie_id": mid})
                new_any = True
        if not new_any:
            break
    return entries, pages


def _person_drama_page_urls(person_base_url: str, max_pages: int = 20) -> List[str]:
    """person/<id>/drama/ のページURL群を生成。"""
    urls = [person_base_url.rstrip('/') + '/drama/']
    for p in range(2, max_pages + 1):
        urls.append(person_base_url.rstrip('/') + f"/drama/{p}/")
    return urls


def _extract_drama_titles_from_person_drama_html(html: str) -> List[str]:
    """人物のドラマ一覧HTMLから作品名テキストを抽出。
    eiga.comのドラマ詳細リンクは将来構造変更の可能性があるため、/drama/ または /tv/ を含む a のテキストを候補とする。
    """
    titles: List[str] = []
    # /drama/<id>/ または /tv/... を持つリンクのテキストを抽出
    for inner in re.findall(r"<a[^>]+href=\"(?:/drama/\d+/|/tv/[^\"]+/)\"[^>]*>([\s\S]*?)</a>", html, re.IGNORECASE):
        text = sanitize_query(_strip_html(inner))
        if text and text not in titles:
            titles.append(text)
    return titles


async def _fetch_person_all_dramas(person_base_url: str) -> tuple[List[str], int]:
    titles: List[str] = []
    seen = set()
    pages = 0
    for url in _person_drama_page_urls(person_base_url):
        try:
            html = await _fetch_text(url)
        except Exception:
            break
        page_titles = _extract_drama_titles_from_person_drama_html(html)
        pages += 1
        new_any = False
        for t in page_titles:
            if t not in seen:
                seen.add(t)
                titles.append(t)
                new_any = True
        if not new_any:
            break
    return titles, pages


def _extract_person_profile(html: str) -> Dict[str, Any]:
    """人物プロフィール（かな/生年/没年/備考）を抽出。
    優先: JSON-LD(@type=Person) → 日本語ラベル（生年月日/誕生日/生年/没年/命日 等） → 括弧内かな。
    """
    profile: Dict[str, Any] = {"kana": None, "birth_year": None, "death_year": None, "note": None}
    # 1) JSON-LD (@type Person)
    try:
        for obj in _iter_json_ld(html):
            ty = obj.get("@type")
            types = [ty] if isinstance(ty, str) else (ty or [])
            if (isinstance(types, list) and ("Person" in types)) or ty == "Person":
                alt = (obj.get("alternateName") or obj.get("alternateNames") or "")
                if isinstance(alt, list):
                    alt = ",".join([str(a) for a in alt if a])
                alt = str(alt or "").strip()
                if alt:
                    profile["kana"] = alt
                # description を note 候補に
                desc = (obj.get("description") or "").strip()
                if desc and len(desc) >= 40:
                    profile["note"] = desc
                bdate = str(obj.get("birthDate") or "").strip()  # YYYY / YYYY-MM-DD
                if bdate:
                    m = re.search(r"(18|19|20)\d{2}", bdate)
                    if m:
                        by = int(m.group(0))
                        if 1800 <= by <= 2100:
                            profile["birth_year"] = by
                ddate = str(obj.get("deathDate") or "").strip()
                if ddate:
                    m = re.search(r"(18|19|20)\d{2}", ddate)
                    if m:
                        dy = int(m.group(0))
                        if 1800 <= dy <= 2100:
                            profile["death_year"] = dy
                break
    except Exception:
        pass
    text = _strip_html(html)
    # 2) 日本語ラベル + note本文からの詳細抽出
    try:
        if not profile.get("kana"):
            m = re.search(r"(ふりがな|フリガナ|よみがな|読み仮名|読み|ヨミ)[\s　]*[:：]?[\s　]*([\u3040-\u309F\u30A0-\u30FF・ー\s　]{2,40})", text)
            if m:
                profile["kana"] = m.group(2).strip()
    except Exception:
        pass
    try:
        # 誕生日（YYYY年MM月DD日）/ 生年のみ
        if not profile.get("birth_year"):
            m = re.search(r"(生年月日|誕生日)[\s　]*[:：]?[\s　]*((?:18|19|20)\d{2})年(?:\s*(\d{1,2})月)?(?:\s*(\d{1,2})日)?", text)
            if m:
                by = int(m.group(2))
                if 1800 <= by <= 2100:
                    profile["birth_year"] = by
        if not profile.get("birth_year"):
            m = re.search(r"(生年|生まれ)[\s　]*[:：]?[\s　]*((?:18|19|20)\d{2})年", text)
            if m:
                by = int(m.group(2))
                if 1800 <= by <= 2100:
                    profile["birth_year"] = by
    except Exception:
        pass
    try:
        if not profile.get("death_year"):
            m = re.search(r"(没年|命日|逝去|死亡)[\s　]*[:：]?[\s　]*((?:18|19|20)\d{2})年", text)
            if m:
                dy = int(m.group(2))
                if 1800 <= dy <= 2100:
                    profile["death_year"] = dy
    except Exception:
        pass
    # 3) 出身（任意）
    try:
        m = re.search(r"出身[\s　]*[:：]?[\s　]*([^\s　]+(?:[／/][^\s　]+)?)", text)
        if m:
            profile["birth_place"] = m.group(1).strip()
    except Exception:
        pass

    # 4) 括弧内かな（例: （よしざわ りょう））
    try:
        if not profile.get("kana"):
            m = re.search(r"（([\u3040-\u309F\u30A0-\u30FF・ー\s]{2,40})）", text)
            if m:
                k = m.group(1).strip()
                # 記号のみなどを除外
                if re.search(r"[\u3040-\u309F\u30A0-\u30FF]", k):
                    profile["kana"] = k
    except Exception:
        pass
    # 5) 備考（略歴/プロフィールを最優先で抽出。無ければ本文段落→冒頭1文）
    try:
        # 明示ラベルの直後テキストを優先
        m = re.search(r"(略歴|プロフィール)[\s　]*[:：]?[\s　]*([^\n]+)", text)
        if m:
            note = m.group(2).strip()
            if note:
                profile["note"] = note
        if not profile.get("note"):
            para = _extract_long_paragraph_from_html(html)
            if para:
                profile["note"] = para
        if not profile.get("note"):
            # ページ全体テキストから略歴らしい塊を推定
            bio = _extract_bio_from_text(text)
            if bio:
                profile["note"] = bio
        if not profile.get("note"):
            s = text.strip()
            cut = s.find("。")
            first = s[:cut+1] if cut != -1 else s[:200]
            if first:
                profile["note"] = first.strip()
    except Exception:
        pass
    return profile

def _parse_eiga_movie_id(url: str) -> Optional[str]:
    try:
        pr = urlparse(url)
        m = re.match(r"^/movie/(\d+)/?$", pr.path)
        return m.group(1) if m else None
    except Exception:
        return None


def _parse_eiga_person_id(url: str) -> Optional[str]:
    try:
        pr = urlparse(url)
        m = re.match(r"^/person/(\d+)/?$", pr.path)
        return m.group(1) if m else None
    except Exception:
        return None


def _normalize_eiga_person_url(url: str) -> Optional[str]:
    """eiga.com/person/<id>/... を https://eiga.com/person/<id>/ に正規化して返す。該当しなければ None。"""
    try:
        s = (url or "").strip()
        if not s:
            return None
        pr = urlparse(s)
        if not pr.scheme or not pr.netloc:
            return None
        if "eiga.com" not in pr.netloc.lower():
            return None
        m = re.match(r"^/person/(\d+)(?:/.*)?$", pr.path)
        if not m:
            return None
        pid = m.group(1)
        return f"https://eiga.com/person/{pid}/"
    except Exception:
        return None


async def build_deep_payload(hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "persons": [],
        "works": [],
        "credits": [],
        "external_ids": [],
        "unified": [],
        "note": None,
        "next_queries": [],
    }
    main_url = _select_main_eiga_url(hits)
    if not main_url:
        return payload
    try:
        html = await _fetch_text(main_url)
        data = deep_extract_from_page(main_url, html)
        title = (data.get("title") or (data.get("work") or [None])[0] or "").strip()
        if not title:
            return payload
        # Work
        yrs = list(data.get("year") or [])
        year_int: Optional[int] = None
        for y in yrs:
            try:
                yi = int(str(y)[:4])
                if 1800 <= yi <= 2100:
                    year_int = yi
                    break
            except Exception:
                continue
        synopsis = (data.get("synopsis") or "").strip() or None
        payload["works"].append({
            "title": title,
            "category": "映画",
            "year": year_int,
            "subtype": None,
            "summary": synopsis,
        })
        # Persons and credits
        role_map = {
            "director": "director",
            "screenplay": "screenplay",
            "author": "author",
            "composer": "composer",
            "theme_song": "theme_song",
            "sound_effects": "sound_effects",
            "producer": "producer",
            "actor": "actor",
            "voice": "voice",
        }
        added_persons: set[str] = set()
        def _add_person(name: str) -> None:
            n = name.strip()
            if not n or n in added_persons:
                return
            payload["persons"].append({"name": n})
            added_persons.add(n)
        for key, role in role_map.items():
            for nm in (data.get(key) or []):
                n = str(nm).strip()
                if not n:
                    continue
                _add_person(n)
                payload["credits"].append({
                    "work": title,
                    "person": n,
                    "role": role,
                    "character": None,
                })
        # cast_pairs から person external_id を付与
        try:
            for pair in (data.get("cast_pairs") or []):
                nm = str(pair.get("name") or "").strip()
                pid = str(pair.get("person_id") or "").strip()
                if nm and pid:
                    _add_person(nm)
                    payload.setdefault("external_ids", []).append({
                        "entity": "person",
                        "name": nm,
                        "source": "eiga.com",
                        "value": pid,
                        "url": f"https://eiga.com/person/{pid}/",
                    })
        except Exception:
            pass
        # external_id (eiga.com id)
        mid = _parse_eiga_movie_id(main_url)
        if mid:
            payload["external_ids"].append({
                "entity": "work",
                "name": title,
                "source": "eiga.com",
                "value": mid,
                "url": main_url,
            })
    except Exception:
        return payload
    return payload


def _merge_list_unique(items: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for it in items or []:
        k = tuple((it.get(k) or "").strip() for k in keys)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def merge_payloads(payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "persons": [],
        "works": [],
        "credits": [],
        "external_ids": [],
        "unified": [],
        "note": None,
    }
    for p in payloads:
        for key in result.keys():
            if key == "note":
                continue
            if p.get(key):
                result[key].extend(p[key])
    result["persons"] = _merge_list_unique(result["persons"], ["name"])
    result["works"] = _merge_list_unique(result["works"], ["title", "category"])
    result["credits"] = _merge_list_unique(result["credits"], ["work", "person", "role", "character"])
    result["external_ids"] = _merge_list_unique(result["external_ids"], ["entity", "name", "source"])
    result["unified"] = _merge_list_unique(result["unified"], ["name", "work", "relation"])
    return result


def _normalize_extracted_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """抽出JSONの緩やかな正規化を行う。
    - 欠損キーに空配列/Noneを補完
    - next_queries は最大5件・重複除去・文字列化・空白除去
    """
    normalized: Dict[str, Any] = {}
    # persons: 役割語の混入を除去
    persons_in = list(data.get("persons") or [])
    persons_out: List[Dict[str, Any]] = []
    for p in persons_in:
        nm = _remove_role_prefix(str((p or {}).get("name") or ""))
        if not nm or _is_pure_role_word(nm):
            continue
        q = dict(p)
        q["name"] = nm
        persons_out.append(q)
    normalized["persons"] = persons_out

    # works: タイトル先頭の役割語を除去し、役割語だけのタイトルは除外
    works_in = list(data.get("works") or [])
    works_out: List[Dict[str, Any]] = []
    for w in works_in:
        ttl = _remove_role_prefix(str((w or {}).get("title") or ""))
        if not ttl or _is_pure_role_word(ttl):
            continue
        q = dict(w)
        q["title"] = ttl
        works_out.append(q)
    normalized["works"] = works_out
    normalized["credits"] = list(data.get("credits") or [])
    normalized["external_ids"] = list(data.get("external_ids") or [])
    normalized["unified"] = list(data.get("unified") or [])
    normalized["note"] = data.get("note") if data.get("note") is not None else None
    # next_queries の正規化（役割語除去/弾き）
    nq: List[str] = []
    for q in (data.get("next_queries") or [])[:10]:  # 念のため上限
        qs = _remove_role_prefix(str(q).strip())
        if not qs:
            continue
        if _is_pure_role_word(qs):
            continue
        if qs in nq:
            continue
        nq.append(qs)
        if len(nq) >= 5:
            break
    normalized["next_queries"] = nq
    return normalized

def _is_effectively_empty_payload(data: Dict[str, Any]) -> bool:
    return not any(len(data.get(k) or []) for k in ["persons", "works", "credits", "external_ids", "unified"]) 


def _select_next_keyword(db_path: str, candidates: List[str]) -> Optional[str]:
    """候補キーワードの先頭から順に、DBに存在しないものを返す（person.name と work.title を厳密一致で確認）。
    見つからなければ None。
    """
    try:
        db_abs = os.path.abspath(db_path)
        conn = sqlite3.connect(db_abs)
        with conn:
            for raw in candidates or []:
                kw = str(raw or "").strip()
                if not kw:
                    continue
                # person/ work のどちらにも無ければ採用
                cur = conn.execute("SELECT 1 FROM person WHERE name=? LIMIT 1", (kw,))
                if cur.fetchone():
                    continue
                cur = conn.execute("SELECT 1 FROM work WHERE title=? LIMIT 1", (kw,))
                if cur.fetchone():
                    continue
                return kw
    except Exception:
        pass
    return None


async def run_ingest_mode(
    topic: str,
    domain: str,
    rounds: int,
    db_path: str,
    expand: bool = True,
    strict: bool = False,
    log_callback: Optional[Callable[[str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    topic_type: str = "unknown",
    auto_next_max: int = 3,
) -> Dict[str, Any]:
    ensure_dirs()
    log_filename = os.path.join(BASE_DIR, "logs", "ingest_conversation.log")
    operation_log_filename = os.path.join(BASE_DIR, "..", "logs", "operation_ingest.log")

    manager = CharacterManager(log_filename, operation_log_filename)

    # 事前ウォームアップ（Ollamaの場合）
    try:
        for c in manager.list_characters():
            if str(c.get("provider", "")).lower() == "ollama":
                base_url = c.get("base_url", "http://localhost:11434")
                model = c.get("model")
                ensure_ollama_model_ready_sync(base_url, model, operation_log_filename)
    except Exception:
        pass

    extractor = build_extractor_prompt(domain)
    def _log(msg: str) -> None:
        try:
            if log_callback:
                log_callback(msg)
        except Exception:
            pass
    collected: List[Dict[str, Any]] = []
    # URL直指定（eiga.com/person/<id>/...）なら検索を行わず、このURLのみで収集する
    forced_person_base: Optional[str] = _normalize_eiga_person_url(topic)

    # 検索専用キャラ（隠し）を優先使用。存在しなければ可視キャラでフォールバック
    all_names = manager.get_character_names(include_hidden=True)
    characters = [n for n in all_names if n == "サーチャー"] or manager.get_character_names(include_hidden=False)
    # 検索クエリのキューと実行済み集合
    executed_queries = set()  # type: ignore[var-annotated]
    next_query_queue: List[str] = []
    base_topic = sanitize_query(topic)
    base_type = (topic_type or "unknown").lower()
    _log(f"Start ingest: topic='{topic}', domain='{domain}', rounds={rounds}, strict={strict}")
    iter_max = max(1, rounds)
    auto_budget = max(0, int(auto_next_max))
    r = 0
    while r < iter_max:
        # STOPボタン/外部キャンセルの確認
        try:
            if cancel_check and cancel_check():
                _log("Cancelled by user request")
                break
        except Exception:
            pass
        # 次に叩く検索クエリを決定
        if expand and next_query_queue:
            current_query = sanitize_query(next_query_queue.pop(0))
        else:
            current_query = base_topic
        if not current_query:
            current_query = sanitize_query(topic)
        executed_queries.add(current_query)
        _log(f"Search query: {current_query}")
        # 現在のクエリのタイプ（人物/作品）を推定/保持
        def _infer_type(q: str) -> str:
            t = base_type
            if t not in ("work", "person"):
                # ひらかな/カタカナ/漢字のみで2-4文字の固有名に見える場合は人物寄り
                qs = q.strip()
                if re.match(r"^[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]{2,4}$", qs):
                    t = "person"
                else:
                    t = "unknown"
            return t
        current_type = _infer_type(current_query)

        # ラウンド内で収集したペイロード（次キーワード選定用）
        round_payloads: List[Dict[str, Any]] = []
        # 検索→ヒント生成（分離関数）
        try:
            person_base_url: Optional[str] = None
            if forced_person_base:
                # 検索スキップ。人物ページのみを情報源にする
                hits, merged_hits, main_eiga_hits = [], [], []
                person_base_url = forced_person_base
                hints_list = f"- PERSON_URL :: {person_base_url}"
                structured = ""
                structured_credits = ""
                deep = ""
                raw_dump_path = ""
                hint_block = log_hints_and_build_block(_log, hints_list, structured, structured_credits, deep, hits)
                _log(f"Forced person mode: {person_base_url}")
            else:
                hits, merged_hits, main_eiga_hits, hints_list, structured, structured_credits, deep, raw_dump_path = await perform_web_search_and_hints(current_query, domain)
                # 人物ベースURL解決
                person_base_url = await resolve_person_base_url_from_hits(current_query, merged_hits, _log)
                # 取得元を人物ページに限定表示（他のヒントは抑制）
                if person_base_url:
                    hints_list = f"- PERSON_URL :: {person_base_url}"
                    structured = ""
                    structured_credits = ""
                    deep = ""
                # ログ出力とヒントブロック生成
                hint_block = log_hints_and_build_block(_log, hints_list, structured, structured_credits, deep, hits)
            # 生検索結果ファイルの場所をログに出す
            if raw_dump_path:
                _log(f"Saved raw search results: {raw_dump_path}")
            # 人物ベースURLが取れたら、プロフィール/作品一覧を収集
            if person_base_url:
                _log(f"Person base resolved: {person_base_url}")
                try:
                    # プロフィール
                    try:
                        person_html = await _fetch_text(person_base_url)
                        profile = _extract_person_profile(person_html)
                    except Exception:
                        profile = {"kana": None, "birth_year": None, "death_year": None, "note": None}
                    # 方針: person が取れていれば movieは不要。dramaのみ巡回
                    all_titles, pages = ([], 0)
                    drama_titles, drama_pages = await _fetch_person_all_dramas(person_base_url)
                    all_entries, _pages2 = ([], 0)
                    if drama_titles or any(profile.values()):
                        if drama_titles:
                            _log(f"PersonDrama: {len(drama_titles)} items, pages={drama_pages}")
                        # 参考: 映画一覧もログに表示（登録は行わない）
                        # 映画一覧の取得とログ・ペイロード化（タイトルとURLを正規化して登録）
                        try:
                            movie_entries, movie_pages = await _fetch_person_all_movie_entries(person_base_url)
                            normalized_movies: List[Dict[str, Any]] = []
                            if movie_entries:
                                _log("Movie list (from person page):")
                                for ent in movie_entries[:50]:
                                    t = _clean_title_token(ent.get('title') or '')
                                    mid = str(ent.get('movie_id') or '').strip()
                                    if not t or not mid:
                                        continue
                                    url_norm = f"https://eiga.com/movie/{mid}/"
                                    _log(f"- {t} (id:{mid}) :: {url_norm}")
                                    normalized_movies.append({"title": t, "movie_id": mid, "url": url_norm})
                            # 正規化済み映画を DB ペイロードに追加
                            if normalized_movies:
                                for m in normalized_movies:
                                    ttl = m["title"]
                                    filmography_payload["works"].append({
                                        "title": ttl, "category": "映画", "year": None, "subtype": None, "summary": None
                                    })
                                    filmography_payload["credits"].append({
                                        "work": ttl, "person": person_name, "role": "actor", "character": None
                                    })
                                    filmography_payload["external_ids"].append({
                                        "entity": "work", "name": ttl, "source": "eiga.com", "value": m["movie_id"], "url": m["url"]
                                    })
                        except Exception:
                            pass
                        # スナップショットをファイル保存
                        try:
                            snap = {
                                "topic": current_query,
                                "person_base_url": person_base_url,
                                "profile": profile,
                                "movie_count": len(all_titles),
                                "movie_pages": pages,
                                "drama_count": len(drama_titles),
                                "drama_pages": drama_pages,
                                "movies_sample": all_titles[:50],
                            }
                            root_logs = os.path.abspath(os.path.join(BASE_DIR, "..", "logs"))
                            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                            qsafe = sanitize_query(current_query)[:50].replace(" ", "_")
                            snap_path = os.path.join(root_logs, "person", f"person_{ts}_{qsafe or 'query'}.json")
                            with open(snap_path, "w", encoding="utf-8") as f:
                                json.dump(snap, f, ensure_ascii=False, indent=2)
                            _log(f"Saved person snapshot: {snap_path}")
                        except Exception:
                            pass
                        if not forced_person_base:
                            structured_add = "- 作品候補: " + ", ".join(drama_titles[:20]) if drama_titles else ""
                            structured = (structured + "\n" + structured_add) if structured_add and structured else (structured_add or structured)
                        person_name = sanitize_query(current_query)
                        if person_name:
                            try:
                                person_pid = _parse_eiga_person_id(person_base_url)
                            except Exception:
                                person_pid = None
                        # 作品名トークンのクリーンアップ（「上映中」「配信中」「出演」などの前置きを除去）
                        cleaned_drama_titles = _dedupe_preserve_order([_clean_title_token(t) for t in drama_titles])
                        cleaned_drama_titles = [t for t in cleaned_drama_titles if t and not _is_pure_role_word(t)]

                        filmography_payload: Dict[str, Any] = {
                                "persons": [{
                                    "name": person_name,
                                    "kana": profile.get("kana"),
                                    "birth_year": profile.get("birth_year"),
                                    "death_year": profile.get("death_year"),
                                    "note": profile.get("note"),
                                }],
                                "works": ([{"title": t, "category": "ドラマ", "year": None, "subtype": None, "summary": None} for t in cleaned_drama_titles]),
                                "credits": ([{"work": t, "person": person_name, "role": "actor", "character": None} for t in cleaned_drama_titles]),
                                "external_ids": ([{
                                    "entity": "person",
                                    "name": person_name,
                                    "source": "eiga.com",
                                    "value": person_pid,
                                    "url": person_base_url,
                                }] if person_pid else []),
                                "unified": [],
                                "note": None,
                            "next_queries": cleaned_drama_titles,
                        }
                        # 映画エントリ/深掘りはスキップ（dramaのみ運用）
                        collected.append(filmography_payload)
                        round_payloads.append(filmography_payload)
                        _log(f"Added filmography payload: persons={len(filmography_payload['persons'])}, works={len(filmography_payload['works'])}, credits={len(filmography_payload['credits'])}")
                except Exception as e:
                    _log(f"Person filmography extraction failed: {e}")
        except Exception:
            hits, hints_list, structured, structured_credits, deep = [], "", "", "", ""
            hint_block = ""
        # 適切な検索結果が乏しい場合は人物/作品のタイプを切替（片側が空近い）
        try:
            # 人物フィルモグラフィが成立している場合はタイプ切替を抑止
            filmography_succeeded = any(len(p.get('works') or []) > 0 for p in round_payloads)
            if not filmography_succeeded:
                if (not hits) or (('人物候補' not in structured and current_type == 'person') or ('作品候補' not in structured and current_type == 'work')):
                    if current_type in ('person','work'):
                        current_type = 'work' if current_type == 'person' else 'person'
                        _log(f"Switched query type: {current_type}")
        except Exception:
            pass
        # 上記で round_payloads に追記済み
        for name in characters:
            persona = manager.get_persona_prompt(name)
            if strict:
                system_prompt = f"## 収集モード(STRICT)\n{extractor}\n\n必ず有効なJSONのみを出力してください。前置き・補足・マークダウンは禁止です。"
            else:
                system_prompt = f"{persona}\n\n## 収集モード\n{extractor}"
            llm = manager.get_llm(name)
            if llm is None:
                continue
            try:
                # 検索ヒントを常に併用して1回で応答を取得
                resp = await asyncio.wait_for(llm.ainvoke(system_prompt, f"収集対象: {current_query}{hint_block}"), timeout=60.0)
                data = extract_json(resp)
                if isinstance(data, dict):
                    data = _normalize_extracted_payload(data)
                    # JSONだが中身が空の場合は修復/補完を試みる
                    if _is_effectively_empty_payload(data):
                        try:
                            repair_prompt = build_repair_prompt(domain)
                            rep = await asyncio.wait_for(llm.ainvoke(repair_prompt, resp), timeout=45.0)
                            fixed = extract_json(rep)
                            if isinstance(fixed, dict):
                                fixed = _normalize_extracted_payload(fixed)
                                if not _is_effectively_empty_payload(fixed):
                                    data = fixed
                                    _log("Repaired JSON payload")
                        except Exception:
                            pass
                    collected.append(data)
                    round_payloads.append(data)
                    write_operation_log(operation_log_filename, "INFO", "IngestMode", f"Collected payload from {name} (round {r+1}).")
                    _log(f"Collected JSON from {name}")
                    # 依然として空なら deep フォールバックを追加で補完
                    if _is_effectively_empty_payload(data):
                        try:
                            fallback_payload = await build_deep_payload(hits)
                            if any(fallback_payload.get(k) for k in ("persons","works","credits","external_ids")):
                                collected.append(fallback_payload)
                                write_operation_log(operation_log_filename, "INFO", "IngestMode", f"Collected payload (fallback-deep) (round {r+1}).")
                                _log("Collected fallback payload (deep)")
                        except Exception:
                            pass
                    if expand:
                        # LLMが提案した next_queries を優先採用
                        for q in (data.get("next_queries") or []):
                            qstr = sanitize_query(str(q))
                            if not qstr:
                                continue
                            if qstr in executed_queries:
                                continue
                            if qstr in next_query_queue:
                                continue
                            next_query_queue.append(qstr)
                        # フォールバック: persons/works から語を抽出
                        if not data.get("next_queries"):
                            for p in (data.get("persons") or []):
                                n = sanitize_query(p.get("name") or "")
                                if n and n not in executed_queries and n not in next_query_queue:
                                    next_query_queue.append(n)
                            for w in (data.get("works") or []):
                                n = sanitize_query(w.get("title") or "")
                                if n and n not in executed_queries and n not in next_query_queue:
                                    next_query_queue.append(n)
                else:
                    # リトライ（STRICT再試行）
                    if not strict:
                        sp = f"## 収集モード(STRICT-RETRY)\n{extractor}\n\nJSONのみを返してください。先頭から {{ と }} までの有効JSONのみ。"
                        resp2 = await asyncio.wait_for(llm.ainvoke(sp, f"収集対象: {current_query}{hint_block}"), timeout=60.0)
                        data2 = extract_json(resp2)
                        if isinstance(data2, dict):
                            data2 = _normalize_extracted_payload(data2)
                            collected.append(data2)
                            round_payloads.append(data2)
                            write_operation_log(operation_log_filename, "INFO", "IngestMode", f"Collected payload (retry) from {name} (round {r+1}).")
                            _log(f"Collected JSON (retry) from {name}")
                            if expand:
                                for q in (data2.get("next_queries") or []):
                                    qstr = sanitize_query(str(q))
                                    if qstr and qstr not in executed_queries and qstr not in next_query_queue:
                                        next_query_queue.append(qstr)
                                if not data2.get("next_queries"):
                                    for p in (data2.get("persons") or []):
                                        n = sanitize_query(p.get("name") or "")
                                        if n and n not in executed_queries and n not in next_query_queue:
                                            next_query_queue.append(n)
                                    for w in (data2.get("works") or []):
                                        n = sanitize_query(w.get("title") or "")
                                        if n and n not in executed_queries and n not in next_query_queue:
                                            next_query_queue.append(n)
                        else:
                            write_operation_log(operation_log_filename, "WARNING", "IngestMode", f"Non-JSON from {name} (round {r+1}).")
                            _log(f"Non-JSON from {name}")
                            # デバッグ用に生応答を保存
                            try:
                                raw_path = os.path.join(BASE_DIR, "logs", f"ingest_raw_r{r+1}_{name}.txt")
                                os.makedirs(os.path.dirname(raw_path), exist_ok=True)
                                with open(raw_path, "w", encoding="utf-8") as f:
                                    f.write(str(resp2))
                            except Exception:
                                pass
                            # Fallback: Deep抽出から自動ペイロード生成
                            try:
                                fallback_payload = await build_deep_payload(hits)
                                if any(fallback_payload.get(k) for k in ("persons","works","credits","external_ids")):
                                    collected.append(fallback_payload)
                                    round_payloads.append(fallback_payload)
                                    write_operation_log(operation_log_filename, "INFO", "IngestMode", f"Collected payload (fallback-deep) (round {r+1}).")
                                    _log("Collected fallback payload (deep)")
                            except Exception:
                                pass
                            preview = str(resp2 or "").replace("\n", " ")[:200]
                            if preview:
                                _log(f"Preview: {preview}")
                    else:
                        write_operation_log(operation_log_filename, "WARNING", "IngestMode", f"Non-JSON from {name} (round {r+1}).")
                        _log(f"Non-JSON from {name}")
                        # デバッグ用に生応答を保存
                        try:
                            raw_path = os.path.join(BASE_DIR, "logs", f"ingest_raw_r{r+1}_{name}.txt")
                            os.makedirs(os.path.dirname(raw_path), exist_ok=True)
                            with open(raw_path, "w", encoding="utf-8") as f:
                                f.write(str(resp))
                        except Exception:
                            pass
                        # Fallback: Deep抽出から自動ペイロード生成
                        try:
                            fallback_payload = await build_deep_payload(hits)
                            if any(fallback_payload.get(k) for k in ("persons","works","credits","external_ids")):
                                collected.append(fallback_payload)
                                round_payloads.append(fallback_payload)
                                write_operation_log(operation_log_filename, "INFO", "IngestMode", f"Collected payload (fallback-deep) (round {r+1}).")
                                _log("Collected fallback payload (deep)")
                        except Exception:
                            pass
                        preview = str(resp or "").replace("\n", " ")[:200]
                        if preview:
                            _log(f"Preview: {preview}")
            except asyncio.TimeoutError:
                write_operation_log(operation_log_filename, "WARNING", "IngestMode", f"Timeout from {name} (round {r+1}).")
                _log(f"Timeout from {name}")
            except Exception as e:
                write_operation_log(operation_log_filename, "ERROR", "IngestMode", f"Error from {name} (round {r+1}): {e}")
                _log(f"Error from {name}: {e}")

        # ラウンド末に次検索キーワードを先頭に追加
        try:
            next_candidates_round: List[str] = []
            for p in round_payloads:
                for q in (p.get("next_queries") or []):
                    qs = sanitize_query(str(q))
                    if qs and qs not in next_candidates_round:
                        next_candidates_round.append(qs)
            # 人物ページ由来の全作品名を優先してnextに反映（存在チェックは後段で実施）
            if person_base_url:
                try:
                    all_titles, _pg = await _fetch_person_all_movies(person_base_url)
                    for t in all_titles:
                        st = sanitize_query(t)
                        if st and st not in next_candidates_round:
                            next_candidates_round.append(st)
                except Exception:
                    pass
            if not next_candidates_round:
                for p in round_payloads:
                    for pr in (p.get("persons") or []):
                        n = sanitize_query(pr.get("name") or "")
                        if n and n not in next_candidates_round:
                            next_candidates_round.append(n)
                    for w in (p.get("works") or []):
                        n = sanitize_query(w.get("title") or "")
                        if n and n not in next_candidates_round:
                            next_candidates_round.append(n)
            # 人物フィルモグラフィが成立している場合は次検索のエンキューも抑止
            filmography_succeeded = any(len(p.get('works') or []) > 0 for p in round_payloads)
            if not filmography_succeeded:
                nk = _select_next_keyword(db_path, next_candidates_round)
                if nk and nk not in executed_queries and nk not in next_query_queue:
                    # 役割語プレフィックスは事前除去済みだが念のため再チェック
                    clean_nk = _remove_role_prefix(nk)
                    if clean_nk and not _is_pure_role_word(clean_nk):
                        next_query_queue.insert(0, clean_nk)
                        _log(f"Enqueued next keyword: {clean_nk} ({current_type or 'unknown'})")
        except Exception:
            pass

        r += 1
        # 自動継続（予算がありキューもある場合、即座に次ラウンドへ）
        if next_query_queue and auto_budget > 0:
            auto_budget -= 1
            iter_max += 1  # 追加ラウンドを許容
            continue
        # 予算切れ あるいは キュー無しで終了
        if not next_query_queue or auto_budget <= 0:
            break

    merged = merge_payloads(collected)

    # next keyword selection
    next_candidates: List[str] = []
    # 1) LLMの next_queries を優先
    for p in collected:
        for q in (p.get("next_queries") or []):
            qs = sanitize_query(str(q))
            if qs and qs not in next_candidates:
                next_candidates.append(qs)
    # 2) 補助: persons/works の名前/タイトルからも候補を補完
    if not next_candidates:
        for p in merged.get("persons") or []:
            n = sanitize_query(p.get("name") or "")
            if n and n not in next_candidates:
                next_candidates.append(n)
        for w in merged.get("works") or []:
            n = sanitize_query(w.get("title") or "")
            if n and n not in next_candidates:
                next_candidates.append(n)

    next_keyword: Optional[str] = _select_next_keyword(db_path, next_candidates)

    if ingest_payload is None:
        write_operation_log(operation_log_filename, "ERROR", "IngestMode", "KB.ingest not available; skipping DB registration.")
    else:
        try:
            ingest_payload(os.path.abspath(db_path), merged)
            write_operation_log(operation_log_filename, "INFO", "IngestMode", f"Registered to DB: {db_path}")
            _log("Registered to DB")
            # 追加要素のサマリをログ出力
            try:
                persons = merged.get("persons") or []
                works = merged.get("works") or []
                credits = merged.get("credits") or []
                external_ids = merged.get("external_ids") or []
                unified = merged.get("unified") or []
                _log(
                    "DB added summary: "
                    f"persons={len(persons)}, works={len(works)}, credits={len(credits)}, "
                    f"external_ids={len(external_ids)}, unified={len(unified)}"
                )
                if persons:
                    _log("Added persons:")
                    for p in persons[:10]:
                        _log(f"- {str(p.get('name') or '').strip()}")
                    if len(persons) > 10:
                        _log(f"... and {len(persons)-10} more persons")
                if works:
                    _log("Added works:")
                    for w in works[:10]:
                        ttl = str(w.get('title') or '').strip()
                        yr = w.get('year')
                        cat = str(w.get('category') or '').strip()
                        extra = []
                        if cat:
                            extra.append(cat)
                        if yr:
                            extra.append(str(yr))
                        suffix = f" ({', '.join(extra)})" if extra else ""
                        _log(f"- {ttl}{suffix}")
                    if len(works) > 10:
                        _log(f"... and {len(works)-10} more works")
                if credits:
                    _log("Added credits:")
                    for c in credits[:10]:
                        wk = str(c.get('work') or '').strip()
                        ps = str(c.get('person') or '').strip()
                        rl = str(c.get('role') or '').strip()
                        ch = str(c.get('character') or '').strip()
                        chs = f" as {ch}" if ch else ""
                        _log(f"- {wk} : {ps} [{rl}]{chs}")
                    if len(credits) > 10:
                        _log(f"... and {len(credits)-10} more credits")
                if external_ids:
                    _log("Added external_ids:")
                    for e in external_ids[:10]:
                        ent = str(e.get('entity') or '').strip()
                        nm = str(e.get('name') or '').strip()
                        src = str(e.get('source') or '').strip()
                        val = str(e.get('value') or '').strip()
                        _log(f"- {ent}:{nm} {src}={val}")
                    if len(external_ids) > 10:
                        _log(f"... and {len(external_ids)-10} more external_ids")

                # 追加の詳細（作品ごと役割別・ID付き）
                try:
                    # DBからIDを引く
                    db_abs = os.path.abspath(db_path)
                    conn = sqlite3.connect(db_abs)
                    conn.row_factory = sqlite3.Row
                    with conn:
                        # 作品ごとの詳細
                        role_order = [
                            "director", "screenplay", "author", "composer",
                            "theme_song", "sound_effects", "producer"
                        ]
                        for w in works:
                            title = (w.get("title") or "").strip()
                            if not title:
                                continue
                            cur = conn.execute("SELECT id, year FROM work WHERE title=? ORDER BY id DESC LIMIT 1", (title,))
                            row_w = cur.fetchone()
                            wid = row_w["id"] if row_w else None
                            yr_db = row_w["year"] if row_w else None
                            cat = (w.get("category") or "").strip()
                            yr = w.get("year") or yr_db
                            _log(f"Work detail: {title} [id:{wid if wid is not None else '-'}]{' ('+cat+')' if cat else ''}{' ('+str(yr)+')' if yr else ''}")
                            if w.get("summary"):
                                summ = str(w.get("summary") or "")
                                _log("  Summary: " + (summ[:300] + ("..." if len(summ) > 300 else "")))
                            # 役割別
                            cs = [c for c in credits if (c.get("work") or "").strip() == title]
                            # スタッフ系
                            for rname in role_order:
                                names = []
                                for c in cs:
                                    if str(c.get("role") or "").strip() == rname:
                                        nm = (c.get("person") or "").strip()
                                        if nm and nm not in names:
                                            names.append(nm)
                                if names:
                                    _log(f"  {rname}: " + ", ".join(names))
                            # キャスト
                            cast_lines = []
                            for c in cs:
                                role = str(c.get("role") or "").strip()
                                if role in ("actor", "voice"):
                                    nm = (c.get("person") or "").strip()
                                    ch = (c.get("character") or "").strip()
                                    cast_lines.append(f"- {nm} [{role}]" + (f" as {ch}" if ch else ""))
                            if cast_lines:
                                _log("  cast:")
                                for ln in cast_lines[:30]:
                                    _log("    " + ln)
                            # 外部ID
                            for e in external_ids:
                                if (e.get("entity") == "work") and ((e.get("name") or "").strip() == title):
                                    src = (e.get("source") or "").strip()
                                    val = (e.get("value") or "").strip()
                                    url = (e.get("url") or "").strip()
                                    _log(f"  external_id: {src}={val} {url}")
                        # 人物IDリスト
                        if persons:
                            _log("Persons with IDs:")
                            for p in persons[:50]:
                                nm = (p.get("name") or "").strip()
                                if not nm:
                                    continue
                                cur = conn.execute("SELECT id FROM person WHERE name=? ORDER BY id DESC LIMIT 1", (nm,))
                                row_p = cur.fetchone()
                                pid = row_p["id"] if row_p else None
                                _log(f"- {nm} [id:{pid if pid is not None else '-'}]")
                except Exception:
                    pass
            except Exception:
                pass
            # NextKeyword を最後に出力
            try:
                if next_keyword:
                    _log(f"NextKeyword: {next_keyword}")
                elif next_candidates:
                    _log(f"NextKeyword: (no-new) first-candidate='{next_candidates[0]}'")
                else:
                    _log("NextKeyword: (none)")
            except Exception:
                pass
        except Exception as e:
            write_operation_log(operation_log_filename, "ERROR", "IngestMode", f"Failed to register DB: {e}")
            _log(f"Failed to register DB: {e}")

    return merged
