import pytest
from unittest.mock import patch
import requests
from services.ai_provider import (
    AIProvider,
    AIProviderError,
    MockAIProvider,
    OpenRouterAIProvider,
    OpenAIProvider,
    AgentRouterAIProvider,
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


def test_create_provider_selects_agentrouter():
    provider = create_provider({
        "AI_PROVIDER": "agentrouter",
        "AI_MODEL": "gpt-4o",
        "AGENTROUTER_API_KEY": "sk-test",
    })
    assert isinstance(provider, AgentRouterAIProvider)
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


def test_agentrouter_missing_api_key_fails():
    with pytest.raises(AIProviderError, match="AGENTROUTER_API_KEY is required"):
        AgentRouterAIProvider(model="gpt-4o", api_key="")


def test_agentrouter_missing_model_fails():
    with pytest.raises(AIProviderError, match="AI_MODEL is required"):
        AgentRouterAIProvider(model="", api_key="sk-test")


def test_create_provider_missing_agentrouter_key_fails():
    with pytest.raises(AIProviderError, match="AGENTROUTER_API_KEY is required"):
        create_provider({"AI_PROVIDER": "agentrouter", "AI_MODEL": "gpt-4o"})


def test_live_provider_extract_raises_not_implemented():
    openrouter = OpenRouterAIProvider(model="openai/gpt-4o", api_key="sk-test")
    with pytest.raises(NotImplementedError, match="OpenRouter integration pending"):
        openrouter.extract_invoice_fields(b"data", "application/pdf")

    openai = OpenAIProvider(model="gpt-4o", api_key="sk-test")
    with pytest.raises(NotImplementedError, match="OpenAI integration pending"):
        openai.extract_invoice_fields(b"data", "application/pdf")


def test_agentrouter_text_extraction_success():
    provider = AgentRouterAIProvider(model="gpt-4o", api_key="sk-test")
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": '{"invoice_number": "INV-123", "amount": "150.00", "currency": "USD", "confidence": 0.9}'
                }
            }
        ]
    }
    with patch("services.ai_provider.requests.post") as mock_post:
        mock_post.return_value.json.return_value = mock_response
        mock_post.return_value.raise_for_status.return_value = None
        result = provider.extract_invoice_fields(b"data", "application/pdf", processing_mode="text", extracted_text="Invoice text")
    assert result["provider"] == "agentrouter"
    assert result["fields"]["invoice_number"] == "INV-123"
    assert result["fields"]["amount"] == "150.00"
    assert result["fields"]["currency"] == "USD"
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args.kwargs
    assert "Authorization" in call_kwargs["headers"]
    assert call_kwargs["headers"]["Authorization"] == "Bearer sk-test"


def test_agentrouter_network_failure():
    provider = AgentRouterAIProvider(model="gpt-4o", api_key="sk-test")
    with patch("services.ai_provider.requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection error")
        with pytest.raises(AIProviderError, match="AgentRouter API request failed"):
            provider.extract_invoice_fields(b"data", "application/pdf", processing_mode="text", extracted_text="text")


def test_agentrouter_malformed_response():
    provider = AgentRouterAIProvider(model="gpt-4o", api_key="sk-test")
    with patch("services.ai_provider.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {"choices": []}
        mock_post.return_value.raise_for_status.return_value = None
        with pytest.raises(AIProviderError, match="Invalid AgentRouter response structure"):
            provider.extract_invoice_fields(b"data", "application/pdf", processing_mode="text", extracted_text="text")


def test_agentrouter_no_api_key_leakage():
    provider = AgentRouterAIProvider(model="gpt-4o", api_key="super-secret-key")
    with patch("services.ai_provider.requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection error")
        try:
            provider.extract_invoice_fields(b"data", "application/pdf", processing_mode="text", extracted_text="text")
        except AIProviderError as exc:
            assert "super-secret-key" not in str(exc)


def test_agentrouter_vision_unsupported_model_raises():
    provider = AgentRouterAIProvider(model="gpt-3.5-turbo", api_key="sk-test")
    with pytest.raises(AIProviderError, match="does not support vision extraction"):
        provider.extract_invoice_fields(b"image data", "image/png", processing_mode="vision")


def test_agentrouter_vision_supported_model():
    provider = AgentRouterAIProvider(model="gpt-4o", api_key="sk-test")
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": '{"invoice_number": "INV-456", "amount": "200.00", "currency": "EUR", "confidence": 0.85}'
                }
            }
        ]
    }
    with patch("services.ai_provider.requests.post") as mock_post:
        mock_post.return_value.json.return_value = mock_response
        mock_post.return_value.raise_for_status.return_value = None
        result = provider.extract_invoice_fields(b"image data", "image/png", processing_mode="vision")
    assert result["provider"] == "agentrouter"
    assert result["fields"]["invoice_number"] == "INV-456"
