from datetime import datetime
import os
import re
from typing import Optional

# 既定ディレクトリ
DEFAULT_CONVERSATION_LOG_DIR = os.path.join("LLM", "logs")
DEFAULT_OPERATION_LOG_DIR = "logs"  # ルート配下に集約


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def create_log_filename(log_dir: Optional[str] = None) -> str:
    target_dir = log_dir or DEFAULT_CONVERSATION_LOG_DIR
    _ensure_dir(target_dir)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    return os.path.join(target_dir, f"conversation_{timestamp}.log")


def create_operation_log_filename(op_dir: Optional[str] = None) -> str:
    target_dir = op_dir or DEFAULT_OPERATION_LOG_DIR
    _ensure_dir(target_dir)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    return os.path.join(target_dir, f"operation_{timestamp}.log")

def write_log(filename, speaker, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(filename, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] [{speaker}] {message}\n")

def write_operation_log(filename, level, module, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(filename, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] [{level}] [{module}] {message}\n")

def get_formatted_conversation_history(filename, max_lines=50):
    """Reads the log file and returns a clean, formatted conversation history for the LLM."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Keep only the most recent lines
        recent_lines = lines[-max_lines:]
        
        formatted_history = []
        # Regex to capture only USER or character messages, ignoring [System]
        log_pattern = re.compile(r"\[.*?\] \[(?!System)(.*?)\] (.*)")
        
        for line in recent_lines:
            match = log_pattern.match(line)
            if match:
                speaker, message = match.groups()
                # Simple format: Speaker: Message
                formatted_history.append(f"{speaker}: {message.strip()}")
        
        return "\n".join(formatted_history)
        
    except FileNotFoundError:
        return ""

# Keep the old read_log for other purposes if needed, or remove if unused.
def read_log(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return ""
