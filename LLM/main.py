import asyncio
import traceback
import os
import sys
import sqlite3
from typing import List, Optional
from fastapi import FastAPI, WebSocket, Body, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import uvicorn

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import character_manager as cm
import websocket_manager as wm
import log_manager as lm
import yaml
from readiness_checker import ensure_ollama_model_ready_sync
from ingest_mode import run_ingest_mode  # type: ignore
import json

app = FastAPI()

# CORS: フロントを外部サーブ/ローカルfileスキームから開いた場合でもAPIを叩けるように許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "../html"), html=True), name="static")

operation_log_filename = ""
conversation_log_dir = None
operation_log_dir = None
_last_ingest_result_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "last_ingest.json")

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

@app.post("/api/ingest")
async def api_ingest(payload: dict = Body(...)):
    """
    JSON: {"topic": str, "domain": str, "rounds": int, "db": str, "strict": bool}
    """
    topic = str(payload.get("topic") or "").strip()
    domain = str(payload.get("domain") or "映画").strip()
    rounds = int(payload.get("rounds") or 1)
    db = str(payload.get("db") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "KB", "media.db"))
    strict = bool(payload.get("strict") or False)
    lm.write_operation_log(operation_log_filename, "INFO", "API", f"Ingest requested: topic={topic}, domain={domain}, rounds={rounds}, strict={strict}")
    # ログをフロントへ逐次返すための簡易バッファ
    logs: list[str] = []
    def _cb(m: str) -> None:
        logs.append(m)

    result = await run_ingest_mode(topic, domain, rounds, db, expand=True, strict=strict, log_callback=_cb)
    try:
        os.makedirs(os.path.dirname(_last_ingest_result_path), exist_ok=True)
        with open(_last_ingest_result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return {"ok": True, "result": result, "logs": logs}

# ==== KB Query API ====

def _default_db_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "KB", "media.db")

def _open_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or _default_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/api/db/persons")
async def api_db_persons(keyword: str = Query(..., description="人名の部分一致キーワード"), db: Optional[str] = Query(None)):
    with _open_db(db) as conn:
        cur = conn.execute(
            "SELECT id, name FROM person WHERE name LIKE ? ORDER BY name LIMIT 50",
            (f"%{keyword}%",),
        )
        return {"ok": True, "items": [dict(r) for r in cur.fetchall()]}

@app.get("/api/db/persons/{person_id}/credits")
async def api_db_person_credits(person_id: int = Path(...), db: Optional[str] = Query(None)):
    with _open_db(db) as conn:
        cur = conn.execute(
            """
            SELECT w.id AS work_id, w.title, w.year, c.role, c.character
            FROM credit c
            JOIN work w ON w.id=c.work_id
            WHERE c.person_id=?
            ORDER BY w.year IS NULL, w.year, w.title
            """,
            (person_id,),
        )
        return {"ok": True, "items": [dict(r) for r in cur.fetchall()]}

@app.get("/api/db/works")
async def api_db_works(keyword: str = Query(..., description="作品名の部分一致キーワード"), db: Optional[str] = Query(None)):
    with _open_db(db) as conn:
        cur = conn.execute(
            "SELECT id, title, year FROM work WHERE title LIKE ? ORDER BY year DESC, title LIMIT 50",
            (f"%{keyword}%",),
        )
        return {"ok": True, "items": [dict(r) for r in cur.fetchall()]}

@app.get("/api/db/works/{work_id}/cast")
async def api_db_work_cast(work_id: int = Path(...), db: Optional[str] = Query(None)):
    with _open_db(db) as conn:
        cur = conn.execute(
            """
            SELECT p.id AS person_id, p.name, c.role, c.character
            FROM credit c
            JOIN person p ON p.id=c.person_id
            WHERE c.work_id=?
            ORDER BY CASE c.role WHEN 'director' THEN 0 WHEN 'actor' THEN 1 ELSE 9 END, p.name
            """,
            (work_id,),
        )
        return {"ok": True, "items": [dict(r) for r in cur.fetchall()]}

@app.get("/api/db/fts")
async def api_db_fts(q: str = Query(..., description="FTS5 検索クエリ"), limit: int = Query(50, ge=1, le=200), db: Optional[str] = Query(None)):
    with _open_db(db) as conn:
        cur = conn.execute(
            "SELECT kind, ref_id, snippet(fts, 1, '[', ']', '...', 10) AS snippet FROM fts WHERE fts MATCH ? LIMIT ?",
            (q, limit),
        )
        return {"ok": True, "items": [dict(r) for r in cur.fetchall()]}

@app.get("/api/db/unified")
async def api_db_unified(title: str = Query(..., description="起点となる作品タイトルの部分一致"), db: Optional[str] = Query(None)):
    with _open_db(db) as conn:
        sql = (
            """
            WITH target AS (
              SELECT uw.id AS unified_id
              FROM work w
              JOIN unified_work_member uwm ON uwm.work_id=w.id
              JOIN unified_work uw ON uw.id=uwm.unified_work_id
              WHERE w.title LIKE ?
              LIMIT 1
            )
            SELECT w.id AS work_id, w.title, w.year, c.name AS category, uwm.relation
            FROM unified_work_member uwm
            JOIN work w ON w.id=uwm.work_id
            JOIN category c ON c.id=w.category_id
            JOIN target t ON t.unified_id=uwm.unified_work_id
            ORDER BY w.year, w.title
            """
        )
        cur = conn.execute(sql, (f"%{title}%",))
        return {"ok": True, "items": [dict(r) for r in cur.fetchall()]}

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
