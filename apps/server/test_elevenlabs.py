"""Test script for ElevenLabs audio transcription provider."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.audio_transcription import TranscriptionConfig, AudioEncoding
from app.elevenlabs_provider import ElevenLabsProvider


async def test_file_transcription():
    """Test file transcription with ElevenLabs."""
    print("=== Testing ElevenLabs File Transcription ===\n")
    
    # Configure provider (you need to add your API key here)
    config = {
        "api_key": "your-elevenlabs-api-key-here",
        "model_id": "scribe_v2_realtime",
        "include_timestamps": True,
    }
    
    try:
        provider = ElevenLabsProvider(config)
        print(f"✅ Provider initialized: {provider.get_provider_name()}")
    except ImportError as e:
        print(f"❌ Error: {e}")
        print("   Install with: pip install elevenlabs")
        return
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return
    
    # Create transcription config
    transcription_config = TranscriptionConfig(
        encoding=AudioEncoding.MP3,
        language="en-US",
        enable_timestamps=True,
        enable_word_timestamps=True,
    )
    
    # Test with a sample audio file (you need to provide this)
    audio_file = Path("test_audio.mp3")
    
    if not audio_file.exists():
        print(f"⚠️  Test audio file not found: {audio_file}")
        print("   Please provide a test audio file named 'test_audio.mp3'")
        return
    
    print(f"📁 Transcribing file: {audio_file}")
    
    try:
        result = await provider.transcribe_file(audio_file, transcription_config)
        
        print("\n✅ Transcription completed!")
        print(f"\n📝 Text: {result.text}")
        print(f"🏷️  Provider: {result.provider}")
        print(f"🤖 Model: {result.model}")
        
        if result.words:
            print(f"\n🔤 Word count: {len(result.words)}")
            print("\n📊 First 5 words with timestamps:")
            for word in result.words[:5]:
                print(f"   '{word.word}': {word.start:.2f}s - {word.end:.2f}s")
        
        if result.segments:
            print(f"\n📋 Segments: {len(result.segments)}")
    
    except Exception as e:
        print(f"\n❌ Transcription error: {e}")
        import traceback
        traceback.print_exc()


async def test_stream_transcription():
    """Test stream transcription with ElevenLabs."""
    print("\n=== Testing ElevenLabs Stream Transcription ===\n")
    
    # Configure provider
    config = {
        "api_key": "your-elevenlabs-api-key-here",
        "model_id": "scribe_v2_realtime",
        "include_timestamps": True,
    }
    
    try:
        provider = ElevenLabsProvider(config)
        print(f"✅ Provider initialized: {provider.get_provider_name()}")
    except ImportError as e:
        print(f"❌ Error: {e}")
        return
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return
    
    # Create transcription config
    transcription_config = TranscriptionConfig(
        encoding=AudioEncoding.MP3,
        language="en-US",
        enable_timestamps=False,
        enable_word_timestamps=False,
    )
    
    # Test with a sample audio file streamed in chunks
    audio_file = Path("test_audio.mp3")
    
    if not audio_file.exists():
        print(f"⚠️  Test audio file not found: {audio_file}")
        return
    
    print(f"📁 Streaming file: {audio_file}")
    
    # Create audio stream
    async def audio_stream():
        with open(audio_file, "rb") as f:
            while chunk := f.read(8192):  # 8KB chunks
                yield chunk
                await asyncio.sleep(0.01)  # Simulate real-time streaming
    
    try:
        print("\n🎤 Starting stream transcription...")
        print("=" * 60)
        
        chunk_count = 0
        async for chunk in provider.transcribe_stream(
            audio_stream(),
            transcription_config
        ):
            chunk_count += 1
            final_marker = "✅" if chunk.is_final else "⏳"
            print(f"{final_marker} [{chunk_count:3d}] {chunk.text}")
        
        print("=" * 60)
        print(f"\n✅ Stream transcription completed! Total chunks: {chunk_count}")
    
    except Exception as e:
        print(f"\n❌ Stream transcription error: {e}")
        import traceback
        traceback.print_exc()


async def test_health_check():
    """Test provider health check."""
    print("\n=== Testing Provider Health Check ===\n")
    
    config = {
        "api_key": "test-key",
        "model_id": "scribe_v2_realtime",
    }
    
    try:
        provider = ElevenLabsProvider(config)
        is_healthy = await provider.health_check()
        print(f"Health check: {'✅ Healthy' if is_healthy else '❌ Unhealthy'}")
    except Exception as e:
        print(f"❌ Health check failed: {e}")


async def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("ElevenLabs Audio Transcription Provider Test Suite")
    print("=" * 70 + "\n")
    
    # Test health check
    await test_health_check()
    
    # Test file transcription
    await test_file_transcription()
    
    # Test stream transcription
    await test_stream_transcription()
    
    print("\n" + "=" * 70)
    print("Tests completed!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
