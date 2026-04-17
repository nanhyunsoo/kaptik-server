"""
CLOVA Speech gRPC 직접 테스트 스크립트
STT 텍스트 + Diarization(발화자 구분) 결과 확인용
"""

import sys
import os
import json
import grpc
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'grpc'))
from nest_pb2 import NestRequest, NestConfig, NestData, RequestType
from nest_pb2_grpc import NestServiceStub

SECRET_KEY = "af9e6d15d6ed47749ac0f3a103b1cff8"
GRPC_HOST = "clovaspeech-gw.ncloud.com:50051"
CHUNK_SIZE = 32000  # 약 1초 분량


def read_wav_chunks(wav_path: str):
    """WAV 파일을 PCM 청크로 읽기"""
    with wave.open(wav_path, 'rb') as wf:
        print(f"[오디오 정보]")
        print(f"  샘플레이트: {wf.getframerate()} Hz")
        print(f"  채널수: {wf.getnchannels()}")
        print(f"  비트수: {wf.getsampwidth() * 8} bit")
        total_frames = wf.getnframes()
        duration = total_frames / wf.getframerate()
        print(f"  길이: {duration:.1f}초\n")

        while True:
            chunk = wf.readframes(CHUNK_SIZE // 2)  # 16-bit = 2bytes/frame
            if not chunk:
                break
            yield chunk


def generate_requests(wav_path: str):
    """gRPC 요청 스트림 생성"""
    # 1. CONFIG 메시지
    yield NestRequest(
        type=RequestType.CONFIG,
        config=NestConfig(
            config=json.dumps({
                "transcription": {"language": "ko"},
                "diarization": {"enable": True},
            })
        ),
    )

    # 2. 오디오 DATA 청크
    for seq_id, chunk in enumerate(read_wav_chunks(wav_path)):
        yield NestRequest(
            type=RequestType.DATA,
            data=NestData(
                chunk=chunk,
                extra_contents=json.dumps({"seqId": seq_id, "epFlag": False}),
            ),
        )

    # 3. 종료 신호
    yield NestRequest(
        type=RequestType.DATA,
        data=NestData(
            chunk=b"",
            extra_contents=json.dumps({"seqId": 0, "epFlag": True}),
        ),
    )


def main():
    wav_path = os.path.join(
        os.path.dirname(__file__),
        "test-audio",
        "BTS_audiosample_cut.wav"
    )

    if not os.path.exists(wav_path):
        print(f"[오류] 파일 없음: {wav_path}")
        sys.exit(1)

    print("=" * 50)
    print("CLOVA Speech gRPC 테스트 시작")
    print("=" * 50)

    channel = grpc.secure_channel(GRPC_HOST, grpc.ssl_channel_credentials())
    stub = NestServiceStub(channel)
    metadata = (("authorization", f"Bearer {SECRET_KEY}"),)

    print("[연결] CLOVA gRPC 채널 연결 중...\n")

    try:
        responses = stub.recognize(generate_requests(wav_path), metadata=metadata)

        print("[결과] STT 응답 수신 중...\n")
        for response in responses:
            data = json.loads(response.contents)
            response_types = data.get("responseType", [])

            # config 응답 무시
            if "transcription" not in response_types:
                continue

            transcription = data.get("transcription", {})
            text = transcription.get("text", "").strip()
            ep_flag = transcription.get("epFlag", False)
            start_ms = transcription.get("startTimestamp", 0)
            end_ms = transcription.get("endTimestamp", 0)

            if not text:
                continue

            # epFlag=True: 문장 완성, epFlag=False: partial
            status = "✅ FINAL" if ep_flag else "⏳ partial"
            print(f"{status} [{start_ms}ms~{end_ms}ms] {text}")

    except grpc.RpcError as e:
        print(f"\n[gRPC 오류] {e.code()}: {e.details()}")
    finally:
        channel.close()
        print("\n[완료] 채널 종료")


if __name__ == "__main__":
    main()
