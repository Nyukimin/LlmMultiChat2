import os
import yaml
import asyncio
import re
from typing import List, Dict, Any, Optional

# FastAPIとWebSocketのインポート
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from dotenv import load_dotenv
load_dotenv()

# 新しいモジュールのインポート
from character_manager import CharacterManager
from conversation_loop import conversation_loop
from websocket_manager import websocket_endpoint # websocket_endpointをインポート

# --- FastAPIアプリケーション ---
app = FastAPI()
manager = CharacterManager(config_path="config.yaml", persona_path="personas.yaml") # CharacterManagerのインスタンス化をここで行う

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket_endpoint(websocket, manager)

# 静的ファイルの配信
app.mount("/", StaticFiles(directory="../html", html=True), name="html")
