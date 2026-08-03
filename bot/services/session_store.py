"""In-memory store mapping short tokens to pending download sessions.

Telegram inline keyboard callback_data is capped at 64 bytes, so we can't
stuff a full URL + format id into it. Instead we generate a short UUID token
per preview message, store the details here, and look them up when the user
taps a quality button.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from bot.downloaders.ytdlp_service import FormatOption, MediaInfo


@dataclass
class PendingSession:
    token: str
    url: str
    title: str
    formats: dict[str, FormatOption] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    user_id: int = 0
    chat_id: int = 0


class SessionStore:
    def __init__(self, ttl_seconds: int = 3600):
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, PendingSession] = {}

    def create(self, info: MediaInfo, user_id: int, chat_id: int) -> PendingSession:
        token = uuid.uuid4().hex[:12]
        formats_by_id = {f.format_id: f for f in info.formats}
        session = PendingSession(
            token=token,
            url=info.url,
            title=info.title,
            formats=formats_by_id,
            user_id=user_id,
            chat_id=chat_id,
        )
        self._sessions[token] = session
        return session

    def get(self, token: str) -> PendingSession | None:
        session = self._sessions.get(token)
        if session and (time.time() - session.created_at) > self.ttl_seconds:
            self._sessions.pop(token, None)
            return None
        return session

    def drop(self, token: str) -> None:
        self._sessions.pop(token, None)

    def clear_expired(self) -> int:
        now = time.time()
        expired = [t for t, s in self._sessions.items() if now - s.created_at > self.ttl_seconds]
        for t in expired:
            self._sessions.pop(t, None)
        return len(expired)
