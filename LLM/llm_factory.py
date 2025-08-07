from typing import Optional

from langchain_community.llms import Ollama
from langchain_openai import ChatOpenAI

from log_manager import write_log, write_operation_log, create_operation_log_filename

class LLMFactory:
    def __init__(self, log_filename: str):
        self.log_filename = log_filename
        self.operation_log_filename = create_operation_log_filename()
        write_log(self.log_filename, "LLMFactory", "Initializing LLMFactory.")
        write_operation_log(self.operation_log_filename, "INFO", "LLMFactory", "Initializing LLMFactory.")
        write_log(self.log_filename, "LLMFactory", "LLMFactory initialized.")
        write_operation_log(self.operation_log_filename, "INFO", "LLMFactory", "LLMFactory initialized.")

    def create_llm(self, provider: str, model: str, base_url: Optional[str] = None):
        write_log(self.log_filename, "LLMFactory", f"Creating LLM with provider: {provider}, model: {model}")
        write_operation_log(self.operation_log_filename, "INFO", "LLMFactory", f"Creating LLM with provider: {provider}, model: {model}")
        try:
            if provider.lower() == "ollama":
                write_log(self.log_filename, "LLMFactory", f"Creating Ollama LLM with model: {model}, base_url: {base_url}")
                write_operation_log(self.operation_log_filename, "INFO", "LLMFactory", f"Creating Ollama LLM with model: {model}, base_url: {base_url}")
                llm = Ollama(model=model, base_url=base_url)
                write_log(self.log_filename, "LLMFactory", f"Ollama LLM created with model: {model}")
                write_operation_log(self.operation_log_filename, "INFO", "LLMFactory", f"Ollama LLM created with model: {model}")
                return llm
            elif provider.lower() == "openai":
                write_log(self.log_filename, "LLMFactory", f"Creating OpenAI LLM with model: {model}")
                write_operation_log(self.operation_log_filename, "INFO", "LLMFactory", f"Creating OpenAI LLM with model: {model}")
                llm = ChatOpenAI(model=model)
                write_log(self.log_filename, "LLMFactory", f"OpenAI LLM created with model: {model}")
                write_operation_log(self.operation_log_filename, "INFO", "LLMFactory", f"OpenAI LLM created with model: {model}")
                return llm
            else:
                write_log(self.log_filename, "LLMFactory", f"Unsupported provider: {provider}")
                write_operation_log(self.operation_log_filename, "WARNING", "LLMFactory", f"Unsupported provider: {provider}")
                return None
        except Exception as e:
            write_log(self.log_filename, "LLMFactory", f"Error creating LLM: {e}")
            write_operation_log(self.operation_log_filename, "ERROR", "LLMFactory", f"Error creating LLM: {e}")
            return None
