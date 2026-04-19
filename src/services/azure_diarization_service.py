"""
Azure Speaker Diarization + Identification 서비스
실시간 오디오 스트림에서 화자를 구분하고 등록된 프로필로 이름을 매핑합니다.
"""

import json
import logging
import os
import threading
from collections import deque

import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)

PROFILES_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'speaker_profiles.json')


class AzureDiarizationService:
  """Azure Cognitive Services 기반 실시간 화자 구분 + 식별"""

  def __init__(self, api_key: str, region: str):
    self.api_key = api_key
    self.region = region
    self._speech_config = None
    self._conversation_transcriber = None
    self._conversation = None
    self._push_stream = None
    self._audio_config = None
    self._segments: deque = deque(maxlen=500)
    self._lock = threading.Lock()
    self._is_running = False

  def _load_speaker_profiles(self) -> dict:
    """등록된 화자 프로필 로드 {이름: profile_id}"""
    if os.path.exists(PROFILES_PATH):
      with open(PROFILES_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)
    return {}

  def initialize(self) -> None:
    """Azure 화자 구분 파이프라인 초기화"""
    self._speech_config = speechsdk.SpeechConfig(
      subscription=self.api_key,
      region=self.region,
    )
    self._speech_config.speech_recognition_language = "ko-KR"

    # 실시간 PCM 스트림 입력 설정 (16kHz, 16bit, mono)
    stream_format = speechsdk.audio.AudioStreamFormat(
      samples_per_second=16000,
      bits_per_sample=16,
      channels=1,
    )
    self._push_stream = speechsdk.audio.PushAudioInputStream(stream_format)
    self._audio_config = speechsdk.audio.AudioConfig(stream=self._push_stream)

    # 등록된 화자 프로필 로드 후 Participant로 추가
    profiles = self._load_speaker_profiles()
    if profiles:
      self._init_with_identification(profiles)
    else:
      self._init_diarization_only()

  def _init_diarization_only(self) -> None:
    """등록된 프로필 없음 → 순수 화자 구분만"""
    self._conversation_transcriber = speechsdk.transcription.ConversationTranscriber(
      speech_config=self._speech_config,
      audio_config=self._audio_config,
    )
    self._attach_callbacks()
    self._conversation_transcriber.start_transcribing_async()
    self._is_running = True
    logger.info("Azure Diarization 초기화 완료 (프로필 없음 - Guest 모드)")

  def _init_with_identification(self, profiles: dict) -> None:
    """등록된 프로필 있음 → Diarization + Identification"""
    import uuid

    # Conversation 생성
    conversation_id = str(uuid.uuid4())
    self._conversation = speechsdk.transcription.Conversation.create_conversation_async(
      self._speech_config, conversation_id
    ).get()

    # 등록된 화자를 Participant로 추가
    for name, profile_id in profiles.items():
      participant = speechsdk.transcription.Participant.from_user_id(name)
      self._conversation.add_participant_async(participant).get()
      logger.info(f"Participant 추가: {name} ({profile_id})")

    # ConversationTranscriber를 Conversation에 연결
    self._conversation_transcriber = speechsdk.transcription.ConversationTranscriber(
      audio_config=self._audio_config,
    )
    self._conversation_transcriber.join_conversation_async(self._conversation).get()

    self._attach_callbacks()
    self._conversation_transcriber.start_transcribing_async()
    self._is_running = True
    logger.info(f"Azure Diarization + Identification 초기화 완료 ({len(profiles)}명 등록)")

  def _attach_callbacks(self) -> None:
    self._conversation_transcriber.transcribed.connect(self._on_transcribed)
    self._conversation_transcriber.session_stopped.connect(self._on_stopped)
    self._conversation_transcriber.canceled.connect(self._on_canceled)

  def _on_transcribed(self, evt: speechsdk.transcription.ConversationTranscriptionEventArgs) -> None:
    """화자 구분 + 식별 결과 수신"""
    result = evt.result
    if result.reason == speechsdk.ResultReason.RecognizedSpeech and result.text:
      speaker_id = result.speaker_id or "Unknown"
      offset_ms = result.offset // 10000
      duration_ms = result.duration // 10000

      segment = {
        "speaker": speaker_id,
        "start_ms": offset_ms,
        "end_ms": offset_ms + duration_ms,
        "text": result.text,
      }
      with self._lock:
        self._segments.append(segment)
      logger.debug(f"[{speaker_id}] {result.text} ({offset_ms}ms~{offset_ms + duration_ms}ms)")

  def _on_stopped(self, evt) -> None:
    self._is_running = False
    logger.info("Azure Diarization 세션 종료")

  def _on_canceled(self, evt) -> None:
    self._is_running = False
    logger.error(f"Azure Diarization 취소: {evt.cancellation_details.reason}")

  def push_audio(self, pcm_bytes: bytes) -> None:
    """PCM 오디오 청크 전송"""
    if self._push_stream and self._is_running:
      self._push_stream.write(pcm_bytes)

  def get_segments(self) -> list[dict]:
    """현재까지 수집된 화자 세그먼트 반환"""
    with self._lock:
      return list(self._segments)

  def find_speaker(self, start_ms: int, end_ms: int) -> str | None:
    """타임스탬프로 화자 찾기 (최대 겹침 기준)"""
    best_speaker = None
    best_overlap = 0.0

    with self._lock:
      for seg in self._segments:
        overlap = max(0, min(end_ms, seg["end_ms"]) - max(start_ms, seg["start_ms"]))
        if overlap > best_overlap:
          best_overlap = overlap
          best_speaker = seg["speaker"]

    return best_speaker

  def stop(self) -> None:
    """서비스 종료"""
    if self._conversation_transcriber and self._is_running:
      self._conversation_transcriber.stop_transcribing_async()
    if self._push_stream:
      self._push_stream.close()
    self._is_running = False
    logger.info("Azure Diarization 종료")
