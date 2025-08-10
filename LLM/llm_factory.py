import asyncio
from typing import Optional, Any, Dict

import httpx
from openai import AsyncOpenAI

from log_manager import write_operation_log


class AsyncOllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.2,
        top_p: float = 0.9,
        repeat_penalty: float = 1.1,
        num_predict: int = 160,
        operation_log_filename: Optional[str] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.repeat_penalty = repeat_penalty
        self.num_predict = num_predict
        self.operation_log_filename = operation_log_filename

    async def ainvoke(self, system_prompt: str, user_message: str) -> str:
        prompt = f"{system_prompt}\n\n{user_message}".strip()
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "top_p": self.top_p,
                "repeat_penalty": self.repeat_penalty,
                "num_predict": self.num_predict,
            },
        }
        url = f"{self.base_url}/api/generate"
        async with httpx.AsyncClient(timeout=httpx.Timeout(70.0)) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return str(data.get("response", "")).strip()
            except Exception as e:
                if self.operation_log_filename:
                    write_operation_log(self.operation_log_filename, "ERROR", "OllamaClient", f"Invocation failed: {e}")
                raise


class AsyncOpenAIChatClient:
    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        temperature: float = 0.0,
        operation_log_filename: Optional[str] = None,
    ) -> None:
        self.client = AsyncOpenAI(base_url=base_url) if base_url else AsyncOpenAI()
        self.model = model
        self.temperature = temperature
        self.operation_log_filename = operation_log_filename

    async def ainvoke(self, system_prompt: str, user_message: str) -> str:
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": system_prompt or ""},
                    {"role": "user", "content": user_message or ""},
                ],
            )
            content = (resp.choices[0].message.content or "").strip()
            return content
        except Exception as e:
            if self.operation_log_filename:
                write_operation_log(self.operation_log_filename, "ERROR", "OpenAIClient", f"Invocation failed: {e}")
            raise


class LLMFactory:
    def __init__(self, log_filename: str, operation_log_filename: str):
        self.log_filename = log_filename
        self.operation_log_filename = operation_log_filename
        write_operation_log(self.operation_log_filename, "INFO", "LLMFactory", "Initializing LLMFactory.")

    def create_llm(self, provider: str, model: str, base_url: Optional[str] = None):
        write_operation_log(self.operation_log_filename, "INFO", "LLMFactory", f"Creating LLM with provider: {provider}, model: {model}")
        try:
            provider_l = (provider or "").lower()
            if provider_l == "ollama":
                return AsyncOllamaClient(
                    base_url=base_url or "http://localhost:11434",
                    model=model,
                    temperature=0.2,
                    top_p=0.9,
                    repeat_penalty=1.1,
                    num_predict=160,
                    operation_log_filename=self.operation_log_filename,
                )
            elif provider_l == "openai":
                return AsyncOpenAIChatClient(
                    model=model,
                    base_url=base_url,
                    temperature=0.0,
                    operation_log_filename=self.operation_log_filename,
                )
            else:
                write_operation_log(self.operation_log_filename, "WARNING", "LLMFactory", f"Unsupported provider: {provider}")
                return None
        except Exception as e:
            write_operation_log(self.operation_log_filename, "ERROR", "LLMFactory", f"Error creating LLM: {e}")
            return None
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
