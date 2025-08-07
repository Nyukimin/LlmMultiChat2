from typing import List

from fastapi import WebSocket

from log_manager import write_log, write_operation_log

async def update_status(websocket: WebSocket, character: str, status: str, log_filename: str, operation_log_filename: str):
    write_log(log_filename, "StatusManager", f"Updating status for {character} to {status}.")
    write_operation_log(operation_log_filename, "INFO", "StatusManager", f"Updating status for {character} to {status}.")
    await websocket.send_json({
        "type": "status",
        "character": character,
        "status": status
    })
    write_log(log_filename, "StatusManager", f"Status updated for {character} to {status}.")
    write_operation_log(operation_log_filename, "INFO", "StatusManager", f"Status updated for {character} to {status}.")

async def update_all_statuses(websocket: WebSocket, characters: List[str], status: str, log_filename: str, operation_log_filename: str):
    write_log(log_filename, "StatusManager", f"Updating status for all characters to {status}.")
    write_operation_log(operation_log_filename, "INFO", "StatusManager", f"Updating status for all characters to {status}.")
    for char in characters:
        await update_status(websocket, char, status, log_filename, operation_log_filename)
    write_log(log_filename, "StatusManager", f"Status updated for all characters to {status}.")
    write_operation_log(operation_log_filename, "INFO", "StatusManager", f"Status updated for all characters to {status}.")
