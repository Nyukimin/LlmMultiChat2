from fastapi import WebSocket

from character_manager import CharacterManager
from status_manager import update_all_statuses
from log_manager import write_log, write_operation_log, create_operation_log_filename

async def set_initial_statuses(websocket: WebSocket, manager: CharacterManager):
    log_filename = ""
    operation_log_filename = create_operation_log_filename()
    write_log(log_filename, "InitialStatusSetter", "Setting initial statuses for characters.")
    write_operation_log(operation_log_filename, "INFO", "InitialStatusSetter", "Setting initial statuses for characters.")
    await update_all_statuses(websocket, manager.get_character_names(), "ACTIVE")
    write_log(log_filename, "InitialStatusSetter", "Initial statuses set for all characters.")
    write_operation_log(operation_log_filename, "INFO", "InitialStatusSetter", "Initial statuses set for all characters.")
