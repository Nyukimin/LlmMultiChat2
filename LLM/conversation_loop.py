import asyncio
import sqlite3
import re
import unicodedata
import os
import json
import shutil
from datetime import datetime
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

# Shared normalizers
try:
    from normalize import (
        normalize_title as nz_title,
        normalize_person_name as nz_person,
        looks_like_role_list_plus_name as nz_rolelist,
        normalize_role as nz_role,
        normalize_character as nz_char,
    )
except Exception:
    nz_title = None  # type: ignore
    nz_person = None  # type: ignore
    nz_rolelist = None  # type: ignore
    nz_role = None  # type: ignore
    nz_char = None  # type: ignore


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
    """KB公式APIでDBパスを解決する。失敗時は KB/DB/media.db にフォールバック。
    """
    try:
        if _KB_DIR not in sys.path:
            sys.path.append(_KB_DIR)
        import api as kb  # type: ignore
        return kb.resolve_db_path()
    except Exception:
        return os.path.abspath(os.path.join(_KB_DIR, 'DB', 'media.db'))


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

def _kb_find_persons_by_alias(db_path: str, keyword: str, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT p.id, p.name
            FROM alias a JOIN person p ON p.id = a.person_id
            WHERE a.name LIKE ?
            ORDER BY p.id DESC
            LIMIT ?
            """,
            (f"%{keyword}%", limit)
        )
        # 去重（同一人物が複数別名でヒットする可能性）
        seen = set()
        out = []
        for r in cur.fetchall():
            pid = r["id"]
            if pid in seen:
                continue
            seen.add(pid)
            out.append(dict(r))
        return out
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

# 便利: タイトル/氏名からIDを引く
def _kb_find_work_by_title(db_path: str, title: str) -> Optional[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT w.id, w.title, w.year, c.name AS category
            FROM work w JOIN category c ON c.id=w.category_id
            WHERE w.title=?
            ORDER BY w.id DESC
            LIMIT 1
            """,
            (title.strip(),)
        )
        r = cur.fetchone()
        return dict(r) if r else None
    except Exception:
        return None
    finally:
        conn.close()

def _kb_find_person_by_name(db_path: str, name: str) -> Optional[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT id, name, kana, birth_year, death_year, note
            FROM person
            WHERE name=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (name.strip(),)
        )
        r = cur.fetchone()
        return dict(r) if r else None
    except Exception:
        return None
    finally:
        conn.close()

# ==== 不十分データ抽出（外部ID不足優先） ====
def _kb_pick_incomplete_work(db_path: str, exclude_ids: Optional[list[int]] = None) -> Optional[dict]:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        with conn:
            # 候補を複数件取得し、除外済みを避けてランダム選択
            sql = (
                "SELECT w.id, w.title, c.name AS category "
                "FROM work w JOIN category c ON c.id = w.category_id "
                "LEFT JOIN external_id e ON e.entity_type='work' AND e.entity_id=w.id "
                "WHERE e.id IS NULL ORDER BY w.id DESC LIMIT 50"
            )
            cur = conn.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
            if exclude_ids:
                rows = [r for r in rows if int(r.get("id") or 0) not in set(exclude_ids)]
            if not rows:
                return None
            try:
                random.shuffle(rows)
            except Exception:
                pass
            return rows[0]
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

def _kb_pick_incomplete_person(db_path: str, exclude_ids: Optional[list[int]] = None) -> Optional[dict]:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        with conn:
            sql = (
                "SELECT p.id, p.name, p.kana "
                "FROM person p LEFT JOIN external_id e ON e.entity_type='person' AND e.entity_id=p.id "
                "WHERE e.id IS NULL ORDER BY p.id DESC LIMIT 50"
            )
            cur = conn.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
            if exclude_ids:
                rows = [r for r in rows if int(r.get("id") or 0) not in set(exclude_ids)]
            if not rows:
                return None
            try:
                random.shuffle(rows)
            except Exception:
                pass
            return rows[0]
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

def _kb_pick_incomplete_entity(db_path: str, exclude_work_ids: Optional[list[int]] = None, exclude_person_ids: Optional[list[int]] = None) -> Optional[tuple[str, dict]]:
    w = _kb_pick_incomplete_work(db_path, exclude_work_ids)
    if w:
        return ("work", w)
    p = _kb_pick_incomplete_person(db_path, exclude_person_ids)
    if p:
        return ("person", p)
    return None
