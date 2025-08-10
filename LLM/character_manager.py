from typing import List, Dict, Any
import os

import yaml

from llm_factory import LLMFactory
from llm_instance_manager import LLMInstanceManager
from persona_manager import PersonaManager
from log_manager import write_operation_log

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
        
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", "CharacterManager initialized.")

    def get_llm(self, character_name: str):
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", f"Getting LLM for {character_name}.")
        
        # display_name（UI表示）→ 対応する internal_id を解決
        character_config = next((char for char in self.character_configs if char.get("display_name", char["name"]) == character_name or char.get("name") == character_name), None)
        
        if character_config:
            provider = character_config.get("provider", "openai")
            model = character_config.get("model", "gpt-4")
            base_url = character_config.get("base_url", None)
            
            llm = self.llm_manager.get_llm(character_name, provider, model, self.llm_factory, base_url)
            
            write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", f"LLM retrieved for {character_name}.")
            return llm
            
        write_operation_log(self.operation_log_filename, "WARNING", "CharacterManager", f"Character {character_name} not found.")
        return None

    def get_persona_prompt(self, character_name: str) -> str:
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", f"Getting persona prompt for {character_name}.")
        prompt = self.persona_manager.get_persona_prompt(character_name)
        return prompt

    def list_characters(self) -> List[Dict[str, Any]]:
        return self.character_configs

    def get_character_names(self) -> List[str]:
        return [char.get("display_name", char["name"]) for char in self.character_configs]
