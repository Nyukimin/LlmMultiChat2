import asyncio
import traceback
import os
import sys
import sqlite3
import importlib
from typing import List, Optional
from fastapi import FastAPI, WebSocket, Body, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse, Response
import uvicorn

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import character_manager as cm
import websocket_manager as wm
import log_manager as lm
import yaml
from readiness_checker import ensure_ollama_model_ready_sync
from ingest_mode import run_ingest_mode  # type: ignore
import json
from web_search import search_text
import yaml
import sqlite3

app = FastAPI()

# CORS: フロントを外部サーブ/ローカルfileスキームから開いた場合でもAPIを叩けるように許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "../html"), html=True), name="static")

operation_log_filename = ""
conversation_log_dir = None
operation_log_dir = None
_last_ingest_result_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "last_ingest.json")
_stop_flags: dict[str, bool] = {}

# ---- Favicon handler to avoid 404 spam ----
@app.get("/favicon.ico")
async def favicon_handler():
    icon_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'html', 'favicon.ico'))
    if os.path.exists(icon_path):
        return FileResponse(icon_path)
    # No icon file provided → return 204 No Content quietly
    return Response(status_code=204)

def _resolve_kb_db_path() -> str:
    try:
        kb_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'KB', 'config.yaml')
        root_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
        kb_dir = os.path.join(root_dir, 'KB')
        with open(kb_cfg_path, 'r', encoding='utf-8') as f:
            kb_cfg = yaml.safe_load(f) or {}
        db_path = kb_cfg.get('db_path') or 'media.db'
        if not os.path.isabs(db_path):
            # ルール: サブディレクトリを含む場合はプロジェクトルート基準、
            # 単純ファイル名の場合は KB ディレクトリ基準
            if ("/" in db_path) or ("\\" in db_path):
                db_path = os.path.abspath(os.path.join(root_dir, db_path))
            else:
                db_path = os.path.abspath(os.path.join(kb_dir, db_path))
        return db_path
    except Exception:
        # フォールバック: 既定の KB/DB/media.db（絶対化）
        return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'KB', 'DB', 'media.db'))

@app.get("/api/db/path")
async def api_db_path():
    return {"ok": True, "db": _resolve_kb_db_path()}

# KBユーティリティの動的ロード（パッケージ化されていないKB直下から）
_kb_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'KB'))
if _kb_dir not in sys.path:
    sys.path.append(_kb_dir)
try:
    from cleanup_dedup import run_cleanup  # type: ignore
