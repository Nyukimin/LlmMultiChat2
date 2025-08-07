import asyncio
import re
import traceback
from datetime import datetime
from fastapi import WebSocket
from langchain_core.messages import SystemMessage, HumanMessage
from character_manager import CharacterManager
from status_manager import update_status, update_all_statuses
from log_manager import create_log_filename, write_log, read_log, create_operation_log_filename, write_operation_log
from initial_status_setter import set_initial_statuses

async def conversation_loop(websocket: WebSocket, manager: CharacterManager):
    log_filename = create_log_filename()
    operation_log_filename = create_operation_log_filename()
    write_log(log_filename, "System", "Conversation loop started.")
    write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "Conversation loop started.")
    print(f"新しい接続が開始されました。ログファイル: {log_filename}")
    print(f"動作ログファイル: {operation_log_filename}")

    await set_initial_statuses(websocket, manager)

    # --- メインの会話ループ ---
    try:
        while True:
            write_log(log_filename, "System", "Waiting for user input...")
            write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "Waiting for user input.")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ユーザー入力を待機中...")
            user_query = await websocket.receive_text()
            write_log(log_filename, "USER", user_query)
            write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "User input received.")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ユーザー入力を受け取りました: {user_query}")

            await update_all_statuses(websocket, manager.get_character_names(), "IDLE")

            for char_name in manager.get_character_names():
                llm = manager.get_llm(char_name)
                
                if llm:
                    write_log(log_filename, "System", f"Processing response for {char_name}")
                    write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Processing response for {char_name}.")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {char_name}の応答処理を開始")
                    await update_status(websocket, char_name, "THINKING")
                    
                    system_prompt = manager.get_persona_prompt(char_name)
                    if not system_prompt: system_prompt = "あなたはAIです。日本語で応答してください。"
                    
                    conversation_log = read_log(log_filename)
                    other_characters = [name for name in manager.get_character_names() if name != char_name]
                    prompt_with_log = f"{system_prompt}\n\n他の参加者: {', '.join(other_characters)}\n\n--- これまでの会話 ---\n{conversation_log}\n--- 会話ここまで ---\n\n上記を踏まえて応答してください。"
                    
                    messages = [SystemMessage(content=prompt_with_log), HumanMessage(content=user_query)]
                    
                    write_log(log_filename, "System", f"Invoking LLM for {char_name}")
                    write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Invoking LLM for {char_name}.")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {char_name}の応答を生成中...")
                    try:
                        response = await llm.ainvoke(messages)
                        response_text = response.content
                        write_log(log_filename, char_name, response.content)
                        write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Received response from LLM for {char_name}.")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] {char_name}の応答を受け取りました: {response_text[:50]}...")
                    except Exception as e:
                        error_details = traceback.format_exc()
                        write_log(log_filename, "System", f"Error invoking LLM for {char_name}: {e}\n{error_details}")
                        write_operation_log(operation_log_filename, "ERROR", "ConversationLoop", f"Error invoking LLM for {char_name}: {e}\n{error_details}")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] {char_name}の応答生成中にエラーが発生しました: {e}")
                        response_text = "応答生成中にエラーが発生しました。"
                    
                    display_text = re.sub(r'\[Next: .*?\]', '', response_text).strip()
                    
                    try:
                        await websocket.send_json({
                            "type": "message",
                            "speaker": char_name,
                            "text": display_text
                        })
                        write_log(log_filename, "System", f"Response sent for {char_name}")
                        write_operation_log(operation_log_filename, "INFO", "ConversationLoop", f"Response sent for {char_name}.")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] {char_name}の応答を送信しました")
                    except Exception as e:
                        error_details = traceback.format_exc()
                        write_log(log_filename, "System", f"Error sending response for {char_name}: {e}\n{error_details}")
                        write_operation_log(operation_log_filename, "ERROR", "ConversationLoop", f"Error sending response for {char_name}: {e}\n{error_details}")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] {char_name}の応答送信中にエラーが発生しました: {e}")

                    await update_status(websocket, char_name, "IDLE")
                    await asyncio.sleep(1)
            
            await update_all_statuses(websocket, manager.get_character_names(), "ACTIVE")

    except Exception as e:
        error_details = traceback.format_exc()
        write_log(log_filename, "System", f"Error in conversation loop: {e}\n{error_details}")
        write_operation_log(operation_log_filename, "ERROR", "ConversationLoop", f"Error in conversation loop: {e}\n{error_details}")
        # WebSocketDisconnectはmain.pyで処理するためここではキャッチしない
        print(f"会話ループ中にエラーが発生しました: {e} (ログファイル: {log_filename})")
    finally:
        write_log(log_filename, "System", "Conversation loop ended.")
        write_operation_log(operation_log_filename, "INFO", "ConversationLoop", "Conversation loop ended.")
