from fastapi import WebSocket

from character_manager import CharacterManager
from status_manager import update_all_statuses, update_status
from log_manager import write_operation_log
from readiness_checker import ensure_ollama_model_ready_sync

async def set_initial_statuses(websocket: WebSocket, manager: CharacterManager, log_filename: str, operation_log_filename: str):
    write_operation_log(operation_log_filename, "INFO", "InitialStatusSetter", "Setting initial statuses for characters.")

    # まず全員を IDLE に
    await update_all_statuses(websocket, manager.get_character_names(), "IDLE", log_filename, operation_log_filename)

    # Ollama の場合のみモデルロードを確認し、準備完了のキャラから ACTIVE に
    for char in manager.list_characters():
        provider = char.get("provider", "").lower()
        display_name = char.get("display_name", char.get("name"))
        if provider == "ollama":
            base_url = char.get("base_url", "http://localhost:11434")
            model = char.get("model")
            ready = ensure_ollama_model_ready_sync(base_url, model, operation_log_filename)
            status = "ACTIVE" if ready else "IDLE"
            await update_status(websocket, display_name, status, log_filename, operation_log_filename)
        else:
            # それ以外のプロバイダは従来通り ACTIVE
            await update_status(websocket, display_name, "ACTIVE", log_filename, operation_log_filename)

    write_operation_log(operation_log_filename, "INFO", "InitialStatusSetter", "Initial statuses set for all characters.")
