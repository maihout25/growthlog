"""A small login throttle for PythonAnywhere's single free web worker."""

from collections import deque
from threading import Lock
from time import monotonic


class LoginThrottle:
    def __init__(self):
        self.by_username = {}
        self.recent = deque()
        self.lock = Lock()

    def allow(self, username):
        """Allow eight attempts per username per 15 minutes, 30 total per minute."""
        now = monotonic()
        # Usernames are case insensitive. Bound the key length for invalid input.
        key = username.strip().lower()[:40]
        with self.lock:
            while self.recent and self.recent[0] <= now - 60:
                self.recent.popleft()
            for name in list(self.by_username):
                attempts = self.by_username[name]
                while attempts and attempts[0] <= now - 900:
                    attempts.popleft()
                if not attempts:
                    del self.by_username[name]
            attempts = self.by_username.get(key, deque())
            if len(self.recent) >= 30 or len(attempts) >= 8:
                return False
            self.recent.append(now)
            attempts.append(now)
            self.by_username[key] = attempts
            return True
