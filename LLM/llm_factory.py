from typing import Optional

try:  # 新推奨: 専用パッケージ
    from langchain_ollama import ChatOllama  # type: ignore
except Exception:
    try:  # 後方互換: 旧 community 実装
        from langchain_community.chat_models import ChatOllama  # type: ignore
    except Exception:
        ChatOllama = None  # type: ignore
try:
    from langchain_openai import ChatOpenAI  # type: ignore
except Exception:
    ChatOpenAI = None  # type: ignore

from log_manager import write_operation_log

class LLMFactory:
    def __init__(self, log_filename: str, operation_log_filename: str):
        self.log_filename = log_filename
        self.operation_log_filename = operation_log_filename
        write_operation_log(self.operation_log_filename, "INFO", "LLMFactory", "Initializing LLMFactory.")

    def create_llm(self, provider: str, model: str, base_url: Optional[str] = None):
        write_operation_log(self.operation_log_filename, "INFO", "LLMFactory", f"Creating LLM with provider: {provider}, model: {model}")
        try:
            if provider.lower() == "ollama":
                # 出力を安定化（ハルシネーション抑制、冗長抑制）
                if ChatOllama is None:
                    write_operation_log(self.operation_log_filename, "ERROR", "LLMFactory", "ChatOllama is unavailable. Ensure 'langchain-ollama' or 'langchain-community' is installed.")
                    return None
                llm = ChatOllama(
                    model=model,
                    base_url=base_url,
                    temperature=0.2,
                    top_p=0.9,
                    repeat_penalty=1.1,
                    num_predict=160,
                )
                return llm
            elif provider.lower() == "openai":
                if ChatOpenAI is None:
                    write_operation_log(self.operation_log_filename, "ERROR", "LLMFactory", "ChatOpenAI is unavailable. Ensure 'langchain-openai' is installed.")
                    return None
                llm = ChatOpenAI(model=model, temperature=0)
                return llm
            else:
                write_operation_log(self.operation_log_filename, "WARNING", "LLMFactory", f"Unsupported provider: {provider}")
                return None
        except Exception as e:
            write_operation_log(self.operation_log_filename, "ERROR", "LLMFactory", f"Error creating LLM: {e}")
            return None
