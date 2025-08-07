import os
import yaml
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

from llm_factory import LLMFactory
from llm_instance_manager import LLMInstanceManager
from persona_manager import PersonaManager
from log_manager import write_log, write_operation_log, create_operation_log_filename

class CharacterManager:
    def __init__(self, log_filename: str, config_path: str = "LLM/config.yaml", persona_path: str = "LLM/personas.yaml"):
        self.log_filename = log_filename
        self.operation_log_filename = create_operation_log_filename()
        write_log(self.log_filename, "CharacterManager", "Initializing CharacterManager.")
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", "Initializing CharacterManager.")
        # 設定ファイルの読み込み
        with open(config_path, 'r', encoding='utf-8') as file:
            self.character_configs = yaml.safe_load(file).get('characters', [])
        self.llm_factory = LLMFactory(self.log_filename)
        self.llm_manager = LLMInstanceManager(self.log_filename, self.character_configs)
        self.persona_manager = PersonaManager(self.log_filename, persona_path)
        write_log(self.log_filename, "CharacterManager", "CharacterManager initialized.")
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", "CharacterManager initialized.")

    def get_llm(self, character_name: str):
        write_log(self.log_filename, "CharacterManager", f"Getting LLM for {character_name}.")
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", f"Getting LLM for {character_name}.")
        character_config = next((char for char in self.character_configs if char.get("display_name", char["name"]) == character_name), None)
        if character_config:
            provider = character_config.get("provider", "openai")
            model = character_config.get("model", "gpt-4")
            base_url = character_config.get("base_url", None)
            llm = self.llm_manager.get_llm(character_name, provider, model, base_url)
            write_log(self.log_filename, "CharacterManager", f"LLM retrieved for {character_name}.")
            write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", f"LLM retrieved for {character_name}.")
            return llm
        write_log(self.log_filename, "CharacterManager", f"Character {character_name} not found.")
        write_operation_log(self.operation_log_filename, "WARNING", "CharacterManager", f"Character {character_name} not found.")
        return None

    def get_persona_prompt(self, character_name: str) -> str:
        write_log(self.log_filename, "CharacterManager", f"Getting persona prompt for {character_name}.")
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", f"Getting persona prompt for {character_name}.")
        prompt = self.persona_manager.get_persona_prompt(character_name)
        write_log(self.log_filename, "CharacterManager", f"Persona prompt retrieved for {character_name}.")
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", f"Persona prompt retrieved for {character_name}.")
        return prompt

    def list_characters(self) -> List[Dict[str, Any]]:
        write_log(self.log_filename, "CharacterManager", "Listing all characters.")
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", "Listing all characters.")
        return self.character_configs

    def get_character_names(self) -> List[str]:
        write_log(self.log_filename, "CharacterManager", "Getting character names.")
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", "Getting character names.")
        names = [char.get("display_name", char["name"]) for char in self.character_configs]
        write_log(self.log_filename, "CharacterManager", "Character names retrieved.")
        write_operation_log(self.operation_log_filename, "INFO", "CharacterManager", "Character names retrieved.")
        return names
