"""Google Cloud Speech-to-Text (Chirp 2) client for streaming audio transcription."""

import asyncio
import json
from typing import AsyncGenerator

from google.cloud import speech_v2
from google.cloud.speech_v2.types import cloud_speech
from google.api_core.client_options import ClientOptions


class GoogleSpeechClient:
    """Client for Google Cloud Speech-to-Text API v2 with Chirp 2 model."""

    def __init__(
        self,
        project_id: str,
        location: str = "global",
        recognizer_id: str = "chirp-2-recognizer",
        credentials_path: str | None = None,
    ):
        """
        Initialize Google Speech client.

        Args:
            project_id: Google Cloud project ID
            location: API location (default: "global")
            recognizer_id: Recognizer resource ID (default: "chirp-2-recognizer")
            credentials_path: Path to service account JSON key file (optional)
        """
        self.project_id = project_id
        self.location = location
        self.recognizer_id = recognizer_id
        self.credentials_path = credentials_path

        # Initialize client
        client_options = None
        if location != "global":
            client_options = ClientOptions(
                api_endpoint=f"{location}-speech.googleapis.com"
            )

        # Set credentials if provided
        if credentials_path:
            import os
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

        self.client = speech_v2.SpeechClient(client_options=client_options)

        # Recognizer name format: projects/{project}/locations/{location}/recognizers/{recognizer}
        self.recognizer_name = (
            f"projects/{project_id}/locations/{location}/recognizers/{recognizer_id}"
        )

    def create_streaming_config(
        self,
        encoding: str = "OPUS",
        sample_rate_hertz: int = 48000,
        language_codes: list[str] = ["zh-CN", "en-US"],
    ) -> cloud_speech.StreamingRecognitionConfig:
        """
        Create streaming recognition configuration.

        Args:
            encoding: Audio encoding (default: "OPUS")
            sample_rate_hertz: Sample rate in Hz (default: 48000)
            language_codes: List of language codes (default: ["zh-CN", "en-US"])

        Returns:
            StreamingRecognitionConfig object
        """
        # Map encoding string to enum
        encoding_map = {
            "LINEAR16": cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            "OPUS": cloud_speech.ExplicitDecodingConfig.AudioEncoding.OPUS,
            "MULAW": cloud_speech.ExplicitDecodingConfig.AudioEncoding.MULAW,
            "ALAW": cloud_speech.ExplicitDecodingConfig.AudioEncoding.ALAW,
        }

        audio_encoding = encoding_map.get(
            encoding.upper(),
            cloud_speech.ExplicitDecodingConfig.AudioEncoding.OPUS,
        )

        # Configure explicit decoding
        explicit_decoding_config = cloud_speech.ExplicitDecodingConfig(
            encoding=audio_encoding,
            sample_rate_hertz=sample_rate_hertz,
        )

        # Configure recognition features
        recognition_features = cloud_speech.RecognitionFeatures(
            enable_automatic_punctuation=True,
            enable_word_time_offsets=True,
        )

        # Create streaming config
        streaming_config = cloud_speech.StreamingRecognitionConfig(
            config=cloud_speech.RecognitionConfig(
                explicit_decoding_config=explicit_decoding_config,
                language_codes=language_codes,
                model="chirp_2",
                features=recognition_features,
            ),
            streaming_features=cloud_speech.StreamingRecognitionFeatures(
                interim_results=True,
            ),
        )

        return streaming_config

    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        encoding: str = "OPUS",
        sample_rate_hertz: int = 48000,
        language_codes: list[str] = ["zh-CN", "en-US"],
    ) -> AsyncGenerator[dict, None]:
        """
        Transcribe audio stream using Chirp 2 model.

        Args:
            audio_stream: Async generator yielding audio chunks
            encoding: Audio encoding (default: "OPUS")
            sample_rate_hertz: Sample rate in Hz (default: 48000)
            language_codes: List of language codes (default: ["zh-CN", "en-US"])

        Yields:
            Dict containing transcription results
        """
        # Create streaming config
        streaming_config = self.create_streaming_config(
            encoding=encoding,
            sample_rate_hertz=sample_rate_hertz,
            language_codes=language_codes,
        )

        # Generator to produce streaming recognize requests
        async def request_generator():
            # First request with config
            yield cloud_speech.StreamingRecognizeRequest(
                recognizer=self.recognizer_name,
                streaming_config=streaming_config,
            )

            # Subsequent requests with audio content
            async for audio_chunk in audio_stream:
                yield cloud_speech.StreamingRecognizeRequest(audio=audio_chunk)

        # Make streaming recognize call
        responses = self.client.streaming_recognize(requests=request_generator())

        # Process responses
        for response in responses:
            for result in response.results:
                if not result.alternatives:
                    continue

                alternative = result.alternatives[0]

                # Format result
                result_dict = {
                    "transcript": alternative.transcript,
                    "confidence": alternative.confidence,
                    "is_final": result.is_final,
                    "stability": result.stability,
                    "language_code": result.language_code,
                }

                # Add word-level timestamps if available
                if alternative.words:
                    result_dict["words"] = [
                        {
                            "word": word.word,
                            "start_offset": word.start_offset.total_seconds(),
                            "end_offset": word.end_offset.total_seconds(),
                        }
                        for word in alternative.words
                    ]

                yield result_dict

    async def transcribe_stream_json(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        encoding: str = "OPUS",
        sample_rate_hertz: int = 48000,
        language_codes: list[str] = ["zh-CN", "en-US"],
    ) -> AsyncGenerator[str, None]:
        """
        Transcribe audio stream and yield JSON-formatted SSE events.

        Args:
            audio_stream: Async generator yielding audio chunks
            encoding: Audio encoding (default: "OPUS")
            sample_rate_hertz: Sample rate in Hz (default: 48000)
            language_codes: List of language codes (default: ["zh-CN", "en-US"])

        Yields:
            SSE-formatted JSON strings
        """
        try:
            async for result in self.transcribe_stream(
                audio_stream=audio_stream,
                encoding=encoding,
                sample_rate_hertz=sample_rate_hertz,
                language_codes=language_codes,
            ):
                # Format as SSE event
                event_data = json.dumps(result, ensure_ascii=False)
                yield f"data: {event_data}\n\n"

            # Send completion event
            yield "data: [DONE]\n\n"

        except Exception as e:
            # Send error event
            error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"
