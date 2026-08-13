import pytest
from services.ai_provider import (
    AIProvider,
    AIProviderError,
    MockAIProvider,
    OpenRouterAIProvider,
    OpenAIProvider,
    create_provider,
)


def test_mock_provider_works_without_api_key():
    provider = MockAIProvider(model="mock-model")
    result = provider.extract_invoice_fields(b"fake pdf bytes", "application/pdf")
    assert result["provider"] == "mock"
    assert result["model"] == "mock-model"
    assert result["mime_type"] == "application/pdf"
    assert result["size"] == len(b"fake pdf bytes")
    assert result["fields"]["invoice_number"] == "INV-001"
    assert result["fields"]["currency"] == "USD"


def test_mock_provider_is_deterministic():
    provider = MockAIProvider(model="mock-model")
    result1 = provider.extract_invoice_fields(b"some bytes", "image/png")
    result2 = provider.extract_invoice_fields(b"some bytes", "image/png")
    assert result1 == result2


def test_create_provider_selects_mock_by_default():
    provider = create_provider({"AI_MODE": "mock", "AI_MODEL": "mock-model"})
    assert isinstance(provider, MockAIProvider)


def test_create_provider_selects_openrouter():
    provider = create_provider({
        "AI_PROVIDER": "openrouter",
        "AI_MODEL": "openai/gpt-4o",
        "OPENROUTER_API_KEY": "sk-test",
    })
    assert isinstance(provider, OpenRouterAIProvider)
    assert provider.model == "openai/gpt-4o"


def test_create_provider_selects_openai():
    provider = create_provider({
        "AI_PROVIDER": "openai",
        "AI_MODEL": "gpt-4o",
        "OPENAI_API_KEY": "sk-test",
    })
    assert isinstance(provider, OpenAIProvider)
    assert provider.model == "gpt-4o"


def test_create_provider_unsupported_provider_fails():
    with pytest.raises(AIProviderError, match="Unsupported AI provider"):
        create_provider({"AI_PROVIDER": "anthropic", "AI_MODEL": "claude-3"})


def test_create_provider_missing_model_fails():
    with pytest.raises(AIProviderError, match="AI_MODEL is required"):
        create_provider({"AI_MODE": "mock"})


def test_openrouter_missing_api_key_fails():
    with pytest.raises(AIProviderError, match="OPENROUTER_API_KEY is required"):
        OpenRouterAIProvider(model="openai/gpt-4o", api_key="")


def test_openai_missing_api_key_fails():
    with pytest.raises(AIProviderError, match="OPENAI_API_KEY is required"):
        OpenAIProvider(model="gpt-4o", api_key="")


def test_openrouter_missing_model_fails():
    with pytest.raises(AIProviderError, match="AI_MODEL is required"):
        OpenRouterAIProvider(model="", api_key="sk-test")


def test_openai_missing_model_fails():
    with pytest.raises(AIProviderError, match="AI_MODEL is required"):
        OpenAIProvider(model="", api_key="sk-test")


def test_create_provider_missing_openrouter_key_fails():
    with pytest.raises(AIProviderError, match="OPENROUTER_API_KEY is required"):
        create_provider({"AI_PROVIDER": "openrouter", "AI_MODEL": "openai/gpt-4o"})


def test_create_provider_missing_openai_key_fails():
    with pytest.raises(AIProviderError, match="OPENAI_API_KEY is required"):
        create_provider({"AI_PROVIDER": "openai", "AI_MODEL": "gpt-4o"})


def test_live_provider_extract_raises_not_implemented():
    openrouter = OpenRouterAIProvider(model="openai/gpt-4o", api_key="sk-test")
    with pytest.raises(NotImplementedError, match="OpenRouter integration pending"):
        openrouter.extract_invoice_fields(b"data", "application/pdf")

    openai = OpenAIProvider(model="gpt-4o", api_key="sk-test")
    with pytest.raises(NotImplementedError, match="OpenAI integration pending"):
        openai.extract_invoice_fields(b"data", "application/pdf")
