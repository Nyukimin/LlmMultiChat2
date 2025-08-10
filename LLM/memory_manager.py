import os
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.messages import SystemMessage

from log_manager import read_log, write_operation_log


_SESSION_THREAD_COUNTER: Dict[str, int] = {}


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _derive_session_id_from_log(log_filename: str) -> str:
    # e.g., LLM/logs/conversation_20250101-121212.log -> 20250101-121212
    base = os.path.basename(log_filename)
    name, _ext = os.path.splitext(base)
    if name.startswith("conversation_"):
        return name.replace("conversation_", "")
    return name


def _next_thread_id_for_session(session_id: str) -> int:
    _SESSION_THREAD_COUNTER.setdefault(session_id, 0)
    _SESSION_THREAD_COUNTER[session_id] += 1
    return _SESSION_THREAD_COUNTER[session_id]


async def persist_thread_from_log(
    manager: Any,
    log_filename: str,
    operation_log_filename: str,
    domain: Optional[str] = None,
) -> None:
    """
    現在の会話ログから要約とキーワードを生成し、JSONL（LLM/logs/memory/session_threads.jsonl）へ永続化する。

    - 依存追加なしで実現（埋め込みはAPIキーがある場合のみ任意で付与）
    - thread_id はセッションごとにインクリメント
    - session_id はログファイル名から導出
    """
    try:
        # 会話ログのディレクトリ配下に "memory" サブディレクトリを作成し、そこへ永続化
        log_dir = os.path.dirname(os.path.abspath(log_filename))
        memory_dir = os.path.join(log_dir, "memory")
        _ensure_dir(memory_dir)
        jsonl_path = os.path.join(memory_dir, "session_threads.jsonl")

        session_id = _derive_session_id_from_log(log_filename)
        thread_id = _next_thread_id_for_session(session_id)

        full_log_text = read_log(log_filename)
        if not full_log_text:
            write_operation_log(operation_log_filename, "WARNING", "MemoryManager", "No log content to persist.")
            return

        # 要約/キーワード生成: 先頭キャラクターのLLMを利用
        first_char = manager.get_character_names()[0]
        llm = manager.get_llm(first_char)
        if llm is None:
            write_operation_log(operation_log_filename, "ERROR", "MemoryManager", "No LLM available to summarize.")
            return

        system_prompt = (
            "あなたは会話の要約者です。以下の会話ログの要点を200文字以内で日本語で要約し、"
            "関連するキーワードを5個抽出してください。必ずJSONで出力し、"
            "他の文字を含めず、次の形式に厳密に従ってください:\n"
            "{\"summary\": string, \"keywords\": [string, string, string, string, string]}\n\n"
            "会話ログ:\n" + full_log_text
        )

        summary = ""
        keywords: List[str] = []

        try:
            response = await llm.ainvoke([SystemMessage(content=system_prompt)])
            content = getattr(response, "content", str(response))
            # JSON抽出（安全のため前後空白除去）
            content = content.strip()
            data = json.loads(content)
            summary = str(data.get("summary", "")).strip()
            kws = data.get("keywords", [])
            if isinstance(kws, list):
                keywords = [str(k).strip() for k in kws if str(k).strip()]
        except Exception as e:  # フォールバック: 簡易要約
            write_operation_log(operation_log_filename, "WARNING", "MemoryManager", f"Failed to parse JSON summary: {e}")
            # 簡易フォールバック: 末尾数行を要約相当として保存
            tail = "\n".join(full_log_text.splitlines()[-10:])
            summary = tail[:200]
            keywords = []

        # 追加メタ情報
        now_iso = datetime.utcnow().isoformat() + "Z"
        record: Dict[str, Any] = {
            "session_id": session_id,
            "thread_id": thread_id,
            "ts_start": now_iso,
            "ts_end": now_iso,
            "domain": domain or "generic",
            "summary": summary,
            "keywords": keywords,
            "embedding": None,
            "full_log": full_log_text,
        }

        # 任意: OpenAI Embeddings（APIキーがある場合のみ）
        try:
            from os import getenv
            if getenv("OPENAI_API_KEY"):
                from langchain_openai import OpenAIEmbeddings
                emb = OpenAIEmbeddings()
                vec = emb.embed_query(summary or full_log_text[:1000])
                record["embedding"] = vec
        except Exception as e:
            write_operation_log(operation_log_filename, "WARNING", "MemoryManager", f"Embedding skipped: {e}")

        # JSONLへ追記
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        write_operation_log(operation_log_filename, "INFO", "MemoryManager", f"Persisted thread {thread_id} for session {session_id}.")

    except Exception as e:
        write_operation_log(operation_log_filename, "ERROR", "MemoryManager", f"Unexpected error persisting memory: {e}")


