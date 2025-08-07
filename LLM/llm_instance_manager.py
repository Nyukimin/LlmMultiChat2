import os
import yaml
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

# 内部モジュールのインポートはパスを明示的に指定
from llm_factory import LLMFactory

# ログ管理モジュールのインポート
from log_manager import write_log, write_operation_log, create_operation_log_filename

class LLMInstanceManager:
    def __init__(self, log_filename: str, character_configs: List[Dict] = None):
        self.log_filename = log_filename
        self.operation_log_filename = create_operation_log_filename()
        write_log(self.log_filename, "LLMInstanceManager", "Initializing LLMInstanceManager.")
        write_operation_log(self.operation_log_filename, "INFO", "LLMInstanceManager", "Initializing LLMInstanceManager.")
        self.llm_instances: Dict[str, any] = {}
        self.llm_factory = LLMFactory(self.log_filename)
        self.character_configs = character_configs or []
        write_log(self.log_filename, "LLMInstanceManager", "LLMInstanceManager initialized.")
        write_operation_log(self.operation_log_filename, "INFO", "LLMInstanceManager", "LLMInstanceManager initialized.")

    def get_llm(self, character_name: str, provider: str, model: str, base_url: Optional[str] = None):
        write_log(self.log_filename, "LLMInstanceManager", f"Getting LLM instance for {character_name}.")
        write_operation_log(self.operation_log_filename, "INFO", "LLMInstanceManager", f"Getting LLM instance for {character_name}.")
        if character_name not in self.llm_instances:
            write_log(self.log_filename, "LLMInstanceManager", f"Creating new LLM instance for {character_name}.")
            write_operation_log(self.operation_log_filename, "INFO", "LLMInstanceManager", f"Creating new LLM instance for {character_name}.")
            llm = self.llm_factory.create_llm(provider, model, base_url)
            if llm:
                self.llm_instances[character_name] = llm
                write_log(self.log_filename, "LLMInstanceManager", f"LLM instance created and stored for {character_name}.")
                write_operation_log(self.operation_log_filename, "INFO", "LLMInstanceManager", f"LLM instance created and stored for {character_name}.")
            else:
                write_log(self.log_filename, "LLMInstanceManager", f"Failed to create LLM instance for {character_name}.")
                write_operation_log(self.operation_log_filename, "ERROR", "LLMInstanceManager", f"Failed to create LLM instance for {character_name}.")
                return None
        else:
            write_log(self.log_filename, "LLMInstanceManager", f"Using existing LLM instance for {character_name}.")
            write_operation_log(self.operation_log_filename, "INFO", "LLMInstanceManager", f"Using existing LLM instance for {character_name}.")
        write_log(self.log_filename, "LLMInstanceManager", f"LLM instance retrieved for {character_name}.")
        write_operation_log(self.operation_log_filename, "INFO", "LLMInstanceManager", f"LLM instance retrieved for {character_name}.")
        return self.llm_instances[character_name]