except Exception:
    run_cleanup = None  # type: ignore

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
    # KB設定を読み込み
    default_db = _resolve_kb_db_path()
    db = str(payload.get("db") or default_db)
    strict = bool(payload.get("strict") or False)
    topic_type = str(payload.get("topicType") or "unknown").strip().lower()
    # KB設定から最大自動巡回数を取得（無ければ3）
    # KB設定からオート継続回数
    try:
        kb_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'KB', 'config.yaml')
        with open(kb_cfg_path, 'r', encoding='utf-8') as f:
            kb_cfg = yaml.safe_load(f) or {}
        v = kb_cfg.get('max_auto_next') if isinstance(kb_cfg, dict) else None
    except Exception:
        v = None
    auto_next_max = v if isinstance(v, int) and v >= 0 else 3
    lm.write_operation_log(operation_log_filename, "INFO", "API", f"Ingest requested: topic={topic}, domain={domain}, rounds={rounds}, strict={strict}")
    # ログをフロントへ逐次返すための簡易バッファ
    logs: list[str] = []
    def _cb(m: str) -> None:
        logs.append(m)

    # STOPボタン対応: /api/ingest 呼び出し単位の簡易フラグ
    session_id = str(payload.get("session") or "default-session")
    _stop_flags.setdefault(session_id, False)
    def _cancel() -> bool:
        return bool(_stop_flags.get(session_id))

    result = await run_ingest_mode(topic, domain, rounds, db, expand=True, strict=strict, log_callback=_cb, cancel_check=_cancel, topic_type=topic_type, auto_next_max=auto_next_max)
    try:
        os.makedirs(os.path.dirname(_last_ingest_result_path), exist_ok=True)
        with open(_last_ingest_result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return {"ok": True, "result": result, "logs": logs}

@app.post("/api/ingest/stop")
async def api_ingest_stop(payload: dict = Body(...)):
    session_id = str(payload.get("session") or "default-session")
    _stop_flags[session_id] = True
    return {"ok": True}

@app.post("/api/kb/init")
async def api_kb_init(payload: dict = Body(...)):
    """KB初期化はKB公式APIに委譲。"""
    try:
        # 動的ロード
        if _kb_dir not in sys.path:
            sys.path.append(_kb_dir)
        import api as kb  # type: ignore
        reset = bool(payload.get("reset", False))
        res = kb.init_db(reset=reset)
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/kb/cleanup")
async def api_kb_cleanup(payload: dict = Body(...)):
    """一括クリーンアップ（特殊機能）。既存DBに対して重複排除/統合/FTS再構築を実行。
    body: { dry_run: bool, vacuum: bool, db?: str }
    """
    db = str(payload.get("db") or _resolve_kb_db_path())
    dry_run = bool(payload.get("dry_run", True))
    vacuum = bool(payload.get("vacuum", False))
    if run_cleanup is None:
        return {"ok": False, "error": "cleanup module not available", "db_path": db}
    try:
        res = run_cleanup(db, dry_run=dry_run, vacuum=vacuum)
        # 正規化して返却
        return {
            "ok": bool(res.get("ok", True)),
            "db_path": db,
            "backup_path": res.get("backup_path"),
            "stats": res.get("stats"),
            "logs": res.get("logs", []),
            "error": res.get("error"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "db_path": db}

# ==== KB Query API ====

def _default_db_path() -> str:
    # KB/config.yaml の db_path（相対なら KB 直下基準）を解決
    return _resolve_kb_db_path()

def _open_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or _default_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/api/db/persons")
async def api_db_persons(keyword: str = Query(..., description="人名の部分一致キーワード"), db: Optional[str] = Query(None)):
    try:
        if _kb_dir not in sys.path:
            sys.path.append(_kb_dir)
        import api as kb  # type: ignore
        items = kb.persons_search(keyword)
        return {"ok": True, "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/db/persons/{person_id}/credits")
async def api_db_person_credits(person_id: int = Path(...), db: Optional[str] = Query(None)):
    try:
        if _kb_dir not in sys.path:
            sys.path.append(_kb_dir)
        import api as kb  # type: ignore
        items = kb.person_credits(person_id)
        return {"ok": True, "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/db/persons/{person_id}")
async def api_db_person_detail(person_id: int = Path(...), db: Optional[str] = Query(None)):
    try:
        if _kb_dir not in sys.path:
            sys.path.append(_kb_dir)
        import api as kb  # type: ignore
        item = kb.person_detail(person_id)
        return {"ok": True, "item": item}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/db/works")
async def api_db_works(keyword: str = Query(..., description="作品名の部分一致キーワード"), db: Optional[str] = Query(None)):
    try:
        if _kb_dir not in sys.path:
            sys.path.append(_kb_dir)
        import api as kb  # type: ignore
        items = kb.works_search(keyword)
        return {"ok": True, "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/db/works/{work_id}/cast")
async def api_db_work_cast(work_id: int = Path(...), db: Optional[str] = Query(None)):
    try:
        if _kb_dir not in sys.path:
            sys.path.append(_kb_dir)
        import api as kb  # type: ignore
        items = kb.work_cast(work_id)
        return {"ok": True, "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/db/works/{work_id}")
async def api_db_work_detail(work_id: int = Path(...), db: Optional[str] = Query(None)):
    try:
        if _kb_dir not in sys.path:
            sys.path.append(_kb_dir)
        import api as kb  # type: ignore
        item = kb.work_detail(work_id)
        return {"ok": True, "item": item}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/db/fts")
async def api_db_fts(q: str = Query(..., description="FTS5 検索クエリ"), limit: int = Query(50, ge=1, le=200), db: Optional[str] = Query(None)):
    try:
        if _kb_dir not in sys.path:
            sys.path.append(_kb_dir)
        import api as kb  # type: ignore
        items = kb.fts_search(q, limit)
        return {"ok": True, "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/db/unified")
async def api_db_unified(title: str = Query(..., description="起点となる作品タイトルの部分一致"), db: Optional[str] = Query(None)):
    try:
        if _kb_dir not in sys.path:
            sys.path.append(_kb_dir)
        import api as kb  # type: ignore
        items = kb.unified_by_title(title)
        return {"ok": True, "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ==== Suggest API ====
@app.get("/api/suggest")
async def api_suggest(q: str = Query(..., description="入力文字列"), type: str = Query("unknown", description="work|person|unknown"), limit: int = Query(8, ge=1, le=20)):
    q = (q or "").strip()
    t = (type or "unknown").lower()
    if not q:
        return {"ok": True, "items": []}
    if t == "work":
        query = f"{q} site:eiga.com/movie"
    elif t == "person":
        query = f"{q} site:eiga.com/person"
    else:
        # デフォルトは映画ドメインの可能性を考慮して作品優先
        query = f"{q} site:eiga.com/movie"
    try:
        hits = search_text(query, region="jp-jp", max_results=limit, safesearch="moderate")
    except Exception:
        hits = []
    items = []
    for h in hits:
        items.append({
            "title": h.get("title"),
            "url": h.get("url") or h.get("href"),
            "snippet": h.get("snippet")
        })
    return {"ok": True, "items": items[:limit]}

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
        characters = [c for c in manager.list_characters() if not c.get("hidden")]
        config_data = [{
            "name": char["name"],
            "display_name": char.get("display_name", char["name"]),
            "short_name": char.get("short_name", "")
        } for char in characters]
        await websocket.send_json({
            "type": "config",
            "characters": config_data
        })
        # クライアントの接続直後の検索モード通知を受けるため、何もしないがログは残す
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
