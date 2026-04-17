"""
화자 ID 매핑 서비스
Diart 레이블(SPEAKER_0, SPEAKER_1)을 멤버 이름으로 치환합니다.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class SpeakerService:
  """세션별 화자 매핑 관리"""

  def __init__(self):
    # session_id → {"SPEAKER_0": "민지", "SPEAKER_1": "하니"}
    self.session_mappings: Dict[str, Dict[str, str]] = {}

  def set_mapping(self, session_id: str, mapping: Dict[str, str]) -> None:
    """화자 매핑 등록"""
    if not session_id:
      raise ValueError("sessionId가 필요합니다")

    self.session_mappings[session_id] = mapping
    logger.info(f"화자 매핑 등록: {session_id} → {mapping}")

  def get_mapping(self, session_id: str) -> Dict[str, str]:
    """화자 매핑 조회"""
    return self.session_mappings.get(session_id, {})

  def resolve(self, session_id: str, speaker_label: str) -> str:
    """화자 레이블을 이름으로 치환

    Args:
      session_id: STT 세션 ID
      speaker_label: Diart에서 반환한 레이블 (SPEAKER_0, SPEAKER_1, ...)

    Returns:
      멤버 이름 또는 원본 레이블 (미매핑 시)
    """
    mapping = self.session_mappings.get(session_id, {})
    return mapping.get(speaker_label, speaker_label)

  def clear_mapping(self, session_id: str) -> None:
    """세션 종료 시 매핑 정리"""
    if session_id in self.session_mappings:
      del self.session_mappings[session_id]
      logger.info(f"화자 매핑 삭제: {session_id}")


# 전역 인스턴스
speaker_service = SpeakerService()
