"""
화자 매핑 API 라우트
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src.services.speaker_service import speaker_service

logger = logging.getLogger(__name__)

router = APIRouter()


class SpeakerMapping(BaseModel):
  """화자 매핑 요청"""

  sessionId: str
  mapping: dict[str, str]  # {"spk_0": "민지", "spk_1": "하니"}


@router.post("/speakers/mapping")
async def set_speaker_mapping(data: SpeakerMapping):
  """화자 매핑 등록"""
  try:
    speaker_service.set_mapping(data.sessionId, data.mapping)
    return {"status": "ok", "sessionId": data.sessionId}
  except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))


@router.get("/speakers/mapping")
async def get_speaker_mapping(sessionId: str):
  """화자 매핑 조회"""
  mapping = speaker_service.get_mapping(sessionId)
  return {"sessionId": sessionId, "mapping": mapping}


@router.delete("/speakers/mapping")
async def delete_speaker_mapping(sessionId: str):
  """화자 매핑 삭제"""
  speaker_service.clear_mapping(sessionId)
  return {"status": "ok", "sessionId": sessionId}
