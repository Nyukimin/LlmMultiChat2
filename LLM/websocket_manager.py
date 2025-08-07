from fastapi import WebSocket, WebSocketDisconnect
from character_manager import CharacterManager
from conversation_loop import conversation_loop
from log_manager import write_log, write_operation_log, create_operation_log_filename

log_filename = ""
operation_log_filename = create_operation_log_filename()

async def websocket_endpoint(websocket: WebSocket, manager: CharacterManager):
    global log_filename
    write_log(log_filename, "WebSocketManager", "WebSocket endpoint activated.")
    write_operation_log(operation_log_filename, "INFO", "WebSocketManager", "WebSocket endpoint activated.")
    # accept()はws_endpoint内で既に呼び出されているため、ここでは呼び出さない
    write_log(log_filename, "WebSocketManager", "WebSocket accepted.")
    write_operation_log(operation_log_filename, "INFO", "WebSocketManager", "WebSocket accepted.")
    
    try:
        await conversation_loop(websocket, manager)
        write_operation_log(operation_log_filename, "INFO", "WebSocketManager", "Conversation loop completed.")
    except WebSocketDisconnect:
        write_log(log_filename, "WebSocketManager", "Client disconnected from WebSocket.")
        print(f"クライアントとの接続が切れました。")
    except Exception as e:
        write_log(log_filename, "WebSocketManager", f"Error in WebSocket endpoint: {e}")
        write_operation_log(operation_log_filename, "ERROR", "WebSocketManager", f"Error in WebSocket endpoint: {e}")
        raise
    finally:
        write_log(log_filename, "WebSocketManager", "WebSocket endpoint finished.")
        write_operation_log(operation_log_filename, "INFO", "WebSocketManager", "WebSocket endpoint finished.")
