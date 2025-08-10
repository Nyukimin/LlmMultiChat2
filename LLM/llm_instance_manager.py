from typing import Dict, Optional

from llm_factory import LLMFactory
from log_manager import write_operation_log

class LLMInstanceManager:
    def __init__(self, log_filename: str, operation_log_filename: str):
        self.log_filename = log_filename
        self.operation_log_filename = operation_log_filename
        self.llm_instances: Dict[str, any] = {}
        write_operation_log(self.operation_log_filename, "INFO", "LLMInstanceManager", "Initializing LLMInstanceManager.")

    def get_llm(self, character_name: str, provider: str, model: str, llm_factory: LLMFactory, base_url: Optional[str] = None):
        if character_name not in self.llm_instances:
            write_operation_log(self.operation_log_filename, "INFO", "LLMInstanceManager", f"Creating new LLM instance for {character_name}.")
            llm = llm_factory.create_llm(provider, model, base_url)
            if llm:
                self.llm_instances[character_name] = llm
            else:
                write_operation_log(self.operation_log_filename, "ERROR", "LLMInstanceManager", f"Failed to create LLM instance for {character_name}.")
                return None
        return self.llm_instances[character_name]
