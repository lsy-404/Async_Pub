"""OpenAI API compatible schemas for request and response models."""

from typing import Any, Literal
from pydantic import BaseModel, Field


# === Chat Completions ===
class Message(BaseModel):
    """Single message in chat."""

    role: Literal["system", "user", "assistant", "function"]
    content: str | None = None
    name: str | None = None
    function_call: dict[str, Any] | None = None


class ChatCompletionRequest(BaseModel):
    """OpenAI Chat Completions API request."""

    model: str = Field(..., description="Model ID to use")
    messages: list[Message] = Field(..., description="Messages in the conversation")
    temperature: float | None = Field(default=1.0, ge=0, le=2)
    top_p: float | None = Field(default=1.0, ge=0, le=1)
    n: int | None = Field(default=1, ge=1, le=10, description="Number of completions")
    stream: bool | None = Field(default=False, description="Stream responses")
    stop: str | list[str] | None = None
    max_tokens: int | None = None
    presence_penalty: float | None = Field(default=0, ge=-2, le=2)
    frequency_penalty: float | None = Field(default=0, ge=-2, le=2)
    logit_bias: dict[str, float] | None = None
    user: str | None = Field(None, description="Unique user identifier")
    
class ChatCompletionChoice(BaseModel):
    """Single completion choice."""

    index: int
    message: Message
    finish_reason: str | None = "stop"


class ChatCompletionUsage(BaseModel):
    """Token usage statistics."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    """OpenAI Chat Completions API response."""

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage | None = None


class ChatCompletionStreamChoice(BaseModel):
    """Streaming completion choice delta."""

    index: int
    delta: dict[str, Any]
    finish_reason: str | None = None


class ChatCompletionStreamResponse(BaseModel):
    """Streaming chunk response."""

    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionStreamChoice]


# === Text Completions (Legacy) ===
class CompletionRequest(BaseModel):
    """OpenAI Completions API request (legacy text completion)."""

    model: str = Field(..., description="Model ID to use")
    prompt: str | list[str] = Field(..., description="Text prompt to complete")
    temperature: float | None = Field(default=1.0, ge=0, le=2)
    top_p: float | None = Field(default=1.0, ge=0, le=1)
    n: int | None = Field(default=1, ge=1, le=10, description="Number of completions")
    stream: bool | None = Field(default=False, description="Stream responses")
    stop: str | list[str] | None = None
    max_tokens: int | None = None
    presence_penalty: float | None = Field(default=0, ge=-2, le=2)
    frequency_penalty: float | None = Field(default=0, ge=-2, le=2)
    logit_bias: dict[str, float] | None = None
    user: str | None = Field(None, description="Unique user identifier")
    suffix: str | None = Field(None, description="Text to append after completion")
    best_of: int | None = Field(None, ge=1, le=20)
    echo: bool | None = Field(default=False)


class CompletionChoice(BaseModel):
    """Single completion choice."""

    text: str
    index: int
    finish_reason: str | None = "stop"
    logprobs: dict[str, Any] | None = None


class CompletionResponse(BaseModel):
    """OpenAI Completions API response."""

    id: str
    object: str = "text_completion"
    created: int
    model: str
    choices: list[CompletionChoice]
    usage: ChatCompletionUsage | None = None


# === Embeddings ===
class EmbeddingsRequest(BaseModel):
    """OpenAI Embeddings API request."""

    model: str = Field(..., description="Model ID to use")
    input: str | list[str] = Field(..., description="Text to embed")
    user: str | None = Field(None, description="Unique user identifier")


class EmbeddingData(BaseModel):
    """Single embedding result."""

    object: str = "embedding"
    embedding: list[float]
    index: int


class EmbeddingsUsage(BaseModel):
    """Token usage for embeddings."""

    prompt_tokens: int
    total_tokens: int


class EmbeddingsResponse(BaseModel):
    """OpenAI Embeddings API response."""

    object: str = "list"
    data: list[EmbeddingData]
    model: str
    usage: EmbeddingsUsage


# === Models ===
class ModelData(BaseModel):
    """Model information."""

    id: str
    object: str = "model"
    created: int
    owned_by: str = "system"


class ModelsResponse(BaseModel):
    """Models list response."""

    object: str = "list"
    data: list[ModelData]