# ---- KB対象（映画/人物）ガード判定 ----
def _infer_kb_entity_from_text(text: str) -> str:
    try:
        s = (text or "").strip()
        if not s:
            return "unknown"
        if re.search(r"eiga\.com/(person|movie)/", s, re.IGNORECASE):
            return "person" if "/person/" in s else ("work" if "/movie/" in s else "unknown")
        if re.search(r"(俳優|女優|監督|人物|キャスト|出演)", s):
            return "person"
        if re.search(r"(映画|作品|ドラマ)", s):
            return "work"
        # 2-4文字の日本語固有名らしさ（人物寄り）
        if re.match(r"^[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]{2,4}$", s):
            return "person"
        # カタカナ主体（長音含む）のタイトルらしさ（作品寄り）
        if re.match(r"^[\u30A0-\u30FF・ー\s]{2,}$", s):
            return "work"
        return "unknown"
    except Exception:
        return "unknown"

def _is_kb_domain_query(text: str) -> bool:
    ent = _infer_kb_entity_from_text(text)
    if ent in ("person", "work"):
        return True
    # キーワードが1つも無ければ対象外
    return bool(re.search(r"(映画|作品|俳優|女優|監督|キャスト|出演|ドラマ|eiga\.com)", str(text or "")))

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
    global_rules: Dict,
    info_search_mode: bool
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
    detected_meta: Dict = {}
    try:
        # 応答生成に上限時間を設け、ハング/長考を防ぐ
        response_text = await asyncio.wait_for(llm.ainvoke(system_prompt, user_message), timeout=60.0)
        response_text = str(response_text or "")
        raw_response_text = response_text

        # --- 自動委譲メタを検出（JSONメタ or [ASK_SEARCHER: ...]）し、表示からは除去 ---
        try:
            # 1) JSONメタ（末尾のJSONオブジェクトに meta キーがあるか）
            s = response_text.strip()
            m1 = re.search(r"(\{[\s\S]*\})\s*$", s)
            if m1:
                frag = m1.group(1)
                import json as _json
                try:
                    obj = _json.loads(frag)
                    if isinstance(obj, dict) and isinstance(obj.get("meta"), dict):
                        detected_meta = obj.get("meta") or {}
                        # 表示からJSONメタを除去
                        response_text = s[: s.rfind(frag)].rstrip()
                except Exception:
                    pass
            # 2) タグ形式 [ASK_SEARCHER: ...]
            if not detected_meta:
                m2 = re.search(r"\[ASK_SEARCHER:\s*(.*?)\]", response_text)
                if m2:
                    detected_meta = {"need_search": True, "kb_query": m2.group(1).strip()}
                    response_text = re.sub(r"\[ASK_SEARCHER:[^\]]*\]", "", response_text).strip()
        except Exception:
            detected_meta = {}

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

    # ===== kbjson 自動取り込み（情報検索モードON時のみ） =====
    try:
        ingest_enabled, kb_db_path = _load_kb_ingest_settings()
        if info_search_mode and ingest_enabled and raw_response_text and _extract_kbjson and _normalize_kbjson and _kb_ingest_payload:
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
                return c["display_name"], response_text, detected_meta

    write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "No valid next speaker resolved. Autonomous loop ending.")
    return None, response_text, detected_meta

