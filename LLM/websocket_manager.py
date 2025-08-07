from fastapi import WebSocket

from character_manager import CharacterManager
from conversation_loop import conversation_loop
from log_manager import write_log, write_operation_log

async def websocket_endpoint(websocket: WebSocket, manager: CharacterManager, log_filename: str, operation_log_filename: str):
    write_log(log_filename, "WebSocketManager", "WebSocket endpoint activated.")
    write_operation_log(operation_log_filename, "INFO", "WebSocketManager", "WebSocket endpoint activated.")
    write_log(log_filename, "WebSocketManager", "WebSocket accepted.")
    write_operation_log(operation_log_filename, "INFO", "WebSocketManager", "WebSocket accepted.")
    try:
        await conversation_loop(websocket, manager, log_filename, operation_log_filename)
        write_operation_log(operation_log_filename, "INFO", "WebSocketManager", "Conversation loop completed.")
    except Exception as e:
        write_log(log_filename, "WebSocketManager", f"Error in WebSocket endpoint: {e}")
        write_operation_log(operation_log_filename, "ERROR", "WebSocketManager", f"Error in WebSocket endpoint: {e}")
        raise
    finally:
        write_log(log_filename, "WebSocketManager", "WebSocket endpoint finished.")
        write_operation_log(operation_log_filename, "INFO", "WebSocketManager", "WebSocket endpoint finished.")
