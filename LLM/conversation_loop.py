import asyncio
import sqlite3
import re
import traceback
import uuid
from datetime import datetime
from fastapi import WebSocket
import yaml
import os
import sys
from typing import Dict, List, Dict as TDict
from typing import Optional
import random

from character_manager import CharacterManager
from status_manager import update_status, update_all_statuses
from log_manager import write_log, get_formatted_conversation_history, write_operation_log
from memory_manager import persist_thread_from_log
from next_speaker_resolver import resolve_next_speaker, NextPolicy
try:
    from ingest_mode import run_ingest_mode as _kb_run_ingest  # type: ignore
except Exception:
    _kb_run_ingest = None  # type: ignore


def safe_brace_format(template: str, **kwargs) -> str:
    """
    安全な簡易フォーマッタ。
    - 置換対象は {identifier} のみ（英数字とアンダースコア）。
    - それ以外（例: JSON の {"next": ...} や波括弧を含む構造）は無視してそのまま残す。
    """
    import re as _re
    pattern = _re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

    def _repl(match):
        key = match.group(1)
        if key in kwargs:
            return str(kwargs[key])
        # 未定義キーは元のまま残す（KeyErrorを避ける）
        return match.group(0)

    return pattern.sub(_repl, template)


def shorten_text(text: str, max_sentences: int = 2, max_chars: int = 140) -> str:
    """日本語向けに簡易短縮: 文末記号で2文まで、全体でmax_charsまでに切り詰める。"""
    if not text:
        return text
    s = str(text).strip()
    # 文分割（簡易）
    import re as _re
    sentences = _re.split(r"(?<=[。.!?！？])\s*", s)
    clipped = "".join(sentences[:max_sentences]).strip()
    if len(clipped) > max_chars:
        clipped = clipped[:max_chars].rstrip()
    return clipped


def remove_preamble(text: str) -> str:
    """挨拶・導入の定型句を除去して要点を先頭に出す。空になりそうな場合は元を返す。"""
    if not text:
        return text
    original = text
    s = str(text).strip()
    import re as _re
    patterns = [
        r"^おはようございます[！!。\s]*",
        r"^こんにちは[！!。\s]*",
        r"^こんばんは[！!。\s]*",
        r"^(本日|今日は|今回|ここでは).{0,15}について(お知らせ|ご案内)いたします[。！!\s]*",
        r"^(本日|今日は|今回|ここでは).{0,15}について(お知らせ|ご案内)します[。！!\s]*",
        r"^ご連絡いたします[。！!\s]*",
    ]
    for pat in patterns:
        s = _re.sub(pat, "", s)
    # 先頭に残った読点/句読点/記号を除去
    s = s.lstrip(" 、。!！?？・:;　\t")
    s = s.strip()
    return s or original


def ensure_sentence_complete(text: str) -> str:
    """末尾が句点/終止記号で終わるように補完する。"""
    if not text:
        return text
    s = str(text).strip()
    if not s:
        return s
    if s[-1] in ("。", "！", "!", "？", "?"):
        return s
    return s + "。"


def _load_auto_loops_from_config(default_value: int) -> int:
    """LLM/config.yaml の conversation.auto_loops を読み込む（存在しなければ既定値）。"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, 'config.yaml')
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        conv = cfg.get('conversation') or {}
        val = conv.get('auto_loops')
        if isinstance(val, int) and val >= 0:
            return val
    except Exception:
        pass
    return default_value

def load_global_rules(rules_path: str = None) -> Dict:
    """LLM/global_rules.yaml をこのファイルの位置からの絶対パスで確実に読み込む"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        resolved_path = rules_path or os.path.join(base_dir, 'global_rules.yaml')
        with open(resolved_path, 'r', encoding='utf-8') as file:
            return yaml.safe_load(file)
    except Exception as e:
        print(f"Warning: Could not load global rules from {rules_path or resolved_path}. Error: {e}")
        return {}

# ===== kbjson 抽出/正規化/登録の準備 =====
# ingest_mode の抽出/正規化関数を再利用
try:
    from ingest_mode import extract_json as _extract_kbjson, _normalize_extracted_payload as _normalize_kbjson  # type: ignore
except Exception:
    _extract_kbjson = None  # type: ignore
    _normalize_kbjson = None  # type: ignore

# KB モジュールの解決と登録関数
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_KB_DIR = os.path.abspath(os.path.join(_BASE_DIR, '..', 'KB'))
if _KB_DIR not in sys.path:
    sys.path.append(_KB_DIR)
