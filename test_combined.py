"""
CLOVA STT + Diart 화자 구분 통합 테스트
WAV 파일을 CLOVA와 Diart에 각각 처리 후 타임스탬프로 결합합니다.
"""

import sys
import os
import json
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'grpc'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

SECRET_KEY = os.getenv("CLOVA_SPEECH_SECRET", "af9e6d15d6ed47749ac0f3a103b1cff8")
HF_TOKEN = os.getenv("HUGGINGFACE_TOKEN")
WAV_PATH = os.path.join(os.path.dirname(__file__), "test-audio", "BTS_audiosample_cut.wav")

SAMPLE_RATE = 16000
CHUNK_SIZE = 32000  # 1초 분량


# ── torchaudio 없이 WAV를 읽는 커스텀 AudioSource ─────────────
def make_wav_audio_source(wav_path: str, sample_rate: int, block_duration: float = 0.5):
  """wave 모듈로 WAV를 읽어 diart AudioSource처럼 동작하는 객체 반환"""
  from rx.subject import Subject

  class WavAudioSource:
    def __init__(self):
      self.uri = Path(wav_path).stem
      self.sample_rate = sample_rate
      self.stream = Subject()
      self.block_size = int(sample_rate * block_duration)
      self.is_closed = False
      with wave.open(wav_path, 'rb') as wf:
        self._duration = wf.getnframes() / wf.getframerate()

    @property
    def duration(self):
      return self._duration

    def read(self):
      with wave.open(wav_path, 'rb') as wf:
        while not self.is_closed:
          frames = wf.readframes(self.block_size)
          if not frames:
            break
          samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
          # 마지막 청크가 짧으면 0으로 패딩
          if len(samples) < self.block_size:
            samples = np.pad(samples, (0, self.block_size - len(samples)))
          # shape: (channels=1, samples)
          self.stream.on_next(samples.reshape(1, -1))
      self.stream.on_completed()

    def close(self):
      self.is_closed = True

  return WavAudioSource()


# ── Diart: WAV 처리 → 화자 세그먼트 수집 ─────────────────────
def run_diart(wav_path: str, hf_token: str) -> list[dict]:
  from diart import SpeakerDiarization, SpeakerDiarizationConfig
  from diart.inference import StreamingInference
  from pyannote.audio import Model

  print("[Diart] 모델 로드 중...")

  def load_model(model_id):
    try:
      return Model.from_pretrained(model_id, token=hf_token)
    except TypeError:
      return Model.from_pretrained(model_id, use_auth_token=hf_token)

  seg_model = load_model("pyannote/segmentation")
  emb_model = load_model("pyannote/embedding")

  config = SpeakerDiarizationConfig(
    segmentation=seg_model,
    embedding=emb_model,
    duration=5.0,
    step=0.5,
    latency="min",
    delta_new=0.7,  # 기본값 1.0 → 새 화자 추가 핵심 파라미터
  )
  pipeline = SpeakerDiarization(config)
  source = make_wav_audio_source(wav_path, sample_rate=SAMPLE_RATE)

  segments = []

  def collect_result(result):
    annotation, _ = result
    if annotation:
      for segment, _, label in annotation.itertracks(yield_label=True):
        segments.append({
          "speaker": label,
          "start": segment.start,
          "end": segment.end,
        })

  print("[Diart] 화자 구분 처리 시작...")
  inference = StreamingInference(
    pipeline, source,
    batch_size=1,
    do_plot=False,
    show_progress=True,
  )
  inference.attach_hooks(collect_result)
  inference()

  print(f"[Diart] 완료: {len(segments)}개 세그먼트")
  return segments


# ── 타임스탬프 겹침으로 화자 매핑 ─────────────────────────────
def find_speaker(segments: list[dict], start_ms: int, end_ms: int) -> str:
  start_s, end_s = start_ms / 1000.0, end_ms / 1000.0
  best, best_overlap = "SPEAKER_?", 0.0
  for seg in segments:
    overlap = max(0.0, min(end_s, seg["end"]) - max(start_s, seg["start"]))
    if overlap > best_overlap:
      best_overlap = overlap
      best = seg["speaker"]
  return best


# ── CLOVA STT ─────────────────────────────────────────────────
def run_clova_stt(wav_path: str) -> list[dict]:
  import grpc
  from nest_pb2 import NestRequest, NestConfig, NestData, RequestType
  from nest_pb2_grpc import NestServiceStub

  chunks = []
  with wave.open(wav_path, 'rb') as wf:
    while True:
      raw = wf.readframes(CHUNK_SIZE // 2)
      if not raw:
        break
      chunks.append(raw)

  def generate():
    yield NestRequest(
      type=RequestType.CONFIG,
      config=NestConfig(config=json.dumps({"transcription": {"language": "ko"}}))
    )
    for i, chunk in enumerate(chunks):
      yield NestRequest(
        type=RequestType.DATA,
        data=NestData(chunk=chunk, extra_contents=json.dumps({"seqId": i, "epFlag": False}))
      )
    yield NestRequest(
      type=RequestType.DATA,
      data=NestData(chunk=b"", extra_contents=json.dumps({"seqId": 0, "epFlag": True}))
    )

  channel = grpc.secure_channel("clovaspeech-gw.ncloud.com:50051", grpc.ssl_channel_credentials())
  stub = NestServiceStub(channel)

  results = []
  try:
    for resp in stub.recognize(generate(), metadata=(("authorization", f"Bearer {SECRET_KEY}"),)):
      data = json.loads(resp.contents)
      if "transcription" not in data.get("responseType", []):
        continue
      t = data["transcription"]
      text = t.get("text", "").strip()
      if not text:
        continue
      results.append({
        "text": text,
        "startMs": t.get("startTimestamp", 0),
        "endMs": t.get("endTimestamp", 0),
        "isFinal": t.get("epFlag", False),
      })
  finally:
    channel.close()

  return results


# ── 메인 ──────────────────────────────────────────────────────
def main():
  if not os.path.exists(WAV_PATH):
    print(f"[오류] WAV 파일 없음: {WAV_PATH}")
    sys.exit(1)
  if not HF_TOKEN:
    print("[오류] HUGGINGFACE_TOKEN 환경변수 필요")
    sys.exit(1)

  print("=" * 60)
  print("CLOVA STT + Diart 화자 구분 통합 테스트")
  print("=" * 60)

  # 1단계: Diart로 화자 세그먼트 수집
  diart_segments = run_diart(WAV_PATH, HF_TOKEN)
  speakers_found = set(s["speaker"] for s in diart_segments)
  print(f"\n감지된 화자: {speakers_found}\n")

  # 2단계: CLOVA STT
  print("[STT] CLOVA 처리 시작...")
  stt_results = run_clova_stt(WAV_PATH)

  # 3단계: 결합 후 출력
  print("\n" + "=" * 60)
  print("결합 결과 (화자 + 텍스트)")
  print("=" * 60)
  for r in stt_results:
    speaker = find_speaker(diart_segments, r["startMs"], r["endMs"])
    status = "✅" if r["isFinal"] else "⏳"
    print(f"{status} [{r['startMs']}ms~{r['endMs']}ms] [{speaker}] {r['text']}")

  print(f"\n총 STT 결과: {len(stt_results)}개 / Diart 세그먼트: {len(diart_segments)}개")


if __name__ == "__main__":
  main()
