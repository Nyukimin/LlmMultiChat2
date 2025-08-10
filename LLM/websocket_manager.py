from fastapi import WebSocket

from character_manager import CharacterManager
from conversation_loop import conversation_loop
from log_manager import write_operation_log

async def websocket_endpoint(websocket: WebSocket, manager: CharacterManager, log_filename: str, operation_log_filename: str):
    write_operation_log(operation_log_filename, "INFO", "WebSocketManager", "WebSocket endpoint activated.")
    try:
        await conversation_loop(websocket, manager, log_filename, operation_log_filename)
    except Exception as e:
        write_operation_log(operation_log_filename, "ERROR", "WebSocketManager", f"Error in WebSocket endpoint: {e}")
        raise
    finally:
        write_operation_log(operation_log_filename, "INFO", "WebSocketManager", "WebSocket endpoint finished.")
