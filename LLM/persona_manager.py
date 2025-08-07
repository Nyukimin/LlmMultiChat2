import yaml
from typing import Dict
from log_manager import write_log, write_operation_log, create_operation_log_filename

class PersonaManager:
    def __init__(self, log_filename: str, persona_path: str = "LLM/personas.yaml"):
        self.log_filename = log_filename
        self.operation_log_filename = create_operation_log_filename()
        write_log(self.log_filename, "PersonaManager", "Initializing PersonaManager.")
        write_operation_log(self.operation_log_filename, "INFO", "PersonaManager", "Initializing PersonaManager.")
        self.personas: Dict[str, str] = {}
        try:
            with open(persona_path, 'r', encoding='utf-8') as file:
                personas_data = yaml.safe_load(file)
                if personas_data:
                    for char_key, persona_info in personas_data.items():
                        # config.yamlのdisplay_nameをキーとしてpromptを保存
                        display_name = persona_info.get("name")
                        prompt = persona_info.get("system_prompt")
                        if display_name and prompt:
                            self.personas[display_name] = prompt
            write_log(self.log_filename, "PersonaManager", "Personas loaded successfully.")
            write_operation_log(self.operation_log_filename, "INFO", "PersonaManager", "Personas loaded successfully.")
        except Exception as e:
            write_log(self.log_filename, "PersonaManager", f"Error loading personas: {e}")
            write_operation_log(self.operation_log_filename, "ERROR", "PersonaManager", f"Error loading personas: {e}")
        write_log(self.log_filename, "PersonaManager", "PersonaManager initialized.")
        write_operation_log(self.operation_log_filename, "INFO", "PersonaManager", "PersonaManager initialized.")

    def get_persona_prompt(self, character_name: str) -> str:
        write_log(self.log_filename, "PersonaManager", f"Getting persona prompt for {character_name}.")
        write_operation_log(self.operation_log_filename, "INFO", "PersonaManager", f"Getting persona prompt for {character_name}.")
        # character_nameは表示名（ルミナなど）で渡される
        prompt = self.personas.get(character_name, "")
        if prompt:
            write_log(self.log_filename, "PersonaManager", f"Persona prompt found for {character_name}.")
            write_operation_log(self.operation_log_filename, "INFO", "PersonaManager", f"Persona prompt found for {character_name}.")
        else:
            write_log(self.log_filename, "PersonaManager", f"No persona prompt found for {character_name}.")
            write_operation_log(self.operation_log_filename, "WARNING", "PersonaManager", f"No persona prompt found for {character_name}.")
        return prompt
