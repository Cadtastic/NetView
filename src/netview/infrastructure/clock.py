"""Wall-clock implementation of the Clock port."""

import time


class SystemClock:
    def now_ms(self) -> int:
        return int(time.time() * 1000)
