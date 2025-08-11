import os
import json
import re
import asyncio
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


def build_extractor_prompt(domain: str) -> str:
    template = """あなたは事実収集アシスタントです。以下の対象ドメインに限定し、確度の高い事実のみを抽出します。
推測は避け、未確定情報は note に記載してください。
対象ドメイン: {DOMAIN}

出力規則:
- 出力は JSON オブジェクト 1個のみ。前置き・後置き・Markdown・説明は禁止。
- コードフェンス（```）やバッククォート、見出しや箇条書きなどのMarkdown記法は一切禁止。
- もし情報が見つからない場合でも、空配列を持つJSONを返す（例: persons:[], works:[] ...）。
- JSONは次のマーカーに必ず挟むこと。
  <<<JSON_START>>>
  {{ ... }}
  <<<JSON_END>>>
 - 次ラウンドで使う検索語を next_queries に最大5件、配列で必ず出力すること（重複や既出語は避け、端的な日本語クエリ）。英語やローマ字は避け、日本語で書くこと。

スキーマ:
{{
  "persons": [ {{ "name": "", "aliases": [""] }} ],
  "works": [ {{ "title": "", "category": "映画", "year": 2024, "subtype": null, "summary": null }} ],
  "credits": [ {{ "work": "", "person": "", "role": "actor", "character": null }} ],
  "external_ids": [ {{ "entity": "work", "name": "", "source": "wikipedia", "value": "", "url": null }} ],
  "unified": [ {{ "name": "", "work": "", "relation": "adaptation" }} ],
  "note": null,
  "next_queries": [ "" ]
}}
"""
    # {DOMAIN} を埋め込み、テンプレートを返す
    return template.replace("{DOMAIN}", str(domain))

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
    normalized["persons"] = list(data.get("persons") or [])
    normalized["works"] = list(data.get("works") or [])
    normalized["credits"] = list(data.get("credits") or [])
    normalized["external_ids"] = list(data.get("external_ids") or [])
    normalized["unified"] = list(data.get("unified") or [])
    normalized["note"] = data.get("note") if data.get("note") is not None else None
    # next_queries の正規化
    nq: List[str] = []
    for q in (data.get("next_queries") or [])[:10]:  # 念のため上限
        qs = str(q).strip()
        if not qs:
            continue
        if qs in nq:
            continue
        nq.append(qs)
        if len(nq) >= 5:
            break
    normalized["next_queries"] = nq
    return normalized


async def run_ingest_mode(
    topic: str,
    domain: str,
    rounds: int,
    db_path: str,
    expand: bool = True,
    strict: bool = False,
    log_callback: Optional[Callable[[str], None]] = None,
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

    # 検索専用キャラ（隠し）を優先使用。存在しなければ可視キャラでフォールバック
    all_names = manager.get_character_names(include_hidden=True)
    characters = [n for n in all_names if n == "サーチャー"] or manager.get_character_names(include_hidden=False)
    # 検索クエリのキューと実行済み集合
    executed_queries = set()  # type: ignore[var-annotated]
    next_query_queue: List[str] = []
    base_topic = sanitize_query(topic)
    _log(f"Start ingest: topic='{topic}', domain='{domain}', rounds={rounds}, strict={strict}")
    for r in range(max(1, rounds)):
        # 次に叩く検索クエリを決定
        if expand and next_query_queue:
            current_query = sanitize_query(next_query_queue.pop(0))
        else:
            current_query = base_topic
        if not current_query:
            current_query = sanitize_query(topic)
        executed_queries.add(current_query)
        _log(f"Search query: {current_query}")

        # DuckDuckGo 検索を先に実施し、上位結果をヒントとして同梱
        try:
            # 映画ドメインではナタリー/ヤフー映画/eiga.com を優先し、不足分を .jp で補完
            search_plan: List[str] = []
            dom = str(domain or "")
            if "映画" in dom:
                search_plan = [
                    f"{current_query} site:natalie.mu",
                    f"{current_query} site:movies.yahoo.co.jp",
                    f"{current_query} site:eiga.com",
                    f"{current_query} 映画.com",
                    f"{current_query} 映画com",
                    f"{current_query} site:.jp",
                ]
            else:
                search_plan = [f"{current_query} site:.jp"]

            allowed_hosts = {"natalie.mu", "movies.yahoo.co.jp", "eiga.com"}
            deny_hosts = {"youtube.com", "www.youtube.com", "tiktok.com", "www.tiktok.com", "jp.mercari.com"}

            merged_hits: List[Dict[str, Any]] = []
            seen_urls = set()
            for q in search_plan:
                if len(merged_hits) >= 8:
                    break
                partial = search_text(q, region="jp-jp", max_results=8, safesearch="moderate")
                for h in partial:
                    url = (h.get("url") or h.get("href") or "").strip()
                    if not url:
                        continue
                    if url in seen_urls:
                        continue
                    host = urlparse(url).netloc.lower()
                    if host in deny_hosts:
                        continue
                    # 映画ドメイン: 許可ドメインを優先採用。許可外は .jp フォールバック段階のみで採用し、ノイズは除外
                    if "映画" in dom:
                        if host in allowed_hosts:
                            seen_urls.add(url)
                            merged_hits.append(h)
                        else:
                            # 最後の .jp クエリ時のみ、許可外でも .jp を許容（denyは除外）
                            if q.endswith("site:.jp") and host.endswith(".jp"):
                                seen_urls.add(url)
                                merged_hits.append(h)
                    else:
                        # 非映画ドメインは緩やかに許容（deny除外のみ）
                        seen_urls.add(url)
                        merged_hits.append(h)
                    if len(merged_hits) >= 8:
                        break

            hits = merged_hits
            hints = "\n".join([f"- {h.get('title')} :: {h.get('url') or h.get('href')} :: {h.get('snippet')}" for h in hits])
        except Exception:
            hints = ""
        hint_block = f"\n\n## 参考ヒント(検索結果)\n{hints}\n" if hints else ""

        _log(f"Hints: {len(hits) if hints else 0} items")
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
                    collected.append(data)
                    write_operation_log(operation_log_filename, "INFO", "IngestMode", f"Collected payload from {name} (round {r+1}).")
                    _log(f"Collected JSON from {name}")
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
                        preview = str(resp or "").replace("\n", " ")[:200]
                        if preview:
                            _log(f"Preview: {preview}")
            except asyncio.TimeoutError:
                write_operation_log(operation_log_filename, "WARNING", "IngestMode", f"Timeout from {name} (round {r+1}).")
                _log(f"Timeout from {name}")
            except Exception as e:
                write_operation_log(operation_log_filename, "ERROR", "IngestMode", f"Error from {name} (round {r+1}): {e}")
                _log(f"Error from {name}: {e}")

    merged = merge_payloads(collected)

    if ingest_payload is None:
        write_operation_log(operation_log_filename, "ERROR", "IngestMode", "KB.ingest not available; skipping DB registration.")
    else:
        try:
            ingest_payload(os.path.abspath(db_path), merged)
            write_operation_log(operation_log_filename, "INFO", "IngestMode", f"Registered to DB: {db_path}")
            _log("Registered to DB")
        except Exception as e:
            write_operation_log(operation_log_filename, "ERROR", "IngestMode", f"Failed to register DB: {e}")
            _log(f"Failed to register DB: {e}")

    return merged
