import asyncio
import re
import traceback
import uuid
from datetime import datetime
from fastapi import WebSocket
import yaml
import os
from typing import Dict, List, Dict as TDict
import random

from character_manager import CharacterManager
from status_manager import update_status, update_all_statuses
from log_manager import write_log, get_formatted_conversation_history, write_operation_log
from memory_manager import persist_thread_from_log
from next_speaker_resolver import resolve_next_speaker, NextPolicy


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
    s = s.strip()
    return s or original


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
    try:
        # 応答生成に上限時間を設け、ハング/長考を防ぐ
        response_text = await asyncio.wait_for(llm.ainvoke(system_prompt, user_message), timeout=60.0)
        response_text = str(response_text or "")

        # [Next: ...]タグを抽出する前に、<think>タグとその内容を削除
        response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
        # 表示前に前置きを除去→短縮（未完了感の軽減と要点提示）
        response_text = remove_preamble(response_text)
        response_text = shorten_text(response_text, max_sentences=2, max_chars=160)
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

    try:
        while True:
            write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "Waiting for user input.")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ユーザー入力を待機中...")
            
            user_query = await websocket.receive_text()
            write_log(log_filename, "USER", user_query)
            write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"User input received: {user_query}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ユーザー入力を受け取りました: {user_query}")
            
            await update_all_statuses(websocket, manager.get_character_names(), "IDLE", log_filename, operation_log_filename)
            
            # 周回内の話者管理
            character_names = manager.get_character_names()
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