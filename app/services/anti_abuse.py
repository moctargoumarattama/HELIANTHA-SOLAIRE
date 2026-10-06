"""Small, thread-safe per-process safeguards for outbound messages and AI."""

from collections import OrderedDict, deque
from math import ceil
from threading import Lock
from time import monotonic
from typing import Callable


ASSISTANT_WAIT_MESSAGE = (
    "Vous avez beaucoup échangé avec notre conseiller solaire. "
    "Merci de patienter quelques instants avant de poursuivre votre conversation."
)


def whatsapp_phone_key(phone: str) -> str:
    """Group local Moroccan and international spellings of the same number."""
    digits = "".join(char for char in str(phone or "") if char in "0123456789")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        digits = "212" + digits[1:]
    return digits


def whatsapp_queue_key(phone: str, caption: str) -> tuple[str, str]:
    """Keep admin notifications for different clients in separate queue groups."""
    marker = "*Telephone :* "
    client = next(
        (line[len(marker):] for line in str(caption).splitlines() if line.startswith(marker)),
        "",
    )
    return whatsapp_phone_key(phone), whatsapp_phone_key(client)


class PhoneCooldown:
    def __init__(self, clock: Callable[[], float] = monotonic):
        self._clock = clock
        self._last_push: dict[str, float] = {}
        self._lock = Lock()

    def claim(self, phone: str) -> bool:
        key = whatsapp_phone_key(phone)
        if not key:
            return False
        with self._lock:
            now = self._clock()
            self._last_push = {
                key: sent_at for key, sent_at in self._last_push.items()
                if now - sent_at < 60
            }
            previous = self._last_push.get(key)
            if previous is not None and now - previous < 20:
                return False
            self._last_push[key] = now
            return True


class AssistantQuota:
    def __init__(self, clock: Callable[[], float] = monotonic):
        self._clock = clock
        self._messages: OrderedDict[str, deque[float]] = OrderedDict()
        self._last_cleanup = clock()
        self._lock = Lock()

    def retry_after(self, ip: str) -> int:
        """Consume one message, or return seconds until a slot is available."""
        with self._lock:
            now = self._clock()
            cutoff = now - 600
            if now - self._last_cleanup >= 60:
                expired = [
                    key for key, times in self._messages.items()
                    if not times or times[-1] <= cutoff
                ]
                for key in expired:
                    self._messages.pop(key)
                self._last_cleanup = now
            times = self._messages.get(ip)
            if times is None:
                if len(self._messages) >= 10000:
                    self._messages.popitem(last=False)
                times = deque()
                self._messages[ip] = times
            self._messages.move_to_end(ip)
            while times and times[0] <= cutoff:
                times.popleft()
            if len(times) >= 30:
                return max(1, ceil(times[0] + 600 - now))
            times.append(now)
            return 0
