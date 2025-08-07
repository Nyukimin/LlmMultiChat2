import os
import yaml
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

from llm_factory import LLMFactory

class LLMInstanceManager:
    def __init__(self, character_configs: List[Dict[str, Any]]):
        self.characters: Dict[str, Any] = {}
        print("--- LLM接続セットアップ開始 ---")
        for char_config in character_configs:
            name = char_config["name"]
            provider = char_config["provider"]
            model = char_config["model"]
            api_key_env = char_config.get("api_key_env")
            api_key = os.getenv(api_key_env) if api_key_env else None
            base_url = char_config.get("base_url")
            try:
                llm_instance = LLMFactory.create_llm(provider, model, api_key, base_url)
                self.characters[name] = llm_instance
                connection_info = f"{provider}/{model}" + (f" @ {base_url}" if base_url else "")
                print(f"✅ [OK] 「{name}」→ {connection_info}")
            except Exception as e:
                print(f"❌ [エラー] 「{name}」の接続に失敗: {e}")
        print("--- セットアップ完了 ---\n")

    def get_llm(self, character_name: str) -> Optional[Any]:
        return self.characters.get(character_name)
