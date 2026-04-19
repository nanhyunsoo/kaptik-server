"""
Azure Speaker Identification 음성 등록 스크립트
실행 방법: python scripts/enroll_speaker.py --name 민지 --audio path/to/audio.wav
"""

import os
import sys
import json
import argparse
import asyncio
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

import azure.cognitiveservices.speech as speechsdk

AZURE_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_REGION = os.getenv("AZURE_SPEECH_REGION")
PROFILES_PATH = os.path.join(os.path.dirname(__file__), '..', 'src', 'data', 'speaker_profiles.json')


def load_profiles() -> dict:
  if os.path.exists(PROFILES_PATH):
    with open(PROFILES_PATH, 'r', encoding='utf-8') as f:
      return json.load(f)
  return {}


def save_profiles(profiles: dict) -> None:
  os.makedirs(os.path.dirname(PROFILES_PATH), exist_ok=True)
  with open(PROFILES_PATH, 'w', encoding='utf-8') as f:
    json.dump(profiles, f, ensure_ascii=False, indent=2)


def enroll(name: str, audio_path: str) -> None:
  if not os.path.exists(audio_path):
    print(f"[오류] 오디오 파일 없음: {audio_path}")
    sys.exit(1)

  speech_config = speechsdk.SpeechConfig(subscription=AZURE_KEY, region=AZURE_REGION)
  client = speechsdk.VoiceProfileClient(speech_config=speech_config)

  print(f"[{name}] 음성 프로필 생성 중...")
  profile = client.create_profile(
    speechsdk.VoiceProfileType.TextIndependentIdentification,
    "ko-KR"
  )
  profile_id = profile.id
  print(f"[{name}] 프로필 생성 완료: {profile_id}")

  # 오디오 파일로 등록
  audio_config = speechsdk.audio.AudioConfig(filename=audio_path)
  result = client.enroll_profile(profile, audio_config)

  if result.reason == speechsdk.ResultReason.EnrolledVoiceProfile:
    print(f"[{name}] 등록 완료 ✅")
    print(f"  - 등록된 음성 길이: {result.enrollment_info.speech_length.total_seconds():.1f}초")

    # 프로필 저장
    profiles = load_profiles()
    profiles[name] = profile_id
    save_profiles(profiles)
    print(f"[{name}] 프로필 저장 완료: {PROFILES_PATH}")
  else:
    print(f"[{name}] 등록 실패: {result.reason}")
    if result.cancellation_details:
      print(f"  오류: {result.cancellation_details.error_details}")


def list_profiles() -> None:
  profiles = load_profiles()
  if not profiles:
    print("등록된 화자가 없습니다.")
    return
  print(f"등록된 화자 ({len(profiles)}명):")
  for name, profile_id in profiles.items():
    print(f"  - {name}: {profile_id}")


def delete_profile(name: str) -> None:
  profiles = load_profiles()
  if name not in profiles:
    print(f"[오류] '{name}' 화자가 없습니다.")
    return

  speech_config = speechsdk.SpeechConfig(subscription=AZURE_KEY, region=AZURE_REGION)
  client = speechsdk.VoiceProfileClient(speech_config=speech_config)

  profile = speechsdk.VoiceProfile(profiles[name])
  client.delete_profile(profile)

  del profiles[name]
  save_profiles(profiles)
  print(f"[{name}] 프로필 삭제 완료")


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Azure 화자 음성 등록")
  subparsers = parser.add_subparsers(dest="command")

  # 등록
  enroll_parser = subparsers.add_parser("enroll", help="음성 등록")
  enroll_parser.add_argument("--name", required=True, help="화자 이름 (예: 민지)")
  enroll_parser.add_argument("--audio", required=True, help="WAV 파일 경로")

  # 목록
  subparsers.add_parser("list", help="등록된 화자 목록")

  # 삭제
  delete_parser = subparsers.add_parser("delete", help="화자 삭제")
  delete_parser.add_argument("--name", required=True, help="삭제할 화자 이름")

  args = parser.parse_args()

  if args.command == "enroll":
    enroll(args.name, args.audio)
  elif args.command == "list":
    list_profiles()
  elif args.command == "delete":
    delete_profile(args.name)
  else:
    parser.print_help()
