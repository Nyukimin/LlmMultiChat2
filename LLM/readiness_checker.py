import json
import ssl
import urllib.request
from typing import Optional

from log_manager import write_operation_log


def _http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        status = resp.getcode()
        body = resp.read().decode("utf-8", errors="ignore")
        return status, body


def _http_post_json(url: str, payload: dict, timeout: float = 10.0) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        status = resp.getcode()
        body = resp.read().decode("utf-8", errors="ignore")
        return status, body


def ensure_ollama_model_ready_sync(base_url: str, model: str, operation_log_filename: Optional[str] = None) -> bool:
    """
    Ollama の疎通/モデル存在/ロード有無を確認し、未ロードなら軽量生成でウォームアップする（同期）。
    1) GET /api/tags でサーバ生存確認
    2) POST /api/show {name:model} でモデル存在確認
    3) GET /api/ps でロード状況確認
    4) 未ロードなら POST /api/generate {prompt:" ", stream:false, options:{num_predict:0}} でウォーム
    """
    try:
        # 1) server reachable
        status, _ = _http_get(f"{base_url}/api/tags")
        if status != 200:
            if operation_log_filename:
                write_operation_log(operation_log_filename, "WARNING", "ReadinessChecker", f"Ollama not reachable: {base_url}")
            return False

        # 2) model exists
        status, _ = _http_post_json(f"{base_url}/api/show", {"name": model})
        if status != 200:
            if operation_log_filename:
                write_operation_log(operation_log_filename, "WARNING", "ReadinessChecker", f"Model not found on server: {model}")
            return False

        # 3) is loaded?
        status, body = _http_get(f"{base_url}/api/ps")
        loaded = (status == 200 and model.split(":")[0] in body)
        if not loaded:
            # 4) warm up (load into memory)
            payload = {"model": model, "prompt": " ", "stream": False, "options": {"num_predict": 0}}
            _http_post_json(f"{base_url}/api/generate", payload, timeout=60.0)

        if operation_log_filename:
            write_operation_log(operation_log_filename, "INFO", "ReadinessChecker", f"Ollama model ready: {model}")
        return True
    except Exception as e:
        if operation_log_filename:
            write_operation_log(operation_log_filename, "ERROR", "ReadinessChecker", f"Readiness check failed for {model}: {e}")
        return False


