import os
import yaml
import asyncio
import re
from typing import List, Dict, Any, Optional

# FastAPIとWebSocketのインポート
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from dotenv import load_dotenv
load_dotenv()

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.chat_models import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic

# ログユーティリティのインポート
from log_utils import create_log_filename, write_log, read_log

# --- LLMプロバイダー登録簿とFactoryクラス ---
PROVIDER_REGISTRY = { "ollama": {"class": ChatOllama, "requires_api_key": False}, "openai": {"class": ChatOpenAI, "requires_api_key": True}, "gemini": {"class": ChatGoogleGenerativeAI, "requires_api_key": True}, "anthropic": {"class": ChatAnthropic, "requires_api_key": True}, "openrouter": { "class": ChatOpenAI, "requires_api_key": True, "extra_params": {"base_url": "https://openrouter.ai/api/v1"} } }
class LLMFactory:
    @staticmethod
    def create_llm(provider: str, model: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        if provider not in PROVIDER_REGISTRY: raise ValueError(f"サポートされていないプロバイダーです: {provider}")
        registry_info = PROVIDER_REGISTRY[provider]
        llm_class = registry_info["class"]
        kwargs = {"model": model}
        if registry_info["requires_api_key"]:
            if not api_key: raise ValueError(f"プロバイダー「{provider}」にはAPIキーが必要です。")
            kwargs["google_api_key" if provider == "gemini" else "api_key"] = api_key
        if provider == "ollama" and base_url: kwargs["base_url"] = base_url
        if "extra_params" in registry_info: kwargs.update(registry_info["extra_params"])
        return llm_class(**kwargs)

# --- CharacterManagerクラス ---
class CharacterManager:
    def __init__(self, config_path: str, persona_path: str):
        self.characters: Dict[str, Any] = {}; self.character_configs: List[Dict[str, Any]] = []; self.personas: Dict[str, Any] = {}
        with open(config_path, 'r', encoding='utf-8') as f: config = yaml.safe_load(f)
        self.character_configs = config.get("characters", [])
        with open(persona_path, 'r', encoding='utf-8') as f: self.personas = yaml.safe_load(f)
        print("--- LLM接続セットアップ開始 ---")
        for char_config in self.character_configs:
            name = char_config["name"]; provider = char_config["provider"]; model = char_config["model"]
            api_key_env = char_config.get("api_key_env"); api_key = os.getenv(api_key_env) if api_key_env else None; base_url = char_config.get("base_url")
            try:
                llm_instance = LLMFactory.create_llm(provider, model, api_key, base_url)
                self.characters[name] = llm_instance; connection_info = f"{provider}/{model}" + (f" @ {base_url}" if base_url else ""); print(f"✅ [OK] 「{name}」→ {connection_info}")
            except Exception as e: print(f"❌ [エラー] 「{name}」の接続に失敗: {e}")
        print("--- セットアップ完了 ---\n")
    def get_llm(self, character_name: str) -> Optional[Any]: return self.characters.get(character_name)
    def get_persona_prompt(self, character_name: str) -> Optional[str]:
        persona_key = character_name.upper(); persona_data = self.personas.get(persona_key)
        return persona_data.get("system_prompt") if persona_data else None
    def list_characters(self) -> List[Dict[str, Any]]: return self.character_configs
    def get_character_names(self) -> List[str]: return [char["name"] for char in self.character_configs]

# --- FastAPIアプリケーション ---
app = FastAPI()
manager = CharacterManager(config_path="config.yaml", persona_path="personas.yaml")

# --- Status Update Helper Functions ---
async def update_status(websocket: WebSocket, character: str, status: str):
    """指定されたキャラクターのステータスを更新する"""
    await websocket.send_json({"type": "status", "character": character, "status": status})

async def update_all_statuses(websocket: WebSocket, manager: CharacterManager, status: str):
    """全キャラクターのステータスを一括で更新する"""
    all_character_names = manager.get_character_names()
    # 全てのステータス更新を並行して行う
    await asyncio.gather(*(update_status(websocket, name, status) for name in all_character_names))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    log_filename = create_log_filename()
    print(f"新しい接続が開始されました。ログファイル: {log_filename}")

    # --- 初期ステータスをACTIVEに設定 ---
    try:
        await update_all_statuses(websocket, manager, "ACTIVE")
    except Exception as e:
        print(f"初期ステータス更新中にエラーが発生しました: {e}")

    # --- メインの会話ループ ---
    try:
        while True:
            user_query = await websocket.receive_text()
            write_log(log_filename, "USER", user_query)

            await update_all_statuses(websocket, manager, "IDLE")

            for char_name in manager.get_character_names():
                llm = manager.get_llm(char_name)
                
                if llm:
                    await update_status(websocket, char_name, "THINKING")
                    
                    system_prompt = manager.get_persona_prompt(char_name)
                    if not system_prompt: system_prompt = "あなたはAIです。日本語で応答してください。"
                    
                    conversation_log = read_log(log_filename)
                    other_characters = [name for name in manager.get_character_names() if name != char_name]
                    prompt_with_log = f"{system_prompt}\n\n他の参加者: {', '.join(other_characters)}\n\n--- これまでの会話 ---\n{conversation_log}\n--- 会話ここまで ---\n\n上記を踏まえて応答してください。"
                    
                    messages = [SystemMessage(content=prompt_with_log), HumanMessage(content=user_query)]
                    
                    response = await llm.ainvoke(messages)
                    response_text = response.content
                    
                    write_log(log_filename, char_name, response.content)
                    
                    display_text = re.sub(r'\[Next: .*?\]', '', response_text).strip()
                    
                    await websocket.send_json({
                        "type": "message",
                        "speaker": char_name,
                        "text": display_text
                    })

                    await update_status(websocket, char_name, "IDLE")
                    await asyncio.sleep(1)
            
            await update_all_statuses(websocket, manager, "ACTIVE")

    except WebSocketDisconnect:
        print(f"クライアントとの接続が切れました。ログファイル: {log_filename}")
    except Exception as e:
        print(f"エラーが発生しました: {e} (ログファイル: {log_filename})")

# 静的ファイルの配信
app.mount("/", StaticFiles(directory="../html", html=True), name="html")
