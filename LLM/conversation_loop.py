import asyncio
import re
from fastapi import WebSocket
from langchain_core.messages import SystemMessage, HumanMessage
from character_manager import CharacterManager
from status_manager import update_status, update_all_statuses
from log_manager import create_log_filename, write_log, read_log

async def conversation_loop(websocket: WebSocket, manager: CharacterManager):
    log_filename = create_log_filename()
    print(f"新しい接続が開始されました。ログファイル: {log_filename}")

    # --- 初期ステータスをACTIVEに設定 ---
    try:
        await update_all_statuses(websocket, manager.get_character_names(), "ACTIVE")
    except Exception as e:
        print(f"初期ステータス更新中にエラーが発生しました: {e}")

    # --- メインの会話ループ ---
    try:
        while True:
            user_query = await websocket.receive_text()
            write_log(log_filename, "USER", user_query)

            await update_all_statuses(websocket, manager.get_character_names(), "IDLE")

            for char_name in manager.get_character_names():
                llm = manager.get_llm(char_name)
                
                if llm:
                    await update_status(websocket, char_name, "THINKING")
                    
                    system_prompt = manager.get_persona_prompt(char_name)
                    if not system_prompt: system_prompt = "あなたはAIです。日本語で応答してください。"
                    
                    conversation_log = read_log(log_filename)
                    other_characters = [name for name in manager.get_character_names() if name != char_name]
                    prompt_with_log = f"{system_prompt}\n\n他の参加者: {', '.join(other_characters)}\n\n--- これまでの会話 ---\n{conversation_log}\n--- 会話ここまで ---\n\n上記を踏まえて応答してください。"
                    
                    messages = [SystemMessage(content=prompt_with_log), HumanMessage(content=user_query)]
                    
                    response = await llm.ainvoke(messages)
                    response_text = response.content
                    
                    write_log(log_filename, char_name, response.content)
                    
                    display_text = re.sub(r'\[Next: .*?\]', '', response_text).strip()
                    
                    await websocket.send_json({
                        "type": "message",
                        "speaker": char_name,
                        "text": display_text
                    })

                    await update_status(websocket, char_name, "IDLE")
                    await asyncio.sleep(1)
            
            await update_all_statuses(websocket, manager.get_character_names(), "ACTIVE")

    except Exception as e:
        # WebSocketDisconnectはmain.pyで処理するためここではキャッチしない
        print(f"会話ループ中にエラーが発生しました: {e} (ログファイル: {log_filename})")
