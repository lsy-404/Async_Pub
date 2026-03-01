"""
ElevenLabs SDK API 探索脚本
用于调研 SDK 的正确使用方法
"""

import sys
import inspect


def explore_sdk():
    """探索 ElevenLabs SDK 的 API 结构"""
    try:
        from elevenlabs import ElevenLabs
        
        print("=" * 80)
        print("ElevenLabs SDK 版本信息")
        print("=" * 80)
        
        # 创建客户端实例（使用假 API key 只是为了探索结构）
        client = ElevenLabs(api_key="test_key_for_exploration")
        
        print(f"\nElevenLabs 类型: {type(client)}")
        print(f"\nElevenLabs 主要属性和方法:")
        for attr in dir(client):
            if not attr.startswith('_'):
                obj = getattr(client, attr)
                print(f"  - {attr}: {type(obj).__name__}")
        
        # 探索 speech_to_text 模块
        print("\n" + "=" * 80)
        print("speech_to_text 模块")
        print("=" * 80)
        
        if hasattr(client, 'speech_to_text'):
            stt = client.speech_to_text
            print(f"\nspeech_to_text 类型: {type(stt)}")
            print(f"\nspeech_to_text 属性和方法:")
            for attr in dir(stt):
                if not attr.startswith('_'):
                    obj = getattr(stt, attr)
                    print(f"  - {attr}: {type(obj).__name__}")
        
        # 探索 realtime 模块
        print("\n" + "=" * 80)
        print("speech_to_text.realtime 模块")
        print("=" * 80)
        
        if hasattr(client, 'speech_to_text') and hasattr(client.speech_to_text, 'realtime'):
            realtime = client.speech_to_text.realtime
            print(f"\nrealtime 类型: {type(realtime)}")
            print(f"\nrealtime 属性和方法:")
            for attr in dir(realtime):
                if not attr.startswith('_'):
                    obj = getattr(realtime, attr)
                    print(f"  - {attr}: {type(obj).__name__}")
                    
                    # 如果是方法，打印签名
                    if callable(obj):
                        try:
                            sig = inspect.signature(obj)
                            print(f"    签名: {attr}{sig}")
                        except Exception as e:
                            print(f"    (无法获取签名: {e})")
        
        # 检查 convert 方法
        print("\n" + "=" * 80)
        print("检查文件转录方法")
        print("=" * 80)
        
        if hasattr(client, 'speech_to_text'):
            stt = client.speech_to_text
            
            # 查找可能的文件转录方法
            file_methods = []
            for attr in dir(stt):
                if not attr.startswith('_') and callable(getattr(stt, attr)):
                    if any(keyword in attr.lower() for keyword in ['convert', 'transcribe', 'file', 'audio']):
                        file_methods.append(attr)
            
            print(f"\n可能的文件转录方法: {file_methods}")
            
            for method_name in file_methods:
                method = getattr(stt, method_name)
                try:
                    sig = inspect.signature(method)
                    print(f"\n{method_name}{sig}")
                    
                    # 获取文档字符串
                    if method.__doc__:
                        print(f"  文档: {method.__doc__[:200]}...")
                except Exception as e:
                    print(f"  (无法获取详细信息: {e})")
        
        # 探索 RealtimeEvents
        print("\n" + "=" * 80)
        print("RealtimeEvents 枚举")
        print("=" * 80)
        
        try:
            from elevenlabs import RealtimeEvents
            print(f"\nRealtimeEvents 类型: {type(RealtimeEvents)}")
            print(f"\n可用事件:")
            for attr in dir(RealtimeEvents):
                if not attr.startswith('_'):
                    value = getattr(RealtimeEvents, attr)
                    print(f"  - {attr} = {value}")
        except ImportError as e:
            print(f"\n无法导入 RealtimeEvents: {e}")
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    explore_sdk()
    
    print("\n" + "=" * 80)
    print("探索完成！")
    print("=" * 80)
