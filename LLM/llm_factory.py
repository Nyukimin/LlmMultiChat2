from typing import Optional, Any
from langchain_community.chat_models import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic

PROVIDER_REGISTRY = {
    "ollama": {"class": ChatOllama, "requires_api_key": False},
    "openai": {"class": ChatOpenAI, "requires_api_key": True},
    "gemini": {"class": ChatGoogleGenerativeAI, "requires_api_key": True},
    "anthropic": {"class": ChatAnthropic, "requires_api_key": True},
    "openrouter": {
        "class": ChatOpenAI,
        "requires_api_key": True,
        "extra_params": {"base_url": "https://openrouter.ai/api/v1"}
    }
}

class LLMFactory:
    @staticmethod
    def create_llm(provider: str, model: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        if provider not in PROVIDER_REGISTRY:
            raise ValueError(f"サポートされていないプロバイダーです: {provider}")
        registry_info = PROVIDER_REGISTRY[provider]
        llm_class = registry_info["class"]
        kwargs = {"model": model}
        if registry_info["requires_api_key"]:
            if not api_key:
                raise ValueError(f"プロバイダー「{provider}」にはAPIキーが必要です。")
            kwargs["google_api_key" if provider == "gemini" else "api_key"] = api_key
        if provider == "ollama" and base_url:
            kwargs["base_url"] = base_url
        if "extra_params" in registry_info:
            kwargs.update(registry_info["extra_params"])
        return llm_class(**kwargs)
