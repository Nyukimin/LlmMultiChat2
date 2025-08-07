from fastapi import WebSocket
from typing import List, Dict, Any
import asyncio

# CharacterManagerのインポートは不要になる
# from character_manager import CharacterManager 

async def update_status(websocket: WebSocket, character: str, status: str):
    """指定されたキャラクターのステータスを更新する"""
    await websocket.send_json({"type": "status", "character": character, "status": status})

async def update_all_statuses(websocket: WebSocket, character_names: List[str], status: str):
    """全キャラクターのステータスを一括で更新する"""
    # 全てのステータス更新を並行して行う
    await asyncio.gather(*(update_status(websocket, name, status) for name in character_names))
