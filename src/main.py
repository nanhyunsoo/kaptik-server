"""
Kaptik 자막 스트리밍 서버

Extension에 실시간 자막을 제공하는 FastAPI 서버입니다.
"""

import os
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from src.routes import subtitles, stt, speaker
from src.routes.subtitles import websocket_subtitle_stream

# 환경 변수 로드
load_dotenv()

# FastAPI 앱 생성
app = FastAPI(
    title="Kaptik 자막 API",
    description="YouTube 실시간 자막 스트리밍 서버",
    version="0.1.0",
)

# CORS 설정 (HTTP 요청용)
# TODO: 개발 완료 후 allow_origins을 실제 도메인으로 변경
try:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 개발 단계: 모든 오리진 허용
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
except Exception as e:
    print(f"[Warning] CORS 설정 실패: {str(e)}")

# 라우트 등록
app.include_router(subtitles.router, prefix="/api")
app.include_router(stt.router, prefix="/api")
app.include_router(speaker.router, prefix="/api")

# WebSocket은 CORS 미들웨어 우회를 위해 app에 직접 등록
app.add_api_websocket_route("/subtitles/stream", websocket_subtitle_stream)
app.add_api_websocket_route("/api/stt/stream", stt.websocket_stt_stream)


@app.get("/")
async def root():
    """헬스 체크"""
    return {
        "status": "ok",
        "message": "Kaptik 자막 서버가 실행 중입니다",
        "version": "0.1.0",
    }


@app.get("/health")
async def health():
    """상태 확인"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "3000"))
    host = os.getenv("HOST", "0.0.0.0")

    print(f"[Kaptik] 서버 시작: {host}:{port}")
    uvicorn.run(app, host=host, port=port)