try:
    from ingest import ingest_payload as _kb_ingest_payload  # type: ignore
except Exception:
    _kb_ingest_payload = None  # type: ignore


def _resolve_kb_db_path_from_kb_config() -> str:
    """KB/config.yaml の db_path を解決し、絶対パスで返す。存在しない場合は既定 KB/media.db。
    """
    try:
        kb_cfg_path = os.path.join(_KB_DIR, 'config.yaml')
        with open(kb_cfg_path, 'r', encoding='utf-8') as f:
            kb_cfg = yaml.safe_load(f) or {}
        db_path = kb_cfg.get('db_path') or 'media.db'
        if not os.path.isabs(db_path):
            db_path = os.path.abspath(os.path.join(_KB_DIR, db_path))
        return db_path
    except Exception:
        return os.path.abspath(os.path.join(_KB_DIR, 'media.db'))


# ==== KB ユーティリティ（会話コマンド用） ====
_KB_ALLOWED_TABLES = {
    "person", "work", "credit", "alias", "external_id",
    "category", "unified_work", "unified_work_member", "fts"
}

def _kb_list_tables(db_path: str) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

def _kb_table_schema(db_path: str, table: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def _kb_count_table(db_path: str, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
        return int(cur.fetchone()[0])
    finally:
        conn.close()

def _kb_find_persons(db_path: str, keyword: str, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT id, name FROM person WHERE name LIKE ? ORDER BY id DESC LIMIT ?", (f"%{keyword}%", limit))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def _kb_find_works(db_path: str, keyword: str, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT id, title, year FROM work WHERE title LIKE ? ORDER BY year DESC, id DESC LIMIT ?", (f"%{keyword}%", limit))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def _kb_fts(db_path: str, q: str, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT kind, ref_id, snippet(fts,1,'[',']','...',10) AS snippet FROM fts WHERE fts MATCH ? LIMIT ?", (q, limit))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def _kb_person_detail(db_path: str, pid: int) -> Optional[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT id, name, kana, birth_year, death_year, note FROM person WHERE id=?", (pid,))
        r = cur.fetchone()
        return dict(r) if r else None
    finally:
        conn.close()

def _kb_person_credits(db_path: str, pid: int, limit: int = 50) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT w.id AS work_id, w.title, w.year, c.role, c.character
            FROM credit c JOIN work w ON w.id=c.work_id
            WHERE c.person_id=?
            ORDER BY w.year IS NULL, w.year, w.title
            LIMIT ?
            """,
            (pid, limit)
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def _kb_work_detail(db_path: str, wid: int) -> Optional[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT w.id, w.title, w.year, c.name AS category
            FROM work w JOIN category c ON c.id=w.category_id
            WHERE w.id=?
            """,
            (wid,)
        )
        r = cur.fetchone()
        return dict(r) if r else None
    finally:
        conn.close()

def _kb_work_cast(db_path: str, wid: int, limit: int = 100) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT p.id AS person_id, p.name, c.role, c.character
            FROM credit c JOIN person p ON p.id=c.person_id
            WHERE c.work_id=?
            ORDER BY CASE c.role WHEN 'director' THEN 0 WHEN 'actor' THEN 1 ELSE 9 END, p.name
            LIMIT ?
            """,
            (wid, limit)
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def _load_kb_ingest_settings() -> tuple:
    """LLM/config.yaml から kb.ingest_mode と db_path を読み出し、(enabled, db_path) を返す。"""
    try:
        llm_cfg_path = os.path.join(_BASE_DIR, 'config.yaml')
        with open(llm_cfg_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        kb_cfg = cfg.get('kb') or {}
        enabled = bool(kb_cfg.get('ingest_mode', False))
        db_path = kb_cfg.get('db_path')
        if db_path:
            if not os.path.isabs(db_path):
                db_path = os.path.abspath(os.path.join(_BASE_DIR, '..', db_path))
        else:
            db_path = _resolve_kb_db_path_from_kb_config()
        return enabled, db_path
    except Exception:
        return False, _resolve_kb_db_path_from_kb_config()

async def process_character_turn(
    websocket: WebSocket,
    manager: CharacterManager,
    character_name: str,
    last_message: str,
    log_filename: str,
    operation_log_filename: str,
    global_rules: Dict
):
    llm = manager.get_llm(character_name)
    if not llm:
        return None, ""

    write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Processing response for {character_name}.")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答処理を開始")
    await update_status(websocket, character_name, "THINKING", log_filename, operation_log_filename)

    persona_prompt = manager.get_persona_prompt(character_name)
    if not persona_prompt:
        persona_prompt = "あなたはAIです。日本語で応答してください。"

    conversation_log = get_formatted_conversation_history(log_filename)
    other_characters_list = [name for name in manager.get_character_names() if name != character_name]
    other_characters = ", ".join(other_characters_list)

    prompt_template = global_rules.get("prompt_template", "{persona_prompt}")
    response_constraints = safe_brace_format(global_rules.get("response_constraints", ""), character_name=character_name)
    flow_rules = safe_brace_format(global_rules.get("flow_rules", ""), other_characters=other_characters)

    final_prompt = safe_brace_format(
        prompt_template,
        character_name=character_name,
        persona_prompt=persona_prompt,
        response_constraints=response_constraints,
        flow_rules=flow_rules,
        other_characters=other_characters,
        conversation_log=conversation_log,
    )
    
    system_prompt = final_prompt
    user_message = last_message

    # 呼び出しメタ情報（モデル等）を特定
    char_cfg = next((c for c in manager.list_characters() if c.get("display_name", c.get("name")) == character_name or c.get("name") == character_name), None)
    provider = (char_cfg or {}).get("provider", "")
    model = (char_cfg or {}).get("model", "")
    base_url = (char_cfg or {}).get("base_url", "")

    # 相関IDでリクエスト/レスポンスをひも付け
    req_id = uuid.uuid4().hex[:8]
    write_operation_log(
        operation_log_filename,
        "INFO",
        "LLMCall",
        f"REQ {req_id} -> speaker={character_name}, provider={provider}, model={model}, base_url={base_url}, system_len={len(final_prompt)}, user_len={len(last_message or '')}"
    )
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答を生成中... (req={req_id})")

    response_text = ""
    raw_response_text: Optional[str] = None
    try:
        # 応答生成に上限時間を設け、ハング/長考を防ぐ
        response_text = await asyncio.wait_for(llm.ainvoke(system_prompt, user_message), timeout=60.0)
        response_text = str(response_text or "")
        raw_response_text = response_text

        # [Next: ...]タグを抽出する前に、<think>タグとその内容を削除
        response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
        # 表示前に前置きを除去→短縮（未完了感の軽減と要点提示）
        response_text = remove_preamble(response_text)
        response_text = shorten_text(response_text, max_sentences=2, max_chars=160)
        response_text = ensure_sentence_complete(response_text)
        write_log(log_filename, character_name, response_text)
        preview_text = (response_text or "")[:120].replace("\n", " ")
        write_operation_log(
            operation_log_filename,
            "INFO",
            "LLMCall",
            f"RESP {req_id} <- speaker={character_name}, chars={len(response_text)}, preview={preview_text}"
        )
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答を受け取りました: {response_text[:50]}...")
    except asyncio.TimeoutError:
        write_operation_log(operation_log_filename, "WARNING", "LLMCall", f"TIMEOUT {req_id} speaker={character_name} after 60s")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答がタイムアウトしました (req={req_id})")
        response_text = "応答に時間がかかっています。"
    except Exception as e:
        error_details = traceback.format_exc()
        write_operation_log(operation_log_filename, "ERROR", "LLMCall", f"ERROR {req_id} speaker={character_name}: {e}")
        write_operation_log(operation_log_filename, "ERROR", "ConversationLoop", f"Error invoking LLM for {character_name}: {e}\n{error_details}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答生成中にエラーが発生しました: {e} (req={req_id})")
        response_text = "応答生成中にエラーが発生しました。"

    # 表示用テキストから[Next: ...]タグと {"next":"..."} 片を削除
    display_text = re.sub(r'\[Next:.*?\]', '', response_text, flags=re.IGNORECASE)
    display_text = re.sub(r'\{\s*"next"\s*:\s*".*?"\s*\}', '', display_text, flags=re.IGNORECASE).strip()

    # 空応答でもUIに可視化するためプレースホルダを送る
    send_text = display_text if display_text else "（応答なし）"
    try:
        await websocket.send_json({
            "type": "message",
            "speaker": character_name,
            "text": send_text
        })
        write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Response sent for {character_name} (len={len(display_text)}).")
        if not display_text:
            write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Displayed placeholder for empty response from {character_name}.")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答を送信しました")
    except Exception as e:
        error_details = traceback.format_exc()
        write_operation_log(operation_log_filename, "ERROR", "ConversationLoop", f"Error sending response for {character_name}: {e}\n{error_details}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答送信中にエラーが発生しました: {e}")
    
    await update_status(websocket, character_name, "IDLE", log_filename, operation_log_filename)
    await asyncio.sleep(1)

    # ===== kbjson 自動取り込み =====
    try:
        ingest_enabled, kb_db_path = _load_kb_ingest_settings()
        if ingest_enabled and raw_response_text and _extract_kbjson and _normalize_kbjson and _kb_ingest_payload:
            data = _extract_kbjson(raw_response_text)
            if isinstance(data, dict):
                payload = _normalize_kbjson(data)
                if any(len(payload.get(k) or []) for k in ("persons", "works", "credits", "external_ids", "unified")):
                    try:
                        _kb_ingest_payload(kb_db_path, payload)
                        write_operation_log(operation_log_filename, "INFO", "KBIngest", f"KB registered from response (persons={len(payload.get('persons') or [])}, works={len(payload.get('works') or [])}).")
                        try:
                            await websocket.send_json({"type": "message", "speaker": "System", "text": "KBに登録しました。"})
                        except Exception:
                            pass
                    except Exception as e:
                        write_operation_log(operation_log_filename, "WARNING", "KBIngest", f"KB register failed: {e}")
                        try:
                            await websocket.send_json({"type": "message", "speaker": "System", "text": "KB登録に失敗しました。"})
                        except Exception:
                            pass
            else:
                write_operation_log(operation_log_filename, "INFO", "KBIngest", "No kbjson detected in response.")
    except Exception as e:
        write_operation_log(operation_log_filename, "WARNING", "KBIngest", f"kbjson handler error: {e}")

    # 次話者解決: internal_id ベース
    registry: List[TDict[str, str]] = []
    for c in manager.list_characters():
        registry.append({
            "internal_id": c.get("name"),
            "display_name": c.get("display_name", c.get("name")),
            "short_name": c.get("short_name", ""),
        })

    # 現在の internal_id を display→internal 変換
    current_internal_id = None
    for c in registry:
        if c["display_name"] == character_name:
            current_internal_id = c["internal_id"]
            break
    if current_internal_id is None and registry:
        current_internal_id = registry[0]["internal_id"]

    policy = NextPolicy(allow_self_nomination=False, fallback="round_robin", fuzzy_threshold=0.85)
    next_internal_id, reason, extracted, normalized = resolve_next_speaker(
        response_text, current_internal_id, registry, policy, operation_log_filename
    )

    # internal_id → display_name へ戻す
    if next_internal_id:
        for c in registry:
            if c["internal_id"] == next_internal_id:
                return c["display_name"], response_text

    write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "No valid next speaker resolved. Autonomous loop ending.")
    return None, response_text

async def conversation_loop(websocket: WebSocket, manager: CharacterManager, log_filename: str, operation_log_filename: str):
    from initial_status_setter import set_initial_statuses
    
    global_rules = load_global_rules()
    # 既定はグローバルルール、優先は config.yaml の conversation.auto_loops
    max_turns = global_rules.get("max_autonomous_turns", 3)
    max_turns = _load_auto_loops_from_config(max_turns)

    await set_initial_statuses(websocket, manager, log_filename, operation_log_filename)
    # セッション内フラグ: 情報検索モード
    info_search_mode: bool = False

    try:
        while True:
            write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "Waiting for user input.")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ユーザー入力を待機中...")
            
            user_query = await websocket.receive_text()
            write_log(log_filename, "USER", user_query)
            write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"User input received: {user_query}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ユーザー入力を受け取りました: {user_query}")
            # コマンド処理: /kbauto on|off
            try:
                m = re.match(r"^\s*/kbauto\s+(on|off)\s*$", user_query, re.IGNORECASE)
            except Exception:
                m = None
            if m:
                val = m.group(1).lower()
                info_search_mode = (val == "on")
                try:
                    await websocket.send_json({"type": "message", "speaker": "System", "text": f"情報検索モードを{('ON' if info_search_mode else 'OFF')}にしました。"})
                except Exception:
                    pass
                # コマンドは会話に使わない→次の入力を待つ
                continue
            # クライアントからの初期通知（/kbauto on|off の直後に通常メッセージが来るため、モード反映漏れを防止）
            if user_query.strip() in ("/kbauto on", "/kbauto off"):
                continue

            # コマンド処理: /kbcheck persons|works [limit]
            try:
                m2 = re.match(r"^\s*/kbcheck\s+(persons|works)(?:\s+(\d+))?\s*$", user_query, re.IGNORECASE)
            except Exception:
                m2 = None
            if m2:
                kind = m2.group(1).lower()
                try:
                    limit = int(m2.group(2)) if m2.group(2) else 10
                except Exception:
                    limit = 10
                limit = max(1, min(limit, 50))
                db_path = _resolve_kb_db_path_from_kb_config()
                try:
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    with conn:
                        if kind == "persons":
                            cur = conn.execute(
                                """
                                SELECT p.id, p.name
                                FROM person p
                                LEFT JOIN credit c ON c.person_id = p.id
                                WHERE c.person_id IS NULL
                                ORDER BY p.id DESC
                                LIMIT ?
                                """,
                                (limit,)
                            )
                            rows = cur.fetchall()
                            if rows:
                                lines = [f"不足人物候補 {len(rows)}件"]
                                for r in rows:
                                    lines.append(f"- {r['name']} (id:{r['id']})")
                                msg = "\n".join(lines)
                            else:
                                msg = "不足人物は見つかりませんでした。"
                        else:
                            cur = conn.execute(
                                """
                                SELECT w.id, w.title
                                FROM work w
                                LEFT JOIN credit c ON c.work_id = w.id
                                WHERE c.work_id IS NULL
                                ORDER BY w.id DESC
                                LIMIT ?
                                """,
                                (limit,)
                            )
                            rows = cur.fetchall()
                            if rows:
                                lines = [f"不足作品候補 {len(rows)}件"]
                                for r in rows:
                                    lines.append(f"- {r['title']} (id:{r['id']})")
                                msg = "\n".join(lines)
                            else:
                                msg = "不足作品は見つかりませんでした。"
                except Exception as e:
                    msg = f"KBチェック中にエラーが発生しました: {e}"
                try:
                    await websocket.send_json({"type": "message", "speaker": "ルミナ", "text": msg})
                except Exception:
                    pass
                continue

            # 一般的なDBコマンド
            # /kbtables : テーブル一覧
            if user_query.strip().lower() == "/kbtables":
                try:
                    db_path = _resolve_kb_db_path_from_kb_config()
                    tables = _kb_list_tables(db_path)
                    msg = "テーブル: " + ", ".join(tables)
                except Exception as e:
                    msg = f"エラー: {e}"
                await websocket.send_json({"type": "message", "speaker": "ルミナ", "text": msg})
                continue

            # /kbschema <table>
            try:
                m3 = re.match(r"^\s*/kbschema\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", user_query)
            except Exception:
                m3 = None
            if m3:
                table = m3.group(1)
                try:
                    db_path = _resolve_kb_db_path_from_kb_config()
                    if table not in _KB_ALLOWED_TABLES:
                        raise ValueError("対象外のテーブルです")
                    cols = _kb_table_schema(db_path, table)
                    lines = [f"schema {table}"]
                    for c in cols:
                        lines.append(f"- {c['name']} ({c['type']})" + (" pk" if c.get('pk') else ""))
                    msg = "\n".join(lines)
                except Exception as e:
                    msg = f"エラー: {e}"
                await websocket.send_json({"type": "message", "speaker": "ルミナ", "text": msg})
                continue

            # /kbcount <table>
            try:
                m4 = re.match(r"^\s*/kbcount\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", user_query)
            except Exception:
                m4 = None
            if m4:
                table = m4.group(1)
                try:
                    db_path = _resolve_kb_db_path_from_kb_config()
                    if table not in _KB_ALLOWED_TABLES:
                        raise ValueError("対象外のテーブルです")
                    cnt = _kb_count_table(db_path, table)
                    msg = f"{table}: {cnt}件"
                except Exception as e:
                    msg = f"エラー: {e}"
                await websocket.send_json({"type": "message", "speaker": "ルミナ", "text": msg})
                continue

            # /kbfind person <keyword> [limit]
            try:
                m5 = re.match(r"^\s*/kbfind\s+person\s+(.+?)(?:\s+(\d+))?\s*$", user_query, re.IGNORECASE)
            except Exception:
                m5 = None
            if m5:
                kw = m5.group(1).strip()
                limit = int(m5.group(2)) if m5.group(2) else 10
                limit = max(1, min(limit, 50))
                db_path = _resolve_kb_db_path_from_kb_config()
                try:
                    rows = _kb_find_persons(db_path, kw, limit)
                    if rows:
                        msg = "\n".join([f"- {r['name']} (id:{r['id']})" for r in rows])
                    else:
                        msg = "該当なし"
                except Exception as e:
                    msg = f"エラー: {e}"
                await websocket.send_json({"type": "message", "speaker": "ルミナ", "text": msg})
                continue

            # /kbfind work <keyword> [limit]
            try:
                m6 = re.match(r"^\s*/kbfind\s+work\s+(.+?)(?:\s+(\d+))?\s*$", user_query, re.IGNORECASE)
            except Exception:
                m6 = None
            if m6:
                kw = m6.group(1).strip()
                limit = int(m6.group(2)) if m6.group(2) else 10
                limit = max(1, min(limit, 50))
                db_path = _resolve_kb_db_path_from_kb_config()
                try:
                    rows = _kb_find_works(db_path, kw, limit)
                    if rows:
                        msg = "\n".join([f"- {r['title']} (id:{r['id']})" + (f" ({r['year']})" if r.get('year') else '') for r in rows])
                    else:
                        msg = "該当なし"
                except Exception as e:
                    msg = f"エラー: {e}"
                await websocket.send_json({"type": "message", "speaker": "ルミナ", "text": msg})
                continue

            # /kb detail person <id>  or  /kb detail work <id>
            try:
                m7 = re.match(r"^\s*/kb\s+detail\s+(person|work)\s+(\d+)\s*$", user_query, re.IGNORECASE)
            except Exception:
                m7 = None
            if m7:
                kind = m7.group(1).lower()
                rid = int(m7.group(2))
                db_path = _resolve_kb_db_path_from_kb_config()
                try:
                    if kind == 'person':
                        d = _kb_person_detail(db_path, rid)
                        cr = _kb_person_credits(db_path, rid, 30)
                        if d:
                            lines = [f"{d['name']} (id:{d['id']})", f"kana={d.get('kana')}", f"birth={d.get('birth_year')} death={d.get('death_year')}"]
                            if d.get('note'):
                                lines.append((d.get('note') or '')[:160])
                            if cr:
                                lines.append('--- credits ---')
                                for c in cr[:30]:
                                    lines.append(f"- {c['title']}{(' ('+str(c['year'])+')') if c.get('year') else ''} [{c['role']}]" + (f" as {c['character']}" if c.get('character') else ''))
                            msg = "\n".join(lines)
                        else:
                            msg = "該当なし"
                    else:
                        d = _kb_work_detail(db_path, rid)
                        cast = _kb_work_cast(db_path, rid, 50)
                        if d:
                            lines = [f"{d['title']} (id:{d['id']})" + (f" ({d['year']})" if d.get('year') else ''), f"category={d.get('category')}"]
                            if cast:
                                lines.append('--- cast/staff ---')
                                for c in cast[:50]:
                                    lines.append(f"- {c['name']} [{c['role']}]" + (f" as {c['character']}" if c.get('character') else ''))
                            msg = "\n".join(lines)
                        else:
                            msg = "該当なし"
                except Exception as e:
                    msg = f"エラー: {e}"
                await websocket.send_json({"type": "message", "speaker": "ルミナ", "text": msg})
                continue
            
            await update_all_statuses(websocket, manager.get_character_names(), "IDLE", log_filename, operation_log_filename)
            
            # 情報検索モード: ルミナが先にKB収集を実況（MVP: ユーザー入力をトピックに1回だけ）
            if info_search_mode and _kb_run_ingest is not None:
                try:
                    topic = (user_query or "").strip()
                    if topic:
                        await update_status(websocket, "ルミナ", "THINKING", log_filename, operation_log_filename)
                        await websocket.send_json({"type": "message", "speaker": "ルミナ", "text": f"{topic} の情報、KBで調べるね。"})
                        await asyncio.sleep(1.2)
                        db_path = _resolve_kb_db_path_from_kb_config()
                        res = await _kb_run_ingest(topic, "映画", 1, db_path)  # type: ignore
                        persons = len(res.get("persons") or [])
                        works = len(res.get("works") or [])
                        await asyncio.sleep(0.6)
                        await websocket.send_json({"type": "message", "speaker": "ルミナ", "text": f"{topic} は登録・更新できたよ。人物 {persons} / 作品 {works} 件なんだって。"})
                        await update_status(websocket, "ルミナ", "IDLE", log_filename, operation_log_filename)
                except Exception as e:
                    write_operation_log(operation_log_filename, "WARNING", "KBAssist", f"failed: {e}")
                    try:
                        await websocket.send_json({"type": "message", "speaker": "System", "text": "情報検索でエラーが発生しました。"})
                    except Exception:
                        pass

            # 周回内の話者管理
            character_names = manager.get_character_names(include_hidden=False)
            current_speaker = character_names[0]
            last_message = user_query
            spoken = set()
            # 1サイクル内に同一話者の重複を避け、できるだけ全員に回す
            # max_turns は上限。全員に回すことを優先し、モデルが無言の場合はスキップする
            num_chars = len(character_names)
            desired_turns = max_turns  # config.yaml で指定された回数だけ回す
            
            # registry を一度だけ構築
            registry = []
            for c in manager.list_characters():
                registry.append({
                    "internal_id": c.get("name"),
                    "display_name": c.get("display_name", c.get("name")),
                    "short_name": c.get("short_name", ""),
                })
            
            for turn in range(desired_turns):
                # 1巡終わったら spoken をリセットして次の巡回へ
                if len(spoken) >= num_chars:
                    spoken.clear()
                spoken.add(current_speaker)
                next_speaker, response_text = await process_character_turn(
                    websocket, manager, current_speaker, last_message, log_filename, operation_log_filename, global_rules
                )
                
                last_message = response_text

                # 無言（空応答）の場合は次の未発言者に即スキップ
                if not (response_text or '').strip():
                    write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Empty response from {current_speaker}, skipping.")
                    # 次の未発言者を選択
                    # 下のフォールバックルーチンに委ねるため next_speaker=None とする
                    next_speaker = None
                
                # 次話者が未決定、または既に話した人なら、未発言の中からラウンドロビン順で選択
                def to_internal_id(display_name: str) -> str:
                    for item in registry:
                        if item["display_name"] == display_name:
                            return item["internal_id"]
                    return registry[0]["internal_id"]

                def to_display_name(internal_id: str) -> str:
                    for item in registry:
                        if item["internal_id"] == internal_id:
                            return item["display_name"]
                    return registry[0]["display_name"]

                def rr_next_unspoken(cur_internal: str) -> str | None:
                    ids = [it["internal_id"] for it in registry]
                    if cur_internal not in ids:
                        ids = ids
                    start = ids.index(cur_internal) if cur_internal in ids else -1
                    n = len(ids)
                    for i in range(1, n + 1):
                        cand = ids[(start + i) % n]
                        cand_disp = to_display_name(cand)
                        if cand_disp not in spoken:
                            return cand_disp
                    return None

                def rr_next_any(cur_internal: str) -> str:
                    ids = [it["internal_id"] for it in registry]
                    start = ids.index(cur_internal) if cur_internal in ids else -1
                    n = len(ids)
                    cand = ids[(start + 1) % n]
                    return to_display_name(cand)

                if not next_speaker or next_speaker in spoken:
                    cur_internal = to_internal_id(current_speaker)
                    fallback_disp = rr_next_unspoken(cur_internal)
                    if fallback_disp:
                        next_speaker = fallback_disp
                    else:
                        # 全員発話済みなら、次の巡回として単純RRで次に進む
                        next_speaker = rr_next_any(cur_internal)

                current_speaker = next_speaker
            else:
                write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Autonomous loop ended: Reached max turns ({max_turns}).")

            await update_all_statuses(websocket, manager.get_character_names(), "ACTIVE", log_filename, operation_log_filename)

            # 会話サイクル（ユーザー1入力→自律ループ）終了時に短期要約を永続化
            try:
                await persist_thread_from_log(manager, log_filename, operation_log_filename)
            except Exception as e:
                write_operation_log(operation_log_filename, "ERROR", "ConversationLoop", f"Error persisting memory: {e}")

    except Exception as e:
        error_details = traceback.format_exc()
        write_operation_log(operation_log_filename, "ERROR", "ConversationLoop", f"Error in conversation loop: {e}\n{error_details}")
        print(f"会話ループ中にエラーが発生しました: {e} (ログファイル: {log_filename})")
    finally:
        write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "Conversation loop ended.")