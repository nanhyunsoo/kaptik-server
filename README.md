# Kaptik Server

Kaptik AI 파이프라인 백엔드 서버

## 기능

- **STT** (Speech-to-Text): 음성을 텍스트로 변환
- **번역**: 다국어 번역 API
- **Speaker Diarization**: 화자 식별 및 분리
- **Kpop Glossary**: K-pop 특화 용어 후처리

## 기술 스택

- Python
- FastAPI (예상)

## 브랜치 전략

- `main`: 프로덕션 배포
- `staging`: 개발/검증 환경
- `feature/*`: 기능 개발

## 배포 환경

| 환경 | 도메인 |
|------|--------|
| 프로덕션 | api.kaptik.com |
| 스테이징 | api-staging.kaptik.com |
