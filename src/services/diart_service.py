"""
Diart 실시간 화자 구분 서비스
오디오 청크를 받아 SPEAKER_0, SPEAKER_1 등 화자 세그먼트를 반환합니다.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

# 오디오 설정
SAMPLE_RATE = 16000
STEP = 0.5        # Diart 처리 간격 (초)
DURATION = 5.0    # Diart 슬라이딩 윈도우 크기 (초)


class DiartService:
  """Diart 실시간 화자 구분 파이프라인 (세션당 1개 인스턴스)"""

  def __init__(self, hf_token: str):
    self.hf_token = hf_token
    self.pipeline = None
    self.audio_buffer = np.array([], dtype=np.float32)
    self._chunk_size = int(SAMPLE_RATE * STEP)  # 0.5초 분량 샘플 수

  def initialize(self) -> None:
    """Diart 파이프라인 초기화 (모델 로드)"""
    try:
      from diart import SpeakerDiarization, SpeakerDiarizationConfig
      from pyannote.audio import Model

      logger.info("Diart 파이프라인 초기화 중...")
      def _load_model(model_id: str):
        # pyannote/audio 버전에 따라 인증 인자 이름이 달라질 수 있어 순차 시도
        try:
          return Model.from_pretrained(model_id, token=self.hf_token)
        except TypeError:
          return Model.from_pretrained(model_id, use_auth_token=self.hf_token)

      # gated 모델 접근을 위해 토큰을 명시적으로 주입
      segmentation_model = _load_model("pyannote/segmentation")
      embedding_model = _load_model("pyannote/embedding")

      config = SpeakerDiarizationConfig(
        segmentation=segmentation_model,
        embedding=embedding_model,
        duration=DURATION,
        step=STEP,
        latency="min",
      )
      self.pipeline = SpeakerDiarization(config)
      logger.info("Diart 파이프라인 초기화 완료")
    except Exception as e:
      logger.error(f"Diart 초기화 실패: {str(e)}")
      raise

  def _pcm_to_float(self, pcm_bytes: bytes) -> np.ndarray:
    """PCM 16-bit bytes → float32 [-1.0, 1.0] 변환"""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    return samples.astype(np.float32) / 32768.0

  def process_chunk(self, pcm_bytes: bytes) -> list[dict]:
    """오디오 청크 처리 → 화자 세그먼트 반환

    Returns:
      [{"speaker": "SPEAKER_0", "start": 0.0, "end": 1.5}, ...]
    """
    if self.pipeline is None:
      return []

    # PCM → float32 변환 후 버퍼에 누적
    new_samples = self._pcm_to_float(pcm_bytes)
    self.audio_buffer = np.concatenate([self.audio_buffer, new_samples])

    # 충분한 샘플이 쌓이면 Diart에 처리 요청
    segments = []
    while len(self.audio_buffer) >= self._chunk_size:
      chunk = self.audio_buffer[:self._chunk_size]
      self.audio_buffer = self.audio_buffer[self._chunk_size:]

      try:
        # Diart는 (1, samples) shape의 np.ndarray를 입력으로 받음
        audio_array = chunk.reshape(1, -1)
        annotation, _ = self.pipeline((audio_array, SAMPLE_RATE))
        if annotation is not None:
          for segment, _, label in annotation.itertracks(yield_label=True):
            segments.append({
              "speaker": label,       # "SPEAKER_0", "SPEAKER_1" 등
              "start": segment.start,
              "end": segment.end,
            })
      except Exception as e:
        logger.warning(f"Diart 청크 처리 오류: {str(e)}")

    return segments

  def reset(self) -> None:
    """세션 종료 시 버퍼 초기화"""
    self.audio_buffer = np.array([], dtype=np.float32)


class SpeakerMatcher:
  """CLOVA STT 타임스탬프 ↔ Diart 화자 세그먼트 겹침 매핑"""

  def __init__(self):
    # Diart 세그먼트 버퍼: [{"speaker": "SPEAKER_0", "start": 0.0, "end": 1.5}]
    self._segments: list[dict] = []

  def add_segments(self, segments: list[dict]) -> None:
    """Diart 결과 누적"""
    self._segments.extend(segments)
    # 오래된 세그먼트 정리 (최근 30초만 유지)
    if self._segments:
      latest_end = max(s["end"] for s in self._segments)
      self._segments = [s for s in self._segments if s["end"] > latest_end - 30]

  def find_speaker(self, start_ms: int, end_ms: int) -> str:
    """타임스탬프 겹침으로 화자 찾기

    STT 결과의 시간 범위와 가장 많이 겹치는 Diart 세그먼트의 화자 반환.
    겹치는 세그먼트가 없으면 None 반환.
    """
    start_s = start_ms / 1000.0
    end_s = end_ms / 1000.0

    best_speaker = None
    best_overlap = 0.0

    for seg in self._segments:
      # 겹치는 구간 계산
      overlap_start = max(start_s, seg["start"])
      overlap_end = min(end_s, seg["end"])
      overlap = max(0.0, overlap_end - overlap_start)

      if overlap > best_overlap:
        best_overlap = overlap
        best_speaker = seg["speaker"]

    return best_speaker
