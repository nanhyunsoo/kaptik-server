"""
DiartService MP3 파일 테스트
test-audio/BTS_audiosample_cut.mp3 → 화자 구분 결과 출력
"""

import sys
import os
import logging
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from services.diart_service import DiartService
from dotenv import load_dotenv

load_dotenv()

AUDIO_PATH = os.path.join(os.path.dirname(__file__), "test-audio", "BTS_audiosample_cut.wav")
HF_TOKEN = os.environ.get("HUGGINGFACE_TOKEN", "")
CHUNK_DURATION = 0.5  # 0.5초 청크 단위로 전송
SAMPLE_RATE = 16000


def load_wav_as_pcm(wav_path: str) -> bytes:
  """WAV 파일 → PCM 16bit bytes (16kHz mono 변환 포함)"""
  import wave, struct

  with wave.open(wav_path, "rb") as wf:
    orig_sr = wf.getframerate()
    orig_ch = wf.getnchannels()
    orig_sw = wf.getsampwidth()
    n_frames = wf.getnframes()
    raw = wf.readframes(n_frames)

  logging.info(f"WAV: {orig_sr}Hz {orig_ch}ch {orig_sw*8}bit, {n_frames} frames ({n_frames/orig_sr:.1f}s)")

  # int16 변환
  samples = np.frombuffer(raw, dtype=np.int16 if orig_sw == 2 else np.int8)

  # 스테레오 → 모노
  if orig_ch == 2:
    samples = samples.reshape(-1, 2).mean(axis=1).astype(np.int16)

  # 리샘플링 (필요 시)
  if orig_sr != SAMPLE_RATE:
    import scipy.signal as sg
    samples = sg.resample_poly(samples, SAMPLE_RATE, orig_sr).astype(np.int16)
    logging.info(f"리샘플링: {orig_sr}Hz → {SAMPLE_RATE}Hz")

  return samples.tobytes()


def main():
  if not HF_TOKEN:
    logging.error("HUGGINGFACE_TOKEN 환경변수가 없습니다.")
    sys.exit(1)

  # WAV 파일 로드
  pcm_bytes = load_wav_as_pcm(AUDIO_PATH)
  total_samples = len(pcm_bytes) // 2  # int16 = 2 bytes
  duration_s = total_samples / SAMPLE_RATE
  logging.info(f"총 오디오 길이: {duration_s:.1f}초")

  # DiartService 초기화
  service = DiartService(hf_token=HF_TOKEN)
  logging.info("Diart 파이프라인 초기화 중... (모델 다운로드 시 수 분 소요)")
  service.initialize()

  # 청크 단위로 처리
  chunk_bytes = int(SAMPLE_RATE * CHUNK_DURATION) * 2  # 16bit = 2 bytes/sample
  all_segments = []
  offset = 0
  chunk_count = 0

  logging.info(f"오디오 처리 시작 (청크 크기: {CHUNK_DURATION}s)")
  while offset < len(pcm_bytes):
    chunk = pcm_bytes[offset: offset + chunk_bytes]
    offset += chunk_bytes
    chunk_count += 1

    segments = service.process_chunk(chunk)
    if segments:
      all_segments.extend(segments)
      for seg in segments:
        print(f"  [{seg['start']:6.2f}s ~ {seg['end']:6.2f}s]  {seg['speaker']}")

  logging.info(f"\n처리 완료: {chunk_count}개 청크, {len(all_segments)}개 세그먼트")

  # 화자별 통계
  if all_segments:
    speakers = {}
    for seg in all_segments:
      sp = seg["speaker"]
      dur = seg["end"] - seg["start"]
      speakers[sp] = speakers.get(sp, 0) + dur

    print("\n=== 화자별 발화 시간 ===")
    for sp, dur in sorted(speakers.items()):
      print(f"  {sp}: {dur:.1f}초")
  else:
    print("\n감지된 화자 세그먼트 없음")


if __name__ == "__main__":
  main()
