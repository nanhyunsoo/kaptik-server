"""
Azure Speaker Diarization 테스트
WAV 파일을 Azure ConversationTranscriber로 처리합니다.
"""

import os
import sys
import wave
import time

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

AZURE_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_REGION = os.getenv("AZURE_SPEECH_REGION")
WAV_PATH = os.path.join(os.path.dirname(__file__), "test-audio", "BTS_audiosample_cut.wav")

CHUNK_SIZE = 3200  # 100ms 분량 (16000Hz * 2bytes * 0.1s)


def main():
  if not AZURE_KEY:
    print("[오류] AZURE_SPEECH_KEY 환경변수 필요")
    sys.exit(1)

  sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
  from services.azure_diarization_service import AzureDiarizationService

  print("=" * 60)
  print("Azure Speaker Diarization 테스트")
  print("=" * 60)

  service = AzureDiarizationService(AZURE_KEY, AZURE_REGION)
  service.initialize()

  print("[Azure] 오디오 스트리밍 시작...")
  with wave.open(WAV_PATH, 'rb') as wf:
    total_frames = wf.getnframes()
    frame_rate = wf.getframerate()
    duration = total_frames / frame_rate
    print(f"파일 길이: {duration:.1f}초")

    while True:
      data = wf.readframes(CHUNK_SIZE // 2)
      if not data:
        break
      service.push_audio(data)
      time.sleep(0.05)  # 실시간 시뮬레이션

  print("[Azure] 스트리밍 완료, 결과 대기 중...")
  time.sleep(5)  # 마지막 결과 처리 대기

  segments = service.get_segments()
  print(f"\n총 {len(segments)}개 세그먼트 수집")
  print("=" * 60)
  speakers = set(s["speaker"] for s in segments)
  print(f"감지된 화자: {speakers}")
  print("=" * 60)

  for seg in segments:
    print(f"[{seg['start_ms']}ms~{seg['end_ms']}ms] [{seg['speaker']}] {seg['text']}")

  service.stop()


if __name__ == "__main__":
  main()
