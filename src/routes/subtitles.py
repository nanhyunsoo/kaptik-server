"""
자막 스트리밍 엔드포인트
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# ============= 타입 정의 =============


class SubtitleStartRequest(BaseModel):
    """자막 시작 요청"""

    videoId: str
    language: str = "ko"


class SubtitleStopRequest(BaseModel):
    """자막 중단 요청"""

    videoId: str


class SubtitleResponse(BaseModel):
    """API 응답"""

    success: bool
    message: str


class SubtitleData(BaseModel):
    """자막 데이터"""

    timestamp: int
    speaker: str
    original_text: str
    translated_text: str
    duration: int


# ============= 상태 관리 =============

# 활성 스트리밍 상태
active_streams: Dict[str, Set[WebSocket]] = {}

# Mock 자막 데이터
MOCK_SUBTITLES = [
    {
        "speaker": "Speaker A",
        "original_text": "Good morning everyone",
        "translated_text": "안녕하세요 여러분",
        "duration": 3000,
    },
    {
        "speaker": "Speaker B",
        "original_text": "Welcome to this presentation",
        "translated_text": "이 프레젠테이션에 오신 것을 환영합니다",
        "duration": 3000,
    },
    {
        "speaker": "Speaker A",
        "original_text": "Today we will discuss AI",
        "translated_text": "오늘 우리는 AI에 대해 논의할 것입니다",
        "duration": 3000,
    },
    {
        "speaker": "Speaker B",
        "original_text": "Let me start with an overview",
        "translated_text": "개요부터 시작하겠습니다",
        "duration": 3000,
    },
    {
        "speaker": "Speaker A",
        "original_text": "This is very important",
        "translated_text": "이것은 매우 중요합니다",
        "duration": 3000,
    },
]

# ============= HTTP 엔드포인트 =============


@router.post("/subtitles/start", response_model=SubtitleResponse)
async def start_subtitles(request: SubtitleStartRequest) -> SubtitleResponse:
    """
    자막 스트리밍 시작

    - **videoId**: YouTube 영상 ID
    - **language**: 언어 코드 (기본값: ko)
    """
    try:
        video_id = request.videoId
        language = request.language

        logger.info(f"자막 스트리밍 시작 요청: videoId={video_id}, language={language}")

        # 해당 videoId의 스트림이 없으면 생성
        if video_id not in active_streams:
            active_streams[video_id] = set()

        return SubtitleResponse(
            success=True,
            message=f"자막 스트리밍이 시작되었습니다 (videoId: {video_id})",
        )
    except Exception as e:
        logger.error(f"자막 시작 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/subtitles/stop", response_model=SubtitleResponse)
async def stop_subtitles(request: SubtitleStopRequest) -> SubtitleResponse:
    """
    자막 스트리밍 중단

    - **videoId**: YouTube 영상 ID
    """
    try:
        video_id = request.videoId

        logger.info(f"자막 스트리밍 중단 요청: videoId={video_id}")

        # 해당 videoId의 모든 WebSocket 연결 종료
        if video_id in active_streams:
            # 모든 클라이언트에게 종료 메시지 전송
            for websocket in active_streams[video_id]:
                try:
                    await websocket.send_json(
                        {
                            "type": "closed",
                            "message": "서버에서 스트리밍을 종료했습니다",
                        }
                    )
                except Exception as e:
                    logger.warning(f"WebSocket 메시지 전송 실패: {str(e)}")

            # 스트림 정리
            del active_streams[video_id]

        return SubtitleResponse(
            success=True,
            message=f"자막 스트리밍이 중단되었습니다 (videoId: {video_id})",
        )
    except Exception as e:
        logger.error(f"자막 중단 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============= WebSocket 엔드포인트 =============


@router.websocket("/subtitles/stream")
async def websocket_subtitle_stream(websocket: WebSocket):
    """
    자막 실시간 스트리밍 WebSocket

    쿼리 파라미터:
    - videoId: YouTube 영상 ID
    """
    await websocket.accept()

    video_id = None
    try:
        # 쿼리 파라미터에서 videoId 추출
        video_id = websocket.query_params.get("videoId")

        if not video_id:
            await websocket.send_json(
                {"type": "error", "message": "videoId가 필요합니다"}
            )
            await websocket.close(code=1008)
            return

        logger.info(f"WebSocket 연결: videoId={video_id}")

        # 연결을 active_streams에 등록
        if video_id not in active_streams:
            active_streams[video_id] = set()
        active_streams[video_id].add(websocket)

        # 연결 확인 메시지
        await websocket.send_json(
            {
                "type": "connected",
                "message": f"자막 스트림에 연결되었습니다 (videoId: {video_id})",
            }
        )

        # Mock 자막 스트리밍 시작
        subtitle_index = 0
        while True:
            # 3초마다 새로운 자막 전송
            await asyncio.sleep(3)

            # Mock 자막 데이터 생성
            subtitle_info = MOCK_SUBTITLES[subtitle_index % len(MOCK_SUBTITLES)]
            subtitle_data = SubtitleData(
                timestamp=int(datetime.now().timestamp() * 1000),
                speaker=subtitle_info["speaker"],
                original_text=subtitle_info["original_text"],
                translated_text=subtitle_info["translated_text"],
                duration=subtitle_info["duration"],
            )

            # 클라이언트에 자막 전송
            await websocket.send_json(
                {"type": "subtitle", "data": subtitle_data.model_dump()}
            )

            logger.debug(f"자막 전송: {subtitle_data.translated_text}")
            subtitle_index += 1

    except WebSocketDisconnect:
        logger.info(f"WebSocket 연결 종료: videoId={video_id}")
        if video_id and video_id in active_streams:
            active_streams[video_id].discard(websocket)
            if not active_streams[video_id]:
                del active_streams[video_id]

    except Exception as e:
        logger.error(f"WebSocket 에러: {str(e)}")
        try:
            await websocket.send_json(
                {"type": "error", "message": f"서버 에러: {str(e)}"}
            )
        except Exception:
            pass
        finally:
            if video_id and video_id in active_streams:
                active_streams[video_id].discard(websocket)
                if not active_streams[video_id]:
                    del active_streams[video_id]
