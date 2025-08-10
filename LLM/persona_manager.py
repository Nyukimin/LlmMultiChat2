import yaml
from typing import Dict
from log_manager import write_operation_log

class PersonaManager:
    def __init__(self, log_filename: str, operation_log_filename: str, persona_path: str = "LLM/personas.yaml"):
        self.log_filename = log_filename
        self.operation_log_filename = operation_log_filename
        self.personas: Dict[str, str] = {}
        write_operation_log(self.operation_log_filename, "INFO", "PersonaManager", "Initializing PersonaManager.")
        try:
            with open(persona_path, 'r', encoding='utf-8') as file:
                personas_data = yaml.safe_load(file)
                if personas_data:
                    for char_key, persona_info in personas_data.items():
                        display_name = persona_info.get("name")
                        prompt = persona_info.get("system_prompt")
                        if display_name and prompt:
                            self.personas[display_name] = prompt
        except Exception as e:
            write_operation_log(self.operation_log_filename, "ERROR", "PersonaManager", f"Error loading personas: {e}")

    def get_persona_prompt(self, character_name: str) -> str:
        prompt = self.personas.get(character_name, "")
        if not prompt:
            write_operation_log(self.operation_log_filename, "WARNING", "PersonaManager", f"No persona prompt found for {character_name}.")
        return prompt
