"""공식 LangChain 통합의 HTTP 경계를 가짜 인증과 전송으로 검증한다."""

from contextlib import contextmanager
from unittest.mock import patch
import httpx2
from langchain.chat_models import init_chat_model


@contextmanager
def transport(handler):
    def factory(model, **kwargs):
        client = kwargs.pop("http_client", None)
        hooks = client.event_hooks if client is not None else {}
        return init_chat_model(
            model,
            **kwargs,
            base_url="https://api.openai.com/v1",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler), event_hooks=hooks
            ),
        )

    with (
        patch.dict(
            "os.environ",
            {"LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"},
        ),
        patch("backend.providers.llm_provider.init_chat_model", side_effect=factory),
    ):
        yield
