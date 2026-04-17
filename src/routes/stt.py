"""
STT 라우트 (세션 관리 + 오디오 스트리밍)
CLOVA STT와 Diart 화자 구분을 병렬 실행하여 결합합니다.
"""

import asyncio
import logging
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.services.stt_service import ClovaSpeechClient, parse_clova_response
from src.services.speaker_service import speaker_service
from src.services.diart_service import DiartService, SpeakerMatcher

logger = logging.getLogger(__name__)

router = APIRouter()

# 활성 STT 세션 관리
active_sessions: dict = {}


@router.post("/stt/session")
async def start_stt_session():
  """STT 세션 시작"""
  session_id = f"stt_{len(active_sessions) + 1}_{int(__import__('time').time())}"
  active_sessions[session_id] = {"client": None, "status": "initialized"}
  logger.info(f"STT 세션 시작: {session_id}")
  return {"sessionId": session_id}


@router.post("/stt/session/{session_id}/stop")
async def stop_stt_session(session_id: str):
  """STT 세션 종료"""
  if session_id in active_sessions:
    client: ClovaSpeechClient = active_sessions[session_id].get("client")
    if client:
      await client.close()
    del active_sessions[session_id]
    logger.info(f"STT 세션 종료: {session_id}")
    return {"status": "stopped"}
  return {"error": "세션을 찾을 수 없습니다"}


@router.websocket("/stt/stream")
async def websocket_stt_stream(websocket: WebSocket):
  """오디오 스트리밍 WebSocket 엔드포인트

  쿼리 파라미터: sessionId
  요청: 바이너리 (PCM 16kHz 오디오 청크)
  응답: JSON (STT + 화자 결합 결과)
  """
  await websocket.accept()

  session_id = websocket.query_params.get("sessionId")
  if not session_id or session_id not in active_sessions:
    await websocket.send_json({"error": "유효하지 않은 sessionId"})
    await websocket.close()
    return

  secret_key = os.getenv("CLOVA_SPEECH_SECRET")
  if not secret_key:
    await websocket.send_json({"error": "CLOVA_SPEECH_SECRET 환경변수 필요"})
    await websocket.close()
    return

  hf_token = os.getenv("HUGGINGFACE_TOKEN")

  # CLOVA STT 클라이언트
  client = ClovaSpeechClient(secret_key)
  active_sessions[session_id]["client"] = client

  # Diart 화자 구분 (HuggingFace 토큰이 있을 때만 활성화)
  diart_service = None
  matcher = SpeakerMatcher()

  if hf_token:
    try:
      diart_service = DiartService(hf_token)
      # 모델 로드는 블로킹이므로 별도 스레드에서 실행
      loop = asyncio.get_event_loop()
      await loop.run_in_executor(None, diart_service.initialize)
      logger.info(f"Diart 활성화: {session_id}")
    except Exception as e:
      logger.warning(f"Diart 초기화 실패 (화자 구분 비활성화): {str(e)}")
      diart_service = None
  else:
    logger.info("HUGGINGFACE_TOKEN 없음 - 화자 구분 비활성화")

  try:
    await client.connect()
    active_sessions[session_id]["status"] = "streaming"

    async def receive_audio():
      """Extension → CLOVA 큐 + Diart에 오디오 전달"""
      loop = asyncio.get_event_loop()
      try:
        while True:
          data = await websocket.receive_bytes()
          if data:
            await client.send_audio_chunk(data)
            # Diart 화자 구분 병렬 처리 (블로킹이므로 executor 사용)
            if diart_service:
              segments = await loop.run_in_executor(
                None, diart_service.process_chunk, data
              )
              if segments:
                matcher.add_segments(segments)
      except WebSocketDisconnect:
        logger.info(f"WebSocket 끊김: {session_id}")
      except Exception as e:
        logger.error(f"오디오 수신 오류: {str(e)}")
      finally:
        await client.close()

    async def stream_results():
      """CLOVA 결과 + Diart 화자 → Extension 전송"""
      try:
        async for response in client.stream_results():
          parsed = parse_clova_response(response)
          for result in parsed.get("results", []):
            start_ms = result.get("startMs", 0)
            end_ms = result.get("endMs", 0)

            # Diart 화자 매핑 우선, 없으면 CLOVA 레이블 사용
            if diart_service:
              diart_speaker = matcher.find_speaker(start_ms, end_ms)
              raw_speaker = diart_speaker or "SPEAKER_UNKNOWN"
            else:
              raw_speaker = result.get("speaker", "SPEAKER_UNKNOWN")

            # SPEAKER_N → 멤버 이름 치환
            resolved_speaker = speaker_service.resolve(session_id, raw_speaker)

            await websocket.send_json({
              "sessionId": session_id,
              "speaker": resolved_speaker,
              "text": result.get("text"),
              "startMs": start_ms,
              "endMs": end_ms,
              "isFinal": result.get("isFinal"),
            })
      except Exception as e:
        logger.error(f"결과 전송 오류: {str(e)}")
        try:
          await websocket.send_json({"error": str(e)})
        except Exception:
          pass

    await asyncio.gather(receive_audio(), stream_results())

  except Exception as e:
    logger.error(f"STT 스트림 오류: {str(e)}")
    try:
      await websocket.send_json({"error": str(e)})
      await websocket.close()
    except Exception:
      pass
  finally:
    if session_id in active_sessions:
      active_sessions[session_id]["status"] = "closed"
    if diart_service:
      diart_service.reset()
