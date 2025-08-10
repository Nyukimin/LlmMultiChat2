import asyncio
import traceback
import os
import sys
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import uvicorn

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import character_manager as cm
import websocket_manager as wm
import log_manager as lm
import yaml
from readiness_checker import ensure_ollama_model_ready_sync

app = FastAPI()

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "../html"), html=True), name="static")

operation_log_filename = ""
conversation_log_dir = None
operation_log_dir = None

@app.on_event("startup")
async def startup_event():
    global operation_log_filename, conversation_log_dir, operation_log_dir

    # 設定からログ出力先を読み込み（存在しなければ既定値）
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        logs_cfg = cfg.get('logs', {}) if isinstance(cfg, dict) else {}
        conversation_log_dir = logs_cfg.get('conversation_dir')
        operation_log_dir = logs_cfg.get('operation_dir')
    except Exception:
        conversation_log_dir = None
        operation_log_dir = None

    # operation_dir が未設定なら conversation_dir と同じ場所を使用
    effective_operation_dir = operation_log_dir or conversation_log_dir
    operation_log_filename = lm.create_operation_log_filename(effective_operation_dir)
    lm.write_operation_log(operation_log_filename, "INFO", "Main", "Application startup initiated.")
    print(f"Operation log file: {operation_log_filename}")

    # すべての Ollama モデルをサーバ起動時にウォームアップ（設定でON/OFFと同期/非同期を切替）
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        characters = cfg.get('characters', [])
        startup_cfg = (cfg.get('startup') or {}) if isinstance(cfg, dict) else {}
        preload_models: bool = bool(startup_cfg.get('preload_models', True))
        preload_blocking: bool = bool(startup_cfg.get('preload_blocking', True))

        async def _preload_async():
            try:
                loop = asyncio.get_running_loop()
                # ブロッキングなチェックをスレッドで実行してUIをブロックしない
                def _work():
                    for char in characters:
                        if str(char.get('provider', '')).lower() == 'ollama':
                            base_url = char.get('base_url', 'http://localhost:11434')
                            model = char.get('model')
                            ensure_ollama_model_ready_sync(base_url, model, operation_log_filename)
                await loop.run_in_executor(None, _work)
                lm.write_operation_log(operation_log_filename, "INFO", "Main", "All Ollama models preloaded (async mode).")
            except Exception as e:
                lm.write_operation_log(operation_log_filename, "WARNING", "Main", f"Async preload failed: {e}")

        if preload_models:
            if preload_blocking:
                for char in characters:
                    if str(char.get('provider', '')).lower() == 'ollama':
                        base_url = char.get('base_url', 'http://localhost:11434')
                        model = char.get('model')
                        ensure_ollama_model_ready_sync(base_url, model, operation_log_filename)
                lm.write_operation_log(operation_log_filename, "INFO", "Main", "All Ollama models preloaded (blocking mode).")
            else:
                asyncio.create_task(_preload_async())
                lm.write_operation_log(operation_log_filename, "INFO", "Main", "Preloading Ollama models started (non-blocking).")
        else:
            lm.write_operation_log(operation_log_filename, "INFO", "Main", "Preloading disabled by config.")
    except Exception as e:
        lm.write_operation_log(operation_log_filename, "WARNING", "Main", f"Preload step skipped/failed: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    lm.write_operation_log(operation_log_filename, "INFO", "Main", "Application shutdown completed.")

@app.get("/")
async def root():
    return RedirectResponse(url="/static/")

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    log_filename = lm.create_log_filename(conversation_log_dir)
    lm.write_operation_log(operation_log_filename, "INFO", "Main", f"Conversation log file created: {log_filename}")
    print(f"Conversation log file: {log_filename}")

    manager = cm.CharacterManager(log_filename, operation_log_filename)

    lm.write_operation_log(operation_log_filename, "INFO", "WebSocket", "New WebSocket connection established.")
    await websocket.accept()
    lm.write_operation_log(operation_log_filename, "INFO", "WebSocket", "WebSocket connection accepted.")
    try:
        characters = manager.list_characters()
        config_data = [{"name": char["name"], "display_name": char.get("display_name", char["name"])} for char in characters]
        await websocket.send_json({
            "type": "config",
            "characters": config_data
        })
        lm.write_operation_log(operation_log_filename, "INFO", "WebSocket", "Character configuration sent to client.")
        
        await wm.websocket_endpoint(websocket, manager, log_filename, operation_log_filename)
        
    except Exception as e:
        error_details = traceback.format_exc()
        lm.write_operation_log(operation_log_filename, "ERROR", "WebSocket", f"Error in WebSocket endpoint: {e}\n{error_details}")
        print(f"WebSocket error: {e} (Log file: {log_filename})")
    finally:
        lm.write_operation_log(operation_log_filename, "INFO", "WebSocket", "WebSocket connection closed.")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
