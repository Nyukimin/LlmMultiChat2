import asyncio
import re
import traceback
from datetime import datetime
from fastapi import WebSocket
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
import yaml
from typing import Dict # Import Dict

from character_manager import CharacterManager
from status_manager import update_status, update_all_statuses
from log_manager import write_log, read_log, write_operation_log

# --- Global Rules Loader ---
def load_global_rules(rules_path: str = "LLM/global_rules.yaml") -> Dict:
    try:
        with open(rules_path, 'r', encoding='utf-8') as file:
            return yaml.safe_load(file)
    except Exception as e:
        print(f"Warning: Could not load global rules from {rules_path}. Error: {e}")
        return {}

# --- Helper function to process a single character's turn ---
async def process_character_turn(
    websocket: WebSocket,
    manager: CharacterManager,
    character_name: str,
    user_query: str,
    log_filename: str,
    operation_log_filename: str,
    global_rules: Dict
):
    """Handles the logic for a single character's response using global rules."""
    llm = manager.get_llm(character_name)
    if not llm:
        return None

    write_log(log_filename, "System", f"Processing response for {character_name}")
    write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Processing response for {character_name}.")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答処理を開始")
    await update_status(websocket, character_name, "THINKING", log_filename, operation_log_filename)

    persona_prompt = manager.get_persona_prompt(character_name)
    if not persona_prompt:
        persona_prompt = "あなたはAIです。日本語で応答してください。"

    conversation_log = read_log(log_filename)
    other_characters_list = [name for name in manager.get_character_names() if name != character_name]
    other_characters = ", ".join(other_characters_list)

    # --- Prompt Generation using global_rules.yaml ---
    prompt_template = global_rules.get("prompt_template", "{persona_prompt}")
    response_constraints = global_rules.get("response_constraints", "").format(character_name=character_name)
    flow_rules = global_rules.get("flow_rules", "").format(other_characters=other_characters)

    final_prompt = prompt_template.format(
        character_name=character_name,
        persona_prompt=persona_prompt,
        response_constraints=response_constraints,
        flow_rules=flow_rules,
        other_characters=other_characters,
        conversation_log=conversation_log
    )
    
    messages = [SystemMessage(content=final_prompt), HumanMessage(content=user_query)]

    # ... (rest of the function is the same as before)
    write_log(log_filename, "System", f"Invoking LLM for {character_name}")
    write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Invoking LLM for {character_name}.")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答を生成中...")

    response_text = ""
    try:
        response = await llm.ainvoke(messages)
        if isinstance(response, AIMessage):
            response_text = response.content
        else:
            response_text = str(response)

        write_log(log_filename, character_name, response_text)
        write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Received response from LLM for {character_name}.")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答を受け取りました: {response_text[:50]}...")
    except Exception as e:
        error_details = traceback.format_exc()
        write_log(log_filename, "System", f"Error invoking LLM for {character_name}: {e}\n{error_details}")
        write_operation_log(operation_log_filename, "ERROR", "ConversationLoop", f"Error invoking LLM for {character_name}: {e}\n{error_details}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答生成中にエラーが発生しました: {e}")
        response_text = "応答生成中にエラーが発生しました。"

    display_text = re.sub(r'\[Next:.*?\]', '', response_text, flags=re.IGNORECASE).strip()
    display_text = re.sub(r'<thought>.*?</thought>', '', display_text, flags=re.DOTALL).strip()

    try:
        await websocket.send_json({
            "type": "message",
            "speaker": character_name,
            "text": display_text
        })
        write_log(log_filename, "System", f"Response sent for {character_name}")
        write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Response sent for {character_name}.")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答を送信しました")
    except Exception as e:
        error_details = traceback.format_exc()
        write_log(log_filename, "System", f"Error sending response for {character_name}: {e}\n{error_details}")
        write_operation_log(operation_log_filename, "ERROR", "ConversationLoop", f"Error sending response for {character_name}: {e}\n{error_details}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {character_name}の応答送信中にエラーが発生しました: {e}")
    
    await update_status(websocket, character_name, "IDLE", log_filename, operation_log_filename)
    await asyncio.sleep(1)

    next_speaker_match = re.search(r'\[Next:\s*(.*?)\]', response_text, re.IGNORECASE)
    if next_speaker_match:
        next_speaker_name = next_speaker_match.group(1).strip()
        if next_speaker_name in manager.get_character_names():
            return next_speaker_name
    return None

# --- Main Conversation Loop ---
async def conversation_loop(websocket: WebSocket, manager: CharacterManager, log_filename: str, operation_log_filename: str):
    from initial_status_setter import set_initial_statuses
    
    global_rules = load_global_rules()

    write_log(log_filename, "System", "Conversation loop started.")
    write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "Conversation loop started.")
    print(f"新しい接続が開始されました。ログファイル: {log_filename}")
    print(f"動作ログファイル: {operation_log_filename}")

    await set_initial_statuses(websocket, manager, log_filename, operation_log_filename)

    try:
        while True:
            write_log(log_filename, "System", "Waiting for user input...")
            write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "Waiting for user input.")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ユーザー入力を待機中...")
            user_query = await websocket.receive_text()
            write_log(log_filename, "USER", user_query)
            write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "User input received.")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ユーザー入力を受け取りました: {user_query}")

            await update_all_statuses(websocket, manager.get_character_names(), "IDLE", log_filename, operation_log_filename)
            
            all_characters = manager.get_character_names()
            responded_characters = set()
            
            current_speaker = all_characters[0]

            while len(responded_characters) < len(all_characters):
                if current_speaker in responded_characters:
                    found_next = False
                    for char in all_characters:
                        if char not in responded_characters:
                            current_speaker = char
                            found_next = True
                            break
                    if not found_next:
                        break
                
                responded_characters.add(current_speaker)
                
                next_speaker = await process_character_turn(
                    websocket, manager, current_speaker, user_query, log_filename, operation_log_filename, global_rules
                )

                if next_speaker and next_speaker not in responded_characters:
                    current_speaker = next_speaker
                else:
                    current_speaker_index = all_characters.index(current_speaker)
                    next_speaker_found = False
                    for i in range(1, len(all_characters)):
                        next_index = (current_speaker_index + i) % len(all_characters)
                        if all_characters[next_index] not in responded_characters:
                            current_speaker = all_characters[next_index]
                            next_speaker_found = True
                            break
                    if not next_speaker_found:
                        break

            await update_all_statuses(websocket, manager.get_character_names(), "ACTIVE", log_filename, operation_log_filename)

    except Exception as e:
        error_details = traceback.format_exc()
        write_log(log_filename, "System", f"Error in conversation loop: {e}\n{error_details}")
        write_operation_log(operation_log_filename, "ERROR", "ConversationLoop", f"Error in conversation loop: {e}\n{error_details}")
        print(f"会話ループ中にエラーが発生しました: {e} (ログファイル: {log_filename})")
    finally:
        write_log(log_filename, "System", "Conversation loop ended.")
        write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "Conversation loop ended.")
