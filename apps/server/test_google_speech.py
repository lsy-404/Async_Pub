"""
测试 Google Chirp 2 音频转录功能的简单脚本

使用前确保：
1. 已安装 google-cloud-speech 依赖
2. 已配置 config.toml 中的 [google.speech] 部分
3. 服务器正在运行（python -m uvicorn main:app --reload --port 3001）
"""

import asyncio
import json
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("错误：需要安装 httpx")
    print("运行：pip install httpx")
    sys.exit(1)


async def test_transcribe(audio_file: str, user_id: str = "test-user"):
    """
    测试音频转录功能
    
    Args:
        audio_file: 音频文件路径（opus 或 wav 格式）
        user_id: 用户 ID（用于鉴权）
    """
    audio_path = Path(audio_file)
    if not audio_path.exists():
        print(f"错误：音频文件不存在: {audio_file}")
        return

    # 根据文件扩展名判断编码和采样率
    ext = audio_path.suffix.lower()
    if ext == ".opus":
        encoding = "OPUS"
        sample_rate = 48000
    elif ext == ".wav":
        encoding = "LINEAR16"
        sample_rate = 16000
    else:
        print(f"警告：未知文件格式 {ext}，尝试使用 OPUS 编码")
        encoding = "OPUS"
        sample_rate = 48000

    print(f"🎤 开始转录音频文件: {audio_file}")
    print(f"   编码: {encoding}, 采样率: {sample_rate}Hz")
    print(f"   用户: {user_id}")
    print("-" * 50)

    url = "http://localhost:3001/api/speech/transcribe"
    headers = {"auth": user_id}
    params = {
        "encoding": encoding,
        "sample_rate": sample_rate,
        "language": "zh-CN,en-US",
    }

    # 读取音频文件
    with open(audio_path, "rb") as f:
        audio_data = f.read()

    print(f"📤 音频大小: {len(audio_data) / 1024:.2f} KB")
    print("-" * 50)

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                params=params,
                content=audio_data,
                timeout=60.0,
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    print(f"❌ 错误 {response.status_code}: {error_text.decode()}")
                    return

                print("📝 转录结果：\n")
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]  # 移除 "data: " 前缀

                        if data == "[DONE]":
                            print("\n" + "=" * 50)
                            print("✅ 转录完成")
                            break

                        try:
                            result = json.loads(data)
                            if "error" in result:
                                print(f"❌ 错误: {result['error']}")
                            else:
                                is_final = result.get("is_final", False)
                                transcript = result.get("transcript", "")
                                confidence = result.get("confidence", 0)
                                language = result.get("language_code", "")

                                # 输出格式化结果
                                prefix = "🔵 [最终]" if is_final else "⚪ [临时]"
                                print(f"{prefix} {transcript}")

                                if is_final and confidence > 0:
                                    print(f"     置信度: {confidence:.2%}, 语言: {language}")

                                # 如果有词时间戳，显示
                                if is_final and "words" in result:
                                    print("     词时间戳:")
                                    for word_info in result["words"]:
                                        word = word_info["word"]
                                        start = word_info["start_offset"]
                                        end = word_info["end_offset"]
                                        print(f"       {word}: {start:.2f}s - {end:.2f}s")

                        except json.JSONDecodeError as e:
                            print(f"⚠️  JSON 解析错误: {e}")
                            print(f"   原始数据: {data}")

    except httpx.ConnectError:
        print("❌ 无法连接到服务器")
        print("   请确保服务器正在运行: python -m uvicorn main:app --reload --port 3001")
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python test_google_speech.py <audio_file> [user_id]")
        print("\n示例:")
        print("  python test_google_speech.py audio.opus")
        print("  python test_google_speech.py audio.wav test-user")
        print("\n支持的音频格式:")
        print("  - .opus: OPUS 编码, 48000Hz（推荐）")
        print("  - .wav: LINEAR16 编码, 16000Hz")
        sys.exit(1)

    audio_file = sys.argv[1]
    user_id = sys.argv[2] if len(sys.argv) > 2 else "test-user"

    asyncio.run(test_transcribe(audio_file, user_id))


if __name__ == "__main__":
    main()
