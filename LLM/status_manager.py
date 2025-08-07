from fastapi import WebSocket
from typing import List, Dict, Any
import asyncio
from log_manager import write_log, create_log_filename, write_operation_log, create_operation_log_filename

log_filename = create_log_filename()

# CharacterManagerのインポートは不要になる
# from character_manager import CharacterManager 

async def update_status(websocket: WebSocket, character: str, status: str):
    log_filename = ""
    operation_log_filename = create_operation_log_filename()
    write_log(log_filename, "StatusManager", f"Updating status for {character} to {status}.")
    write_operation_log(operation_log_filename, "INFO", "StatusManager", f"Updating status for {character} to {status}.")
    await websocket.send_json({
        "type": "status",
        "character": character,
        "status": status
    })
    write_log(log_filename, "StatusManager", f"Status updated for {character} to {status}.")
    write_operation_log(operation_log_filename, "INFO", "StatusManager", f"Status updated for {character} to {status}.")

async def update_all_statuses(websocket: WebSocket, characters: List[str], status: str):
    log_filename = ""
    operation_log_filename = create_operation_log_filename()
    write_log(log_filename, "StatusManager", f"Updating status for all characters to {status}.")
    write_operation_log(operation_log_filename, "INFO", "StatusManager", f"Updating status for all characters to {status}.")
    for char in characters:
        await update_status(websocket, char, status)
    write_log(log_filename, "StatusManager", f"Status updated for all characters to {status}.")
    write_operation_log(operation_log_filename, "INFO", "StatusManager", f"Status updated for all characters to {status}.")
