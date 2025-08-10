import os
import json
import re
import asyncio
from typing import Any, Dict, List, Optional

from character_manager import CharacterManager
from llm_factory import LLMFactory
from llm_instance_manager import LLMInstanceManager
from log_manager import write_operation_log

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
    return (
        "あなたは事実収集アシスタントです。以下の対象ドメインに限定して、確度の高い事実のみを"
        "JSONで抽出してください。推測は避け、未確定情報はnoteに記載してください。\n\n"
        f"対象ドメイン: {domain}\n\n"
        "必ず次のスキーマのJSONだけを出力します（他の文字は出力しない）。\n"
        "{\n"
        "  \"persons\": [ { \"name\": str, \"aliases\": [str] } ],\n"
        "  \"works\": [ { \"title\": str, \"category\": str, \"year\": int|null, \"subtype\": str|null, \"summary\": str|null } ],\n"
        "  \"credits\": [ { \"work\": str, \"person\": str, \"role\": str, \"character\": str|null } ],\n"
        "  \"external_ids\": [ { \"entity\": \"work|person\", \"name\": str, \"source\": str, \"value\": str, \"url\": str|null } ],\n"
        "  \"unified\": [ { \"name\": str, \"work\": str, \"relation\": str } ],\n"
        "  \"note\": str|null\n"
        "}\n\n"
        "role の例: actor/voice/director/author/screenplay/composer/lyricist 等。"
    )


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = text.strip()
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


async def run_ingest_mode(topic: str, domain: str, rounds: int, db_path: str) -> Dict[str, Any]:
    ensure_dirs()
    log_filename = os.path.join(BASE_DIR, "logs", "ingest_conversation.log")
    operation_log_filename = os.path.join(BASE_DIR, "..", "logs", "operation_ingest.log")

    manager = CharacterManager(log_filename, operation_log_filename)

    extractor = build_extractor_prompt(domain)
    collected: List[Dict[str, Any]] = []

    characters = manager.get_character_names()
    for r in range(max(1, rounds)):
        for name in characters:
            persona = manager.get_persona_prompt(name)
            system_prompt = f"{persona}\n\n## 収集モード\n{extractor}"
            llm = manager.get_llm(name)
            if llm is None:
                continue
            try:
                resp = await asyncio.wait_for(llm.ainvoke(system_prompt, f"収集対象: {topic}"), timeout=60.0)
                data = extract_json(resp)
                if isinstance(data, dict):
                    collected.append(data)
                    write_operation_log(operation_log_filename, "INFO", "IngestMode", f"Collected payload from {name} (round {r+1}).")
                else:
                    write_operation_log(operation_log_filename, "WARNING", "IngestMode", f"Non-JSON from {name} (round {r+1}).")
            except asyncio.TimeoutError:
                write_operation_log(operation_log_filename, "WARNING", "IngestMode", f"Timeout from {name} (round {r+1}).")
            except Exception as e:
                write_operation_log(operation_log_filename, "ERROR", "IngestMode", f"Error from {name} (round {r+1}): {e}")

    merged = merge_payloads(collected)

    if ingest_payload is None:
        write_operation_log(operation_log_filename, "ERROR", "IngestMode", "KB.ingest not available; skipping DB registration.")
    else:
        try:
            ingest_payload(os.path.abspath(db_path), merged)
            write_operation_log(operation_log_filename, "INFO", "IngestMode", f"Registered to DB: {db_path}")
        except Exception as e:
            write_operation_log(operation_log_filename, "ERROR", "IngestMode", f"Failed to register DB: {e}")

    return merged
