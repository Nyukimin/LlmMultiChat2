import os
from datetime import datetime
import pytz

# ログディレクトリの設定
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
JST = pytz.timezone('Asia/Tokyo')

def get_jst_now():
    """JSTの現在時刻を取得する"""
    return datetime.now(JST)

def create_log_filename():
    """JSTに基づいたログファイル名を生成する"""
    return f"conversation_{get_jst_now().strftime('%Y%m%d_%H%M%S')}.txt"

def get_log_filepath(log_filename):
    """ログファイルのフルパスを取得する"""
    return os.path.join(LOG_DIR, log_filename)

def write_log(log_filename, speaker, message):
    """指定されたログファイルに会話を追記する"""
    filepath = get_log_filepath(log_filename)
    timestamp = get_jst_now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{speaker}] [{timestamp}]: {message}"
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    except Exception as e:
        print(f"Error writing to log file {filepath}: {e}")

def read_log(log_filename):
    """指定されたログファイルの内容を読み込む"""
    filepath = get_log_filepath(log_filename)
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        return "" # ファイルが存在しない場合は空文字を返す
    except Exception as e:
        print(f"Error reading from log file {filepath}: {e}")
        return ""
