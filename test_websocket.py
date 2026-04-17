"""
WebSocket 클라이언트 테스트
"""

import asyncio
import websockets
import json


async def test_websocket():
    """WebSocket 스트리밍 테스트"""
    uri = "ws://localhost:3000/subtitles/stream?videoId=test123"

    print(f"[Test] WebSocket 연결: {uri}")

    try:
        async with websockets.connect(uri, ping_interval=None) as websocket:
            print("[Test] 연결 성공!")

            # 5개의 메시지 수신
            for i in range(5):
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=5)
                    data = json.loads(message)

                    if data["type"] == "connected":
                        print(f"[Msg] {data['message']}")
                    elif data["type"] == "subtitle":
                        subtitle = data["data"]
                        print(
                            f"[자막 {i}] {subtitle['speaker']}: {subtitle['translated_text']}"
                        )
                except asyncio.TimeoutError:
                    print("[Error] 메시지 수신 타임아웃")
                    break

            print("[Test] 테스트 완료!")

    except Exception as e:
        print(f"[Error] {type(e).__name__}: {str(e)}")


if __name__ == "__main__":
    asyncio.run(test_websocket())
