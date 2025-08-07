import os
import datetime
import re

LOG_DIR = "logs"

def create_log_filename():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(LOG_DIR, f"conversation_{timestamp}.log")

def write_log(filename: str, speaker: str, text: str):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    with open(filename, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {speaker}: {text}\n")

def read_log(filename: str) -> str:
    if not os.path.exists(filename):
        return ""
    with open(filename, 'r', encoding='utf-8') as f:
        return f.read()
