import asyncio
import traceback
import os
import sys
# モジュール検索パスにカレントディレクトリを追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

# 内部モジュールのインポートはパスを明示的に指定
# アプリケーションのメインインスタンスを作成
import character_manager as cm
import websocket_manager as wm
import log_manager as lm

app = FastAPI()

# グローバル変数としてログファイル名を保持
log_filename = lm.create_log_filename()
operation_log_filename = lm.create_operation_log_filename()

# キャラクター管理インスタンスをグローバルに作成
manager = cm.CharacterManager(log_filename)

# 静的ファイルのマウント
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "../html"), html=True), name="static")

@app.on_event("startup")
async def startup_event():
    lm.write_log(log_filename, "System", "Application started.")
    lm.write_operation_log(operation_log_filename, "INFO", "Main", "Application startup initiated.")
    print(f"ログファイル: {log_filename}")
    print(f"動作ログファイル: {operation_log_filename}")

@app.on_event("shutdown")
async def shutdown_event():
    lm.write_log(log_filename, "System", "Application shutdown.")
    lm.write_operation_log(operation_log_filename, "INFO", "Main", "Application shutdown completed.")

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    lm.write_log(log_filename, "System", "WebSocket connection established.")
    lm.write_operation_log(operation_log_filename, "INFO", "WebSocket", "New WebSocket connection established.")
    await websocket.accept()
    lm.write_log(log_filename, "System", "WebSocket connection accepted.")
    lm.write_operation_log(operation_log_filename, "INFO", "WebSocket", "WebSocket connection accepted.")
    try:
        # キャラクター設定情報を送信
        characters = manager.list_characters()
        config_data = [{"name": char["name"], "display_name": char.get("display_name", char["name"])} for char in characters]
        await websocket.send_json({
            "type": "config",
            "characters": config_data
        })
        lm.write_log(log_filename, "System", "Character configuration sent to client.")
        lm.write_operation_log(operation_log_filename, "INFO", "WebSocket", "Character configuration sent to client.")
        await wm.websocket_endpoint(websocket, manager)
    except Exception as e:
        error_details = traceback.format_exc()
        lm.write_log(log_filename, "System", f"Error in WebSocket endpoint: {e}\n{error_details}")
        lm.write_operation_log(operation_log_filename, "ERROR", "WebSocket", f"Error in WebSocket endpoint: {e}\n{error_details}")
        print(f"WebSocketエラー: {e} (ログファイル: {log_filename})")
    finally:
        lm.write_log(log_filename, "System", "WebSocket connection closed.")
        lm.write_operation_log(operation_log_filename, "INFO", "WebSocket", "WebSocket connection closed.")

if __name__ == "__main__":
    import uvicorn
    lm.write_operation_log(operation_log_filename, "INFO", "Main", "Starting Uvicorn server.")
    uvicorn.run(app, host="0.0.0.0", port=8000)
    lm.write_operation_log(operation_log_filename, "INFO", "Main", "Uvicorn server stopped.")
