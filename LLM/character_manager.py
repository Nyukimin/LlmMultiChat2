from typing import List, Dict, Any
import os

import yaml

from llm_factory import LLMFactory
from llm_instance_manager import LLMInstanceManager
from persona_manager import PersonaManager
from log_manager import write_operation_log
import yaml

class CharacterManager:
    def __init__(self, log_filename: str, operation_log_filename: str, config_path: str = None, persona_path: str = None):
        self.log_filename = log_filename
        self.operation_log_filename = operation_log_filename
        
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", "Initializing CharacterManager.")
        # ベースディレクトリをこのファイルの位置に固定し、相対パス問題を回避
        base_dir = os.path.dirname(os.path.abspath(__file__))
        resolved_config_path = config_path or os.path.join(base_dir, 'config.yaml')
        resolved_persona_path = persona_path or os.path.join(base_dir, 'personas.yaml')

        with open(resolved_config_path, 'r', encoding='utf-8') as file:
            self.character_configs = yaml.safe_load(file).get('characters', [])
        
        self.llm_factory = LLMFactory(self.log_filename, self.operation_log_filename)
        self.llm_manager = LLMInstanceManager(self.log_filename, self.operation_log_filename)
        self.persona_manager = PersonaManager(self.log_filename, self.operation_log_filename, resolved_persona_path)

        # ユーザープロファイル読み込み（任意）
        self.user_profile = {}
        user_profile_path = os.path.join(base_dir, 'user_profile.yaml')
        try:
            if os.path.exists(user_profile_path):
                with open(user_profile_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                    self.user_profile = data.get('profile') or {}
        except Exception:
            self.user_profile = {}
        
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", "CharacterManager initialized.")

    def get_llm(self, character_name: str):
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", f"Getting LLM for {character_name}.")
        
        # display_name（UI表示）→ 対応する internal_id を解決
        character_config = next((char for char in self.character_configs if char.get("display_name", char["name"]) == character_name or char.get("name") == character_name), None)
        
        if character_config:
            provider = character_config.get("provider", "openai")
            model = character_config.get("model", "gpt-4o-mini")
            base_url = character_config.get("base_url", None)
            gen_params = character_config.get("generation", {}) or {}
            
            llm = self.llm_manager.get_llm(character_name, provider, model, self.llm_factory, base_url, gen_params)
            
            write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", f"LLM retrieved for {character_name}.")
            return llm
            
        write_operation_log(self.operation_log_filename, "WARNING", "CharacterManager", f"Character {character_name} not found.")
        return None

    def get_persona_prompt(self, character_name: str) -> str:
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", f"Getting persona prompt for {character_name}.")
        persona = self.persona_manager.get_persona_prompt(character_name)
        # ユーザープロファイルを末尾に付加（軽量）
        if self.user_profile:
            up = self.user_profile
            extras = []
            if up.get('birth_date') or up.get('gender'):
                extras.append(f"ユーザー: {up.get('birth_date','?')} 生まれ / {up.get('gender','?')}")
            if up.get('personality'):
                pers = up['personality']
                af = pers.get('animal_fortune')
                mbti = pers.get('mbti')
                extras.append(f"性格参考: 動物占い={af or '-'}, MBTI={mbti or '-'}")
            if up.get('career'):
                extras.append(f"職歴: {up['career'].get('since','?')}年〜 {up['career'].get('role','')}".strip())
            if up.get('family'):
                extras.append("家族: 結婚(2000)、娘(2008) 中学受験に付き添い")
            if up.get('interaction_preferences'):
                ip = up['interaction_preferences']
                extras.append("会話方針: ユーザー発言には『よろしくお願いします』が含意。あなたの返答は『ありがとうございます』の姿勢で。短く分かりやすい文章を心がける。")
            if up.get('social_watch'):
                extras.append("参考リンクを随時ウォッチ: " + ", ".join(up['social_watch']))
            user_block = "\n\n## ユーザープロファイル（要約）\n- " + "\n- ".join(extras)
            return (persona or "") + user_block
        return persona

    def list_characters(self) -> List[Dict[str, Any]]:
        return self.character_configs

    def get_character_names(self, include_hidden: bool = False) -> List[str]:
        names: List[str] = []
        for char in self.character_configs:
            if not include_hidden and bool(char.get("hidden")):
                continue
            names.append(char.get("display_name", char["name"]))
        return names