async def conversation_loop(websocket: WebSocket, manager: CharacterManager, log_filename: str, operation_log_filename: str):
    from initial_status_setter import set_initial_statuses
    
    global_rules = load_global_rules()
    # 既定はグローバルルール、優先は config.yaml の conversation.auto_loops
    max_turns = global_rules.get("max_autonomous_turns", 3)
    max_turns = _load_auto_loops_from_config(max_turns)

    await set_initial_statuses(websocket, manager, log_filename, operation_log_filename)
    # セッション内フラグ: 情報検索モード
    info_search_mode: bool = False
    # 特殊捜査: 深掘りフォールバックで外部IDを確実取得（夜間のみ稼働）
    if not hasattr(conversation_loop, "_kb_special_running"):
        conversation_loop._kb_special_running = False
        conversation_loop._kb_special_task = None
        conversation_loop._kb_special_last = ""
        conversation_loop._kb_special_window = "23:00-06:00"
        conversation_loop._kb_special_rate = 8.0
        conversation_loop._kb_special_domain = "all"

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

            # /kb normalize : 共通CLIで一括正規化
            if user_query.strip().lower() == "/kb normalize":
                try:
                    db_path = _resolve_kb_db_path_from_kb_config()
                    await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": "DB正規化を開始します（バックアップ→一括処理）。"})
                    # 共通CLIをサブプロセスで実行
                    import subprocess, sys as _sys
                    cli_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "KB", "normalize_db.py"))
                    cmd = [_sys.executable, cli_path, "--db", db_path, "--apply"]
                    try:
                        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
                    except TypeError:
                        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode("utf-8", errors="ignore")
                    write_operation_log(operation_log_filename, "INFO", "KBNormalize", out.strip())
                    await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": "DB正規化が完了しました。"})
                except Exception as e:
                    await websocket.send_json({"type": "message", "speaker": "System", "text": f"正規化エラー: {e}"})
                continue

            # /kb titles suspicious [limit]
            try:
                m_ts = re.match(r"^\s*/kb\s+titles\s+suspicious(?:\s+(\d+))?\s*$", user_query, re.IGNORECASE)
            except Exception:
                m_ts = None
            if m_ts:
                try:
                    limit = int(m_ts.group(1)) if m_ts.group(1) else 20
                except Exception:
                    limit = 20
                limit = max(1, min(limit, 100))
                try:
                    db_path = _resolve_kb_db_path_from_kb_config()
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    with conn:
                        cur = conn.execute("SELECT id, title FROM work ORDER BY id DESC LIMIT ?", (limit * 10,))
                        candidates = []
                        for r in cur.fetchall():
                            wid = r['id']; title = r['title'] or ''
                            raw = title
                            try:
                                norm_title, _yr = nz_title(title) if nz_title else (title, None)  # type: ignore[operator]
                            except Exception:
                                norm_title, _yr = (title, None)
                            suspicious = False
                            if nz_rolelist and (('/' in raw or '／' in raw)):
                                if nz_rolelist(raw):
                                    suspicious = True
                            # 状態語/役割語の除去で変化したものも候補
                            if norm_title != raw:
                                suspicious = True
                            if suspicious:
                                candidates.append({'id': wid, 'title': raw, 'normalized': norm_title})
                        rows = candidates[:limit]
                    if rows:
                        lines = ["疑わしいタイトル:"]
                        for r in rows:
                            lines.append(f"- id:{r['id']}  {r['title']}  ->  {r.get('normalized','')}")
                        msg = "\n".join(lines)
                    else:
                        msg = "疑わしいタイトルは見つかりませんでした。"
                except Exception as e:
                    msg = f"エラー: {e}"
                await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": msg})
                continue

            # ----- 特殊捜査: start/stop/status -----
            def _within_window(win: str) -> bool:
                try:
                    now = datetime.now().time()
                    s, e = win.split("-")
                    sh, sm = [int(x) for x in s.split(":")]
                    eh, em = [int(x) for x in e.split(":")]
                    from datetime import time as _t
                    start = _t(sh, sm)
                    end = _t(eh, em)
                    if start <= end:
                        return start <= now <= end
                    else:
                        return not (end < now < start)
                except Exception:
                    return True

            async def _kb_special_worker():
                try:
                    while conversation_loop._kb_special_running:
                        if not _within_window(conversation_loop._kb_special_window):
                            await asyncio.sleep(conversation_loop._kb_special_rate)
                            continue
                        # 除外（recent）を活用
                        now_ts = datetime.now().timestamp()
                        ttl_sec = 600
                        if not hasattr(conversation_loop, "_kb_recent_attempts"):
                            conversation_loop._kb_recent_attempts = {"work": {}, "person": {}}
                        recent = conversation_loop._kb_recent_attempts  # type: ignore[attr-defined]
                        # クリーンアップ
                        try:
                            for k in list(recent["work"].keys()):
                                if now_ts - float(recent["work"][k]) > ttl_sec:
                                    del recent["work"][k]
                            for k in list(recent["person"].keys()):
                                if now_ts - float(recent["person"][k]) > ttl_sec:
                                    del recent["person"][k]
                        except Exception:
                            pass
                        exw = [int(k) for k in recent.get("work", {}).keys()]
                        exp = [int(k) for k in recent.get("person", {}).keys()]
                        db_path = _resolve_kb_db_path_from_kb_config()
                        picked = _kb_pick_incomplete_entity(db_path, exw, exp)
                        if not picked:
                            conversation_loop._kb_special_last = "在庫なし"
                            await asyncio.sleep(conversation_loop._kb_special_rate)
                            continue
                        kind, item = picked
                        q = (item.get("title") if kind == "work" else item.get("name")) or ""
                        conversation_loop._kb_special_last = f"{kind}:{item.get('id')} '{q}'"
                        try:
                            await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"特殊捜査: 『{q}』を深掘りします。"})
                        except Exception:
                            pass
                        # 除外登録
                        try:
                            if kind == "work":
                                recent["work"][str(int(item.get("id")))] = now_ts
                            else:
                                recent["person"][str(int(item.get("id")))] = now_ts
                        except Exception:
                            pass
                        try:
                            write_operation_log(operation_log_filename, "INFO", "KBSpecial", f"query='{q}' starting")
                            # UIへも開始メッセージ
                            try:
                                await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"特殊捜査: 『{q}』を検索開始します。"})
                            except Exception:
                                pass
                            res = await _kb_run_ingest(q, "映画", 1, db_path, True, False, None, None, kind, 3, True)  # type: ignore
                            pn = len(res.get("persons") or [])
                            wn = len(res.get("works") or [])
                            write_operation_log(operation_log_filename, "INFO", "KBSpecial", f"query='{q}' result persons={pn} works={wn}")
                            # UIへも結果メッセージ
                            try:
                                await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"特殊捜査: 『{q}』の取得結果 人物 {pn} / 作品 {wn} 件。"})
                            except Exception:
                                pass
                        except Exception:
                            pass
                        await asyncio.sleep(conversation_loop._kb_special_rate)
                except asyncio.CancelledError:
                    return

            # /kb special start [domain] [HH:MM-HH:MM] [rate=秒]
            try:
                msp = re.match(r"^\s*/kb\s+special\s+start(?:\s+(work|person|all))?(?:\s+([0-2]?[0-9]:[0-5][0-9]-[0-2]?[0-9]:[0-5][0-9]))?(?:\s+rate=(\d+(?:\.\d+)?))?\s*$", user_query, re.IGNORECASE)
            except Exception:
                msp = None
            if msp:
                dom = (msp.group(1) or "all").lower()
                win = msp.group(2) or conversation_loop._kb_special_window
                rate = float(msp.group(3) or conversation_loop._kb_special_rate)
                conversation_loop._kb_special_domain = dom
                conversation_loop._kb_special_window = win
                conversation_loop._kb_special_rate = max(1.0, rate)
                if conversation_loop._kb_special_running and conversation_loop._kb_special_task:
                    await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": "特殊捜査は既に稼働中です。"})
                else:
                    conversation_loop._kb_special_running = True
                    conversation_loop._kb_special_task = asyncio.create_task(_kb_special_worker())
                    await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"特殊捜査を開始しました（domain={dom}, window={win}, rate={conversation_loop._kb_special_rate}s）。"})
                continue

            if user_query.strip().lower() == "/kb special stop":
                try:
                    if conversation_loop._kb_special_task:
                        conversation_loop._kb_special_task.cancel()
                    conversation_loop._kb_special_running = False
                    conversation_loop._kb_special_task = None
                    await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": "特殊捜査を停止しました。"})
                except Exception as e:
                    await websocket.send_json({"type": "message", "speaker": "System", "text": f"エラー: {e}"})
                continue

            if user_query.strip().lower() == "/kb special status":
                running = conversation_loop._kb_special_running
                win = conversation_loop._kb_special_window
                rate = conversation_loop._kb_special_rate
                last = conversation_loop._kb_special_last
                await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"特殊捜査: {'ON' if running else 'OFF'} window={win} rate={rate}s last={last}"})
                continue
            # /kb normalize titles : 既存 work.title の共通正規化適用
            if user_query.strip().lower() == "/kb normalize titles":
                try:
                    db_path = _resolve_kb_db_path_from_kb_config()
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    fixed = []
                    with conn:
                        cur = conn.execute("SELECT id, title FROM work")
                        rows = cur.fetchall()
                        for r in rows:
                            wid = r['id']; title = r['title'] or ''
                            if nz_title:
                                norm_title, _yr = nz_title(title)  # type: ignore[operator]
                            else:
                                s = unicodedata.normalize('NFKC', (title or '').strip())
                                s = s.replace('\u3000', ' ')
                                s = re.sub(r"[／/]+", " ", s)
                                s = re.sub(r"^(上映中|配信中)[\s／/]+", "", s)
                                while True:
                                    s2 = re.sub(r"^(監督|脚本|原作|音楽|声優|出演|主演|プロデューサー|音響効果)[：:・／/\s]+", "", s)
                                    if s2 == s:
                                        break
                                    s = s2
                                norm_title = re.sub(r"\s+", " ", s).strip()
                            if norm_title and norm_title != title:
                                conn.execute("UPDATE work SET title=? WHERE id=?", (norm_title, wid))
                                fixed.append({"id": int(wid), "before": title, "after": norm_title})
                        # FTS再投入（workのみ簡易）
                        try:
                            conn.execute("INSERT INTO fts(fts) VALUES('delete-all')")
                            conn.execute("INSERT INTO fts(kind, ref_id, text) SELECT 'person', id, COALESCE(name,'')||' '||COALESCE(kana,'') FROM person")
                            conn.execute("INSERT INTO fts(kind, ref_id, text) SELECT 'work', id, COALESCE(title,'')||' '||COALESCE(summary,'') FROM work")
                            cur2 = conn.execute("SELECT id, character, role FROM credit")
                            for rr in cur2.fetchall():
                                conn.execute("INSERT INTO fts(kind, ref_id, text) VALUES('credit', ?, ?)", (rr['id'], (rr['character'] or '')+' '+(rr['role'] or '')))
                        except Exception:
                            pass
                    # ログ出力
                    try:
                        os.makedirs(os.path.join('logs','cleanup'), exist_ok=True)
                        snap = os.path.join('logs','cleanup', f"title_normalize_{datetime.now().strftime('%Y%m%d%H%M%S')}.json")
                        with open(snap,'w',encoding='utf-8') as f:
                            json.dump(fixed, f, ensure_ascii=False, indent=2)
                        write_operation_log(operation_log_filename, "INFO", "KBNormalizeTitles", f"changed={len(fixed)} -> {snap}")
                    except Exception:
                        pass
                    await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"タイトルの再正規化を完了しました（{len(fixed)} 件修正）。"})
                except Exception as e:
                    await websocket.send_json({"type": "message", "speaker": "System", "text": f"正規化エラー: {e}"})
                continue

            # /kbalias normalize : 別名正規化（共通正規化適用 + 重複整理）
            if user_query.strip().lower() == "/kbalias normalize":
                try:
                    db_path = _resolve_kb_db_path_from_kb_config()
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    fixed = 0
                    with conn:
                        cur = conn.execute("SELECT id, entity_type, entity_id, name FROM alias")
                        rows = cur.fetchall()
                        for r in rows:
                            aid = r["id"]
                            et = r["entity_type"]
                            eid = r["entity_id"]
                            raw = r["name"] or ""
                            if et == 'person' and nz_person:
                                name_norm = nz_person(raw)  # type: ignore[operator]
                            elif et == 'work' and nz_title:
                                name_norm, _yr = nz_title(raw)  # type: ignore[operator]
                            else:
                                name = unicodedata.normalize("NFKC", raw)
                                name = name.replace("　", " ")
                                name_norm = re.sub(r"\s+", " ", name).strip()
                            if name_norm != name:
                                conn.execute("UPDATE alias SET name=? WHERE id=?", (name_norm, aid))
                                fixed += 1
                        # 完全重複の削除
                        conn.execute(
                            "DELETE FROM alias WHERE rowid NOT IN (SELECT MIN(rowid) FROM alias GROUP BY entity_type, entity_id, name)"
                        )
                    await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"別名の正規化が完了しました（{fixed} 件修正）。重複も整理しました。"})
                except Exception as e:
                    await websocket.send_json({"type": "message", "speaker": "System", "text": f"エラー: {e}"})
                continue

            # /kbcomplete [N] : サーチャー能力でKBの不十分データをN件（既定3）順次補完し、会話しながら進行
            try:
                m_complete = re.match(r"^\s*/kbcomplete(?:\s+(\d+))?\s*$", user_query, re.IGNORECASE)
            except Exception:
                m_complete = None
            if m_complete:
                try:
                    # 受信直後にサーバ側からも明示メッセージを返す（無反応対策）
                    await websocket.send_json({"type": "message", "speaker": "System", "text": "KBの不十分データを1件補完します…"})
                    write_operation_log(operation_log_filename, "INFO", "KBComplete", "/kbcomplete received")
                    db_path = _resolve_kb_db_path_from_kb_config()
                    try:
                        limit = int(m_complete.group(1)) if m_complete.group(1) else 3
                    except Exception:
                        limit = 3
                    limit = max(1, min(limit, 5))
                    import asyncio as _aio
                    count_done = 0
                    # セッション跨ぎの除外（最近試行したIDは10分スキップ）
                    ttl_sec = 600
                    now_ts = datetime.now().timestamp()
                    if not hasattr(conversation_loop, "_kb_recent_attempts"):
                        conversation_loop._kb_recent_attempts = {"work": {}, "person": {}}
                    recent = conversation_loop._kb_recent_attempts  # type: ignore[attr-defined]
                    # クリーンアップ
                    try:
                        for k in list(recent["work"].keys()):
                            if now_ts - float(recent["work"][k]) > ttl_sec:
                                del recent["work"][k]
                        for k in list(recent["person"].keys()):
                            if now_ts - float(recent["person"][k]) > ttl_sec:
                                del recent["person"][k]
                    except Exception:
                        pass
                    exclude_w: list[int] = [int(k) for k in getattr(recent, "get", lambda x: [])("work", {}).keys()] if isinstance(recent.get("work", {}), dict) else []  # type: ignore
                    exclude_p: list[int] = [int(k) for k in recent.get("person", {}).keys()]  # type: ignore
                    for _i in range(limit):
                        picked = _kb_pick_incomplete_entity(db_path, exclude_w, exclude_p)
                        if not picked:
                            if count_done == 0:
                                await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": "補完対象の不十分データは見つかりませんでした。"})
                            break
                        kind, item = picked
                        query = (item.get("title") if kind == "work" else item.get("name")) or ""
                        # 今回の対象を除外リストへ（クリック間でもスキップ）
                        if kind == "work" and item.get("id"):
                            exclude_w.append(int(item.get("id")))
                            try:
                                recent["work"][str(int(item.get("id")))] = now_ts
                            except Exception:
                                pass
                        if kind == "person" and item.get("id"):
                            exclude_p.append(int(item.get("id")))
                            try:
                                recent["person"][str(int(item.get("id")))] = now_ts
                            except Exception:
                                pass
                        write_operation_log(operation_log_filename, "INFO", "KBComplete", f"picked {kind} id={item.get('id')} query='{query}'")
                        await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"『{query}』を検索開始します。"})
                        await update_status(websocket, "サーチャー", "THINKING", log_filename, operation_log_filename)
                        await _aio.sleep(0.4)
                        try:
                            # 補完は登録まで実施
                            write_operation_log(operation_log_filename, "INFO", "KBComplete", f"query='{query}' starting")
                            res = await _kb_run_ingest(query, "映画", 1, db_path, True, False, None, None, kind, 3, True)  # type: ignore
                            pn = len(res.get("persons") or [])
                            wn = len(res.get("works") or [])
                            write_operation_log(operation_log_filename, "INFO", "KBComplete", f"query='{query}' result persons={pn} works={wn}")
                            # 会話向けのやさしい日本語サマリ
                            summary_text = ""
                            if kind == "work":
                                w = _kb_find_work_by_title(db_path, query)
                                if w:
                                    cat = (w.get("category") or "")
                                    yr = w.get("year")
                                    suffix = (f"（{cat}）" if cat else "") + (f"（{yr}年）" if yr else "")
                                    summary_text = f"『{w.get('title') or query}』{suffix} の基本情報をそろえました。"
                            else:
                                p = _kb_find_person_by_name(db_path, query)
                                if p:
                                    kana = p.get("kana") or ""
                                    by = p.get("birth_year")
                                    dy = p.get("death_year")
                                    life = (f"（{by}生）" if by and not dy else (f"（{by}–{dy}）" if by and dy else ""))
                                    nm = p.get("name") or query
                                    summary_text = f"{nm}{life} に関する情報を補いました。"
                            if not summary_text:
                                summary_text = f"完了しました。人物 {pn} 件、作品 {wn} 件の情報を反映しています。"
                            write_operation_log(operation_log_filename, "INFO", "KBComplete", f"completed {kind} id={item.get('id')} pn={pn} wn={wn}")
                            # 補完後に外部IDが依然として無い場合はsnooze継続（recentに既に入っているため、ここではログのみ）
                            try:
                                chk = 0
                                conn = sqlite3.connect(db_path)
                                with conn:
                                    if kind == "work":
                                        cur = conn.execute("SELECT 1 FROM external_id e JOIN work w ON w.id=? WHERE e.entity_type='work' AND e.entity_id=w.id LIMIT 1", (int(item.get('id') or 0),))
                                    else:
                                        cur = conn.execute("SELECT 1 FROM external_id WHERE entity_type='person' AND entity_id=? LIMIT 1", (int(item.get('id') or 0),))
                                    chk = 1 if cur.fetchone() else 0
                                if chk == 0:
                                    write_operation_log(operation_log_filename, "INFO", "KBComplete", f"snooze: still incomplete {kind} id={item.get('id')}")
                            except Exception:
                                pass
                            await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": summary_text})
                            count_done += 1
                        except Exception as e:
                            write_operation_log(operation_log_filename, "ERROR", "KBComplete", f"error: {e}")
                            await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"エラー: {e}"})
                        await update_status(websocket, "サーチャー", "IDLE", log_filename, operation_log_filename)
                        await _aio.sleep(0.3)
                        # 次へ続ける宣言（最後でなければ）
                        if _i < limit - 1:
                            await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": "次の補完対象を選定します…。"})
                except Exception as e:
                    write_operation_log(operation_log_filename, "ERROR", "KBComplete", f"fatal: {e}")
                    await websocket.send_json({"type": "message", "speaker": "System", "text": f"エラー: {e}"})
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
                        lines = []
                        for r in rows:
                            name = r['name']
                            name_norm = nz_person(name) if nz_person else name
                            if name_norm != name:
                                lines.append(f"- {name} -> {name_norm} (id:{r['id']})")
                            else:
                                lines.append(f"- {name} (id:{r['id']})")
                        msg = "\n".join(lines)
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
                        lines = []
                        for r in rows:
                            title = r['title']
                            norm_title, _yr = nz_title(title) if nz_title else (title, None)
                            yr = r.get('year')
                            if norm_title != title:
                                lines.append(f"- {title} -> {norm_title} (id:{r['id']})" + (f" ({yr})" if yr else ''))
                            else:
                                lines.append(f"- {title} (id:{r['id']})" + (f" ({yr})" if yr else ''))
                        msg = "\n".join(lines)
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

            # /kb fix credits <work_id> : 指定作品のクレジットを共通正規化（role/character）
            try:
                mfix = re.match(r"^\s*/kb\s+fix\s+credits\s+(\d+)\s*$", user_query, re.IGNORECASE)
            except Exception:
                mfix = None
            if mfix:
                try:
                    wid = int(mfix.group(1))
                    db_path = _resolve_kb_db_path_from_kb_config()
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    updated = 0
                    removed = 0
                    with conn:
                        cur = conn.execute("SELECT id, role, character FROM credit WHERE work_id=?", (wid,))
                        for r in cur.fetchall():
                            cid = r['id']
                            new_role = nz_role(r['role'] or '') if nz_role else (r['role'] or '')
                            new_char = nz_char(r['character'] or '') if nz_char else (r['character'] or '')
                            if new_role != (r['role'] or '') or new_char != (r['character'] or ''):
                                conn.execute("UPDATE credit SET role=?, character=? WHERE id=?", (new_role, new_char, cid))
                                updated += 1
                    await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"クレジットを整えました（更新 {updated} 件、削除 {removed} 件）。"})
                except Exception as e:
                    await websocket.send_json({"type": "message", "speaker": "System", "text": f"エラー: {e}"})
                continue

            # /kb fix person delete <id> : 明らかに誤った人物レコードを削除（関連alias/external_id/creditも連鎖）
            try:
                mfpd = re.match(r"^\s*/kb\s+fix\s+person\s+delete\s+(\d+)\s*$", user_query, re.IGNORECASE)
            except Exception:
                mfpd = None
            if mfpd:
                try:
                    pid = int(mfpd.group(1))
                    db_path = _resolve_kb_db_path_from_kb_config()
                    conn = sqlite3.connect(db_path)
                    conn.row_factory = sqlite3.Row
                    with conn:
                        # 付帯情報を先に削除
                        conn.execute("DELETE FROM alias WHERE entity_type='person' AND entity_id=?", (pid,))
                        conn.execute("DELETE FROM external_id WHERE entity_type='person' AND entity_id=?", (pid,))
                        # credit は外部キーON DELETE CASCADEのため person 削除で連鎖削除
                        conn.execute("DELETE FROM person WHERE id=?", (pid,))
                    await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"人物ID {pid} を削除しました。"})
                except Exception as e:
                    await websocket.send_json({"type": "message", "speaker": "System", "text": f"エラー: {e}"})
                continue
            
            await update_all_statuses(websocket, manager.get_character_names(), "IDLE", log_filename, operation_log_filename)
            
            # 外部検索はサーチャーのみ実行。KB登録は情報検索モードON時のみ。
            if _kb_run_ingest is not None:
                try:
                    topic = (user_query or "").strip()
                    # トリガー語判定（「調べて/検索/情報収集」または /searcher run 明示）
                    trigger = False
                    uq = topic
                    if re.search(r"(調べて|検索|情報収集|探して|確認して|調査|リサーチ)", uq):
                        trigger = True
                    if re.match(r"^\s*/searcher\s+run\s+.+", uq):
                        trigger = True
                        topic = re.sub(r"^\s*/searcher\s+run\s+", "", uq).strip()
                    # KB対象（映画/人物）に限定
                    # info_search_mode中は、KBドメイン語ならトリガー無しでも起動
                    if (info_search_mode and topic and _is_kb_domain_query(topic)):
                        trigger = True
                    if trigger and topic and _is_kb_domain_query(topic):
                        # 短期重複抑制（10分 or 3回）
                        if not hasattr(conversation_loop, "_kb_delegate_cache"):
                            conversation_loop._kb_delegate_cache = {}
                        cache = conversation_loop._kb_delegate_cache  # type: ignore[attr-defined]
                        now = datetime.now()
                        ent = cache.get(topic) or {"count": 0, "last": now.replace(year=2000)}
                        recent = (now - ent.get("last")).total_seconds() < 600
                        if ent.get("count", 0) >= 3 or recent:
                            try:
                                await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": "直近の同一調査があるためスキップしました。必要なら /searcher run <語句> で強制実行してください。"})
                            except Exception:
                                pass
                        else:
                            ent["count"] = ent.get("count", 0) + 1
                            ent["last"] = now
                            cache[topic] = ent
                        await update_status(websocket, "サーチャー", "THINKING", log_filename, operation_log_filename)
                        await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"{topic} を調査します。"})
                        await asyncio.sleep(0.8)
                        db_path = _resolve_kb_db_path_from_kb_config()
                        # register は info_search_mode に連動
                        write_operation_log(operation_log_filename, "INFO", "Searcher", f"query='{topic}' starting register={info_search_mode}")
                        res = await _kb_run_ingest(topic, "映画", 1, db_path, True, False, None, None, "unknown", 3, info_search_mode)  # type: ignore
                        persons = len(res.get("persons") or [])
                        works = len(res.get("works") or [])
                        write_operation_log(operation_log_filename, "INFO", "Searcher", f"query='{topic}' result persons={persons} works={works}")
                        await asyncio.sleep(0.4)
                        if info_search_mode:
                            msg = f"KB登録完了。人物 {persons} / 作品 {works} 件。"
                        else:
                            msg = f"検索完了。KB登録はOFFです。人物 {persons} / 作品 {works} 件を把握。"
                        await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": msg})
                        await update_status(websocket, "サーチャー", "IDLE", log_filename, operation_log_filename)
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
                next_speaker, response_text, meta = await process_character_turn(
                    websocket, manager, current_speaker, last_message, log_filename, operation_log_filename, global_rules, info_search_mode
                )
                
                last_message = response_text

                # --- 自動委譲メタの処理（全キャラ共通） ---
                try:
                    meta = meta or {}
                    need = bool(meta.get("need_search"))
                    kb_query = str(meta.get("kb_query") or "").strip()
                    entity = str(meta.get("entity") or "").strip().lower()  # "person"|"work"|""
                except Exception:
                    need, kb_query, entity = False, "", ""

                if need and kb_query and _kb_run_ingest is not None and _is_kb_domain_query(kb_query):
                    # 1) まずKB照会（人物/作品の両方）
                    db_path = _resolve_kb_db_path_from_kb_config()
                    try:
                        persons = _kb_find_persons(db_path, kb_query, 5)
                    except Exception:
                        persons = []
                    try:
                        works = _kb_find_works(db_path, kb_query, 5)
                    except Exception:
                        works = []
                    # alias も併用
                    try:
                        if not persons:
                            persons_alias = _kb_find_persons_by_alias(db_path, kb_query, 5)
                        else:
                            persons_alias = []
                    except Exception:
                        persons_alias = []
                    if persons_alias:
                        # マージ（去重）
                        seen = {p["id"] for p in persons}
                        for r in persons_alias:
                            if r["id"] not in seen:
                                persons.append(r)

                    if persons or works:
                        lines = ["KBに既存の候補が見つかりました。"]
                        if persons:
                            lines.append("- 人物: " + ", ".join([p.get("name") for p in persons[:5] if p.get("name")]))
                        if works:
                            lines.append("- 作品: " + ", ".join([w.get("title") for w in works[:5] if w.get("title")]))
                        msg = "\n".join(lines)
                        await websocket.send_json({"type": "message", "speaker": current_speaker, "text": msg})
                    else:
                        # 2) サーチャーへ委譲（外部検索）。登録は info_search_mode に連動
                        await update_status(websocket, "サーチャー", "THINKING", log_filename, operation_log_filename)
                        await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": f"{kb_query} を調査します。"})
                        import asyncio as _aio
                        await _aio.sleep(0.6)
                        try:
                            res = await _kb_run_ingest(kb_query, "映画", 1, db_path, True, False, None, None, entity if entity in ("person","work") else "unknown", 3, info_search_mode)  # type: ignore
                            pn = len(res.get("persons") or [])
                            wn = len(res.get("works") or [])
                            msg = (f"KB登録完了。人物 {pn} / 作品 {wn} 件。" if info_search_mode else f"検索完了。KB登録はOFFです。人物 {pn} / 作品 {wn} 件を把握。")
                        except Exception as e:
                            msg = f"調査に失敗しました: {e}"
                        await websocket.send_json({"type": "message", "speaker": "サーチャー", "text": msg})
                        await update_status(websocket, "サーチャー", "IDLE", log_filename, operation_log_filename)

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