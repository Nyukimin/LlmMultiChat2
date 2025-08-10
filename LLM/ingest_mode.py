import os
import json
import re
import asyncio
from typing import Any, Dict, List, Optional, Callable

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
- もし情報が見つからない場合でも、空配列を持つJSONを返す（例: persons:[], works:[] ...）。
- JSONは次のマーカーに必ず挟むこと。
  <<<JSON_START>>>
  {{ ... }}
  <<<JSON_END>>>

スキーマ:
{{
  "persons": [ {{ "name": "", "aliases": [""] }} ],
  "works": [ {{ "title": "", "category": "映画", "year": 2024, "subtype": null, "summary": null }} ],
  "credits": [ {{ "work": "", "person": "", "role": "actor", "character": null }} ],
  "external_ids": [ {{ "entity": "work", "name": "", "source": "wikipedia", "value": "", "url": null }} ],
  "unified": [ {{ "name": "", "work": "", "relation": "adaptation" }} ],
  "note": null
}}
"""

def extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = text.strip()
    # まずはマーカー優先
    start_tag = "<<<JSON_START>>>"
    end_tag = "<<<JSON_END>>>"
    if start_tag in s and end_tag in s:
        try:
            frag = s.split(start_tag, 1)[1].split(end_tag, 1)[0]
            return json.loads(frag)
        except Exception:
            pass
    # 最初の { から最後の } までを抜く簡易抽出
    m1 = s.find("{")
    m2 = s.rfind("}")
    if m1 == -1 or m2 == -1 or m2 <= m1:
        return None
    frag = s[m1 : m2 + 1]
    try:
        return json.loads(frag)
    except Exception:
        # フォールバック: クォート崩れ等を緩和（ダブルクォート化は危険なのでここでは行わない）
        return None


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
    seeds: List[str] = []
    base_topic = topic
    _log(f"Start ingest: topic='{topic}', domain='{domain}', rounds={rounds}, strict={strict}")
    for r in range(max(1, rounds)):
        _log(f"Round {r+1}/{max(1, rounds)}")
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
                t = base_topic
                if expand and seeds:
                    t = base_topic + " " + " ".join(list(dict.fromkeys(seeds))[:5])
                # DuckDuckGo 検索を先に実施し、上位結果をヒントとして同梱
                try:
                    hits = search_text(f"{t} site:.jp", region="jp-jp", max_results=8, safesearch="moderate")
                    hints = "\n".join([f"- {h['title']} :: {h['url']} :: {h['snippet']}" for h in hits])
                except Exception as _e:
                    hints = ""
                hint_block = f"\n\n## 参考ヒント(検索結果)\n{hints}\n" if hints else ""
                resp = await asyncio.wait_for(llm.ainvoke(system_prompt, f"収集対象: {t}"), timeout=60.0)
                # 検索ヒント併用で再試行（STRICT優先）
                data = extract_json(resp)
                if not data and hints:
                    resp_h = await asyncio.wait_for(llm.ainvoke(system_prompt, f"収集対象: {t}{hint_block}"), timeout=60.0)
                    data = extract_json(resp_h)
                if isinstance(data, dict):
                    collected.append(data)
                    write_operation_log(operation_log_filename, "INFO", "IngestMode", f"Collected payload from {name} (round {r+1}).")
                    _log(f"Collected JSON from {name}")
                    if expand:
                        # 次ラウンド用シード抽出
                        for p in (data.get("persons") or []):
                            n = (p.get("name") or "").strip()
                            if n:
                                seeds.append(n)
                        for w in (data.get("works") or []):
                            n = (w.get("title") or "").strip()
                            if n:
                                seeds.append(n)
                else:
                    # リトライ（STRICT再試行）
                    if not strict:
                        sp = f"## 収集モード(STRICT-RETRY)\n{extractor}\n\nJSONのみを返してください。先頭から {{ と }} までの有効JSONのみ。"
                        resp2 = await asyncio.wait_for(llm.ainvoke(sp, f"収集対象: {t}"), timeout=60.0)
                        data2 = extract_json(resp2)
                        if isinstance(data2, dict):
                            collected.append(data2)
                            write_operation_log(operation_log_filename, "INFO", "IngestMode", f"Collected payload (retry) from {name} (round {r+1}).")
                            _log(f"Collected JSON (retry) from {name}")
                        else:
                            write_operation_log(operation_log_filename, "WARNING", "IngestMode", f"Non-JSON from {name} (round {r+1}).")
                            _log(f"Non-JSON from {name}")
                    else:
                        write_operation_log(operation_log_filename, "WARNING", "IngestMode", f"Non-JSON from {name} (round {r+1}).")
                        _log(f"Non-JSON from {name}")
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
