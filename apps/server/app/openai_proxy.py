"""OpenAI API proxy logic for forwarding requests to configured endpoints."""

import json
import time
from typing import AsyncIterator

import httpx
from fastapi import HTTPException, status

from .config import Config
from .openai_schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    CompletionRequest,
    CompletionResponse,
    EmbeddingsRequest,
    EmbeddingsResponse,
    ModelsResponse,
    ModelData,
)


class OpenAIProxy:
    """Proxy for OpenAI-compatible API requests."""

    def __init__(self, config: Config):
        self.config = config
        self.client = httpx.AsyncClient(timeout=60.0)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    def _get_model_config(self, model_name: str):
        """Get configuration for a specific model."""
        # Map model names to configurations
        if "gpt-4" in model_name.lower():
            return self.config.multimodal_model
        else:
            return self.config.text_model

    async def chat_completion(
        self, request: ChatCompletionRequest, auth_header: str | None = None
    ) -> ChatCompletionResponse | AsyncIterator[str]:
        """
        Forward chat completion request to configured endpoint.
        Supports both streaming and non-streaming responses.
        """
        model_config = self._get_model_config(request.model)

        if not model_config.is_valid():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Model {request.model} is not configured",
            )

        # Prepare request headers
        headers = {
            "Authorization": f"Bearer {model_config.api_token}",
            "Content-Type": "application/json",
        }

        # Forward to configured endpoint
        endpoint_url = f"{model_config.endpoint}/chat/completions"

        # Prepare request body
        body = request.model_dump(exclude_none=True)

        if request.stream:
            # Return async generator for streaming
            return self._stream_completion(endpoint_url, headers, body, request.model)
        else:
            # Non-streaming request
            try:
                response = await self.client.post(
                    endpoint_url,
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
                return ChatCompletionResponse(**response.json())
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"Upstream API error: {e.response.text}",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Proxy error: {str(e)}",
                )

    async def _stream_completion(
        self, url: str, headers: dict, body: dict, model: str
    ) -> AsyncIterator[str]:
        """Stream chat completion responses as Server-Sent Events."""
        try:
            async with self.client.stream(
                "POST",
                url,
                headers=headers,
                json=body,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        # Forward SSE data
                        yield f"{line}\n\n"
                    elif line.strip() == "":
                        yield "\n"
                    elif line.strip():
                        # Forward other lines as-is
                        yield f"{line}\n"

        except httpx.HTTPStatusError as e:
            error_data = {
                "error": {
                    "message": f"Upstream API error: {e.response.status_code}",
                    "type": "upstream_error",
                    "code": e.response.status_code,
                }
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            error_data = {
                "error": {
                    "message": f"Proxy error: {str(e)}",
                    "type": "proxy_error",
                }
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            yield "data: [DONE]\n\n"

    async def completion(
        self, request: CompletionRequest, auth_header: str | None = None
    ) -> CompletionResponse | AsyncIterator[str]:
        """
        Forward text completion request to configured endpoint.
        Supports both streaming and non-streaming responses.
        """
        model_config = self._get_model_config(request.model)

        if not model_config.is_valid():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Model {request.model} is not configured",
            )

        # Prepare request headers
        headers = {
            "Authorization": f"Bearer {model_config.api_token}",
            "Content-Type": "application/json",
        }

        # Forward to configured endpoint
        endpoint_url = f"{model_config.endpoint}/completions"

        # Prepare request body
        body = request.model_dump(exclude_none=True)

        if request.stream:
            # Return async generator for streaming
            return self._stream_text_completion(endpoint_url, headers, body, request.model)
        else:
            # Non-streaming request
            try:
                response = await self.client.post(
                    endpoint_url,
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
                return CompletionResponse(**response.json())
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"Upstream API error: {e.response.text}",
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Proxy error: {str(e)}",
                )

    async def _stream_text_completion(
        self, url: str, headers: dict, body: dict, model: str
    ) -> AsyncIterator[str]:
        """Stream text completion responses as Server-Sent Events."""
        try:
            async with self.client.stream(
                "POST",
                url,
                headers=headers,
                json=body,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        # Forward SSE data
                        yield f"{line}\n\n"
                    elif line.strip() == "":
                        yield "\n"
                    elif line.strip():
                        # Forward other lines as-is
                        yield f"{line}\n"

        except httpx.HTTPStatusError as e:
            error_data = {
                "error": {
                    "message": f"Upstream API error: {e.response.status_code}",
                    "type": "upstream_error",
                    "code": e.response.status_code,
                }
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            error_data = {
                "error": {
                    "message": f"Proxy error: {str(e)}",
                    "type": "proxy_error",
                }
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            yield "data: [DONE]\n\n"

    async def embeddings(
        self, request: EmbeddingsRequest, auth_header: str | None = None
    ) -> EmbeddingsResponse:
        """Forward embeddings request to configured endpoint."""
        # Use text model for embeddings (or create separate embedding config if needed)
        model_config = self.config.text_model

        if not model_config.is_valid():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Model {request.model} is not configured",
            )

        headers = {
            "Authorization": f"Bearer {model_config.api_token}",
            "Content-Type": "application/json",
        }

        endpoint_url = f"{model_config.endpoint}/embeddings"

        body = request.model_dump(exclude_none=True)

        try:
            response = await self.client.post(
                endpoint_url,
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            return EmbeddingsResponse(**response.json())
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Upstream API error: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Proxy error: {str(e)}",
            )

    async def list_models(self) -> ModelsResponse:
        """Return list of available models from configuration."""
        models_data = []
        created_timestamp = int(time.time())

        # Add configured models
        if self.config.text_model.is_valid():
            models_data.append(
                ModelData(
                    id=self.config.text_model.name,
                    created=created_timestamp,
                    owned_by="system",
                )
            )

        if self.config.multimodal_model.is_valid():
            models_data.append(
                ModelData(
                    id=self.config.multimodal_model.name,
                    created=created_timestamp,
                    owned_by="system",
                )
            )

        return ModelsResponse(object="list", data=models_data)
