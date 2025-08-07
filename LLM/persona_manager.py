import yaml
from typing import Dict, Any, Optional

class PersonaManager:
    def __init__(self, persona_path: str):
        self.personas: Dict[str, Any] = {}
        with open(persona_path, 'r', encoding='utf-8') as f:
            self.personas = yaml.safe_load(f)

    def get_persona_prompt(self, character_name: str) -> Optional[str]:
        persona_key = character_name.upper()
        persona_data = self.personas.get(persona_key)
        return persona_data.get("system_prompt") if persona_data else None
