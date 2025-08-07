from fastapi import WebSocket, WebSocketDisconnect
from character_manager import CharacterManager
from conversation_loop import conversation_loop

async def websocket_endpoint(websocket: WebSocket, manager: CharacterManager):
    await websocket.accept()
    
    try:
        await conversation_loop(websocket, manager)
    except WebSocketDisconnect:
        print(f"クライアントとの接続が切れました。")
    except Exception as e:
        print(f"エラーが発生しました: {e}")
