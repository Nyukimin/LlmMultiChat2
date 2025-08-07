import os
import yaml
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

from llm_factory import LLMFactory
from llm_instance_manager import LLMInstanceManager
from persona_manager import PersonaManager

class CharacterManager:
    def __init__(self, config_path: str, persona_path: str):
        self.character_configs: List[Dict[str, Any]] = []
        with open(config_path, 'r', encoding='utf-8') as f: 
            config = yaml.safe_load(f)
        self.character_configs = config.get("characters", [])
        
        self.llm_instance_manager = LLMInstanceManager(self.character_configs)
        self.persona_manager = PersonaManager(persona_path)

    def get_llm(self, character_name: str):
        return self.llm_instance_manager.get_llm(character_name)

    def get_persona_prompt(self, character_name: str) -> Optional[str]:
        return self.persona_manager.get_persona_prompt(character_name)

    def list_characters(self) -> List[Dict[str, Any]]:
        return self.character_configs

    def get_character_names(self) -> List[str]:
        return [char["name"] for char in self.character_configs]
