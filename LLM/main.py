import os
import yaml
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
load_dotenv()

from langchain_community.chat_models import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic

# --- LLMプロバイダー登録簿 (変更なし) ---
PROVIDER_REGISTRY = {
    "ollama": {"class": ChatOllama, "requires_api_key": False},
    "openai": {"class": ChatOpenAI, "requires_api_key": True},
    "gemini": {"class": ChatGoogleGenerativeAI, "requires_api_key": True},
    "anthropic": {"class": ChatAnthropic, "requires_api_key": True},
    "openrouter": {
        "class": ChatOpenAI,
        "requires_api_key": True,
        "extra_params": {"base_url": "https://openrouter.ai/api/v1"}
    }
}

class LLMFactory:
    @staticmethod
    def create_llm(provider: str, model: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        if provider not in PROVIDER_REGISTRY:
            raise ValueError(f"サポートされていないプロバイダーです: {provider}")
        registry_info = PROVIDER_REGISTRY[provider]
        llm_class = registry_info["class"]
        kwargs = {"model": model}
        if registry_info["requires_api_key"]:
            if not api_key: raise ValueError(f"プロバイダー「{provider}」にはAPIキーが必要です。")
            kwargs["google_api_key" if provider == "gemini" else "api_key"] = api_key
        if provider == "ollama" and base_url:
            kwargs["base_url"] = base_url
        if "extra_params" in registry_info:
            kwargs.update(registry_info["extra_params"])
        return llm_class(**kwargs)

class CharacterManager:
    """
    キャラクターとLLM、ペルソナを管理し、対話を実行するクラス
    """
    def __init__(self, config_path: str, persona_path: str):
        self.characters: Dict[str, Any] = {}
        self.character_configs: List[Dict[str, Any]] = []
        self.personas: Dict[str, Any] = {}

        # 1. LLM接続設定を読み込む
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        self.character_configs = config.get("characters", [])

        # ★★★ 修正点1: ペルソナ設定を読み込む ★★★
        with open(persona_path, 'r', encoding='utf-8') as f:
            self.personas = yaml.safe_load(f)

        print("--- LLM接続セットアップ開始 ---")
        for char_config in self.character_configs:
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

    # ★★★ 修正点2: ペルソナを取得するメソッドを追加 ★★★
    def get_persona_prompt(self, character_name: str) -> Optional[str]:
        """キャラクター名に対応するシステムプロンプトを取得する"""
        # config.yamlの名前(例:ルミナ)からpersonas.yamlのキー(例:LUMINA)を特定
        persona_key = character_name.upper() # 簡単な例として大文字に変換
        persona_data = self.personas.get(persona_key)
        return persona_data.get("system_prompt") if persona_data else None

    def list_characters(self) -> List[Dict[str, Any]]:
        return self.character_configs

# --- メインの実行部分 ---
if __name__ == "__main__":
    try:
        # ★★★ 修正点3: CharacterManagerにペルソナファイルのパスを渡す ★★★
        manager = CharacterManager(config_path="config.yaml", persona_path="personas.yaml")
        
        print("--- 対話シミュレーション開始 ---")
        characters_to_chat = manager.list_characters()
        
        for char_info in characters_to_chat:
            char_name = char_info["name"]
            llm = manager.get_llm(char_name)
            
            if llm:
                # ★★★ 修正点4: ペルソナを読み込んでプロンプトを生成 ★★★
                system_prompt = manager.get_persona_prompt(char_name)
                if not system_prompt:
                    print(f"⚠️ 「{char_name}」のペルソナがpersonas.yamlに見つかりません。")
                    system_prompt = "あなたは親切なAIアシスタントです。日本語で応答してください。" # デフォルトの指示

                user_query = "日本の首都はどこですか？"
                
                # LangChainが推奨するプロンプト形式（システムプロンプトとユーザープロンプトの組み合わせ）
                from langchain_core.messages import SystemMessage, HumanMessage
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_query)
                ]

                print(f"\n[{char_info['short_name']}] {char_name}への問い合わせ: 「{user_query}」")
                
                try:
                    response = llm.invoke(messages)
                    print(f"🤖 {char_name}の応答:\n{response.content}")
                except Exception as e:
                    print(f"❌ 「{char_name}」との対話中にエラー: {e}")
            else:
                print(f"⚠️ 「{char_name}」のLLMはセットアップされていません。")

    except FileNotFoundError as e:
        print(f"❌ エラー: 設定ファイルが見つかりません。({e.filename})")
    except Exception as e:
        print(f"❌ 予期せぬエラーが発生しました: {e}")

