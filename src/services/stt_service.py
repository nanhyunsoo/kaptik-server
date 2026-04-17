"""
CLOVA Speech gRPC 클라이언트
YouTube 오디오를 실시간 STT로 변환합니다.
"""

import json
import asyncio
import logging
import grpc
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'grpc'))
from nest_pb2 import NestRequest, NestConfig, NestData, RequestType
from nest_pb2_grpc import NestServiceStub

logger = logging.getLogger(__name__)

GRPC_HOST = "clovaspeech-gw.ncloud.com:50051"
CHUNK_SIZE = 32000  # 약 1초 분량 (16kHz * 2bytes * 1ch)


class ClovaSpeechClient:
  """CLOVA Speech gRPC 클라이언트 (세션당 1개 인스턴스)"""

  def __init__(self, secret_key: str):
    self.secret_key = secret_key
    self.audio_queue: asyncio.Queue = asyncio.Queue()
    self.channel = None
    self.stub = None
    self._seq_id = 0
    self._stopped = False

  async def connect(self) -> None:
    """gRPC 채널 연결"""
    self.channel = grpc.aio.secure_channel(
      GRPC_HOST,
      grpc.ssl_channel_credentials(),
    )
    self.stub = NestServiceStub(self.channel)
    logger.info("CLOVA gRPC 채널 연결됨")

  async def send_audio_chunk(self, audio_chunk: bytes) -> None:
    """오디오 청크를 큐에 추가"""
    if not self._stopped:
      await self.audio_queue.put(audio_chunk)

  async def _request_generator(self):
    """gRPC 요청 스트림 생성기"""
    # 첫 메시지: CONFIG
    yield NestRequest(
      type=RequestType.CONFIG,
      config=NestConfig(
        config=json.dumps({
          "transcription": {"language": "ko"},
          "diarization": {"enable": True},
        })
      ),
    )

    # 이후: 오디오 DATA 청크
    while not self._stopped:
      try:
        chunk = await asyncio.wait_for(self.audio_queue.get(), timeout=1.0)
        if chunk is None:
          # 종료 신호: epFlag=True로 마지막 청크 전송
          yield NestRequest(
            type=RequestType.DATA,
            data=NestData(
              chunk=b"",
              extra_contents=json.dumps({"seqId": self._seq_id, "epFlag": True}),
            ),
          )
          break

        yield NestRequest(
          type=RequestType.DATA,
          data=NestData(
            chunk=chunk,
            extra_contents=json.dumps({"seqId": self._seq_id, "epFlag": False}),
          ),
        )
        self._seq_id += 1

      except asyncio.TimeoutError:
        # 큐 비어있음 - 계속 대기
        continue

  async def stream_results(self):
    """CLOVA 응답 스트림 (async generator)"""
    metadata = (("authorization", f"Bearer {self.secret_key}"),)

    try:
      async for response in self.stub.recognize(
        self._request_generator(),
        metadata=metadata,
      ):
        data = json.loads(response.contents)
        yield data
    except grpc.aio.AioRpcError as e:
      logger.error(f"gRPC 오류: {e.code()} - {e.details()}")
      raise
    except Exception as e:
      logger.error(f"스트림 수신 오류: {str(e)}")
      raise

  async def close(self) -> None:
    """연결 종료"""
    self._stopped = True
    await self.audio_queue.put(None)  # 종료 신호
    if self.channel:
      await self.channel.close()
      logger.info("CLOVA gRPC 채널 종료")


def parse_clova_response(response: dict) -> dict:
  """CLOVA gRPC 응답 파싱

  실제 응답 형식:
  {
    "responseType": ["transcription"],
    "transcription": {
      "text": "안녕하세요",
      "epFlag": false,       // false: partial, true: final 문장
      "startTimestamp": 50,
      "endTimestamp": 1500,
    }
  }
  """
  response_types = response.get("responseType", [])

  # config 응답은 무시
  if "transcription" not in response_types:
    return {"results": []}

  transcription = response.get("transcription", {})
  text = transcription.get("text", "").strip()

  if not text:
    return {"results": []}

  ep_flag = transcription.get("epFlag", False)
  start_ms = transcription.get("startTimestamp", 0)
  end_ms = transcription.get("endTimestamp", 0)

  # diarization 필드가 있으면 화자별로, 없으면 단일 결과
  diarization = transcription.get("diarization", [])

  results = []
  if diarization:
    for segment in diarization:
      results.append({
        "speaker": segment.get("label", "spk_0"),
        "text": text,
        "startMs": segment.get("start", start_ms),
        "endMs": segment.get("end", end_ms),
        "isFinal": ep_flag,
      })
  else:
    results.append({
      "speaker": "spk_0",
      "text": text,
      "startMs": start_ms,
      "endMs": end_ms,
      "isFinal": ep_flag,
    })

  return {"results": results}
