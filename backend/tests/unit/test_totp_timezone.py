"""
TOTP counter arithmetic across timezones — finding D7.

`verify_totp_code` passed pyotp a FLOAT (`now.timestamp() + offset * interval`).
Reading pyotp:

    def at(self, for_time, counter_offset=0):
        if not isinstance(for_time, datetime.datetime):
            for_time = datetime.datetime.fromtimestamp(int(for_time))   # NAIVE LOCAL
        return self.generate_otp(self.timecode(for_time) + counter_offset)

    def timecode(self, for_time):
        if for_time.tzinfo:
            return int(calendar.timegm(for_time.utctimetuple()) / self.interval)
        else:
            return int(time.mktime(for_time.timetuple()) / self.interval)   # LOCAL

So a float became a naive local datetime and took the `time.mktime` branch,
which interprets a wall-clock struct as LOCAL time.

⚠️ THIS IS WHY THE BUG IS INVISIBLE HERE. On a machine at a fixed UTC offset the
round trip is self-consistent and the counter is right — Karachi is UTC+5 with
no daylight saving, and CI runs in UTC. It breaks only across a DST transition,
where `mktime` is ambiguous: the counter jumps by 3600/interval steps and every
valid code is rejected for an hour, twice a year, in some deployments and not
others.

A test asserting the counter VALUE therefore cannot fail on this machine, so it
would prove nothing. These assert the mechanism instead: pyotp must be handed an
AWARE datetime, which takes the `calendar.timegm` branch and has no local-time
step to be ambiguous about.
"""

import calendar
from datetime import UTC, datetime, timedelta, timezone

import pyotp
import pytest

from app.auth.totp import generate_totp_secret, verify_totp_code


@pytest.fixture
def captured_for_time(monkeypatch):
    """Record every `for_time` pyotp is asked to verify against."""
    seen: list[object] = []
    original = pyotp.TOTP.verify

    def spy(self, otp, for_time=None, valid_window=0):
        seen.append(for_time)
        return original(self, otp, for_time=for_time, valid_window=valid_window)

    monkeypatch.setattr(pyotp.TOTP, "verify", spy)
    return seen


class TestPyotpIsHandedAnAwareDatetime:
    def test_every_probe_is_timezone_aware(self, captured_for_time):
        """
        ⚠️ THE ASSERTION THAT FAILS ON THE OLD CODE. A float, or a naive
        datetime, sends pyotp down the `time.mktime` path.
        """
        secret = generate_totp_secret()
        now = datetime.now(UTC)
        verify_totp_code(secret, "000000", now=now)

        assert captured_for_time, "pyotp.verify was never called"
        for probe in captured_for_time:
            assert isinstance(probe, datetime), f"pyotp got {type(probe).__name__}, not a datetime"
            assert probe.tzinfo is not None, (
                "pyotp got a NAIVE datetime, so timecode() takes the local-time "
                "mktime branch -- finding D7"
            )

    def test_the_three_probes_are_one_interval_apart(self, captured_for_time):
        """The +/-1 step tolerance, expressed in time rather than in epoch maths."""
        secret = generate_totp_secret()
        now = datetime.now(UTC)
        verify_totp_code(secret, "000000", now=now)

        interval = pyotp.TOTP(secret).interval
        offsets = sorted((p - now).total_seconds() for p in captured_for_time)
        assert offsets == [-interval, 0, interval]


class TestTheCounterIsUtcRegardlessOfLocalTime:
    @pytest.mark.parametrize(
        "tz",
        [
            UTC,
            timezone(timedelta(hours=5)),  # Asia/Karachi — the deployment target
            timezone(timedelta(hours=-8)),  # a DST-observing offset, in winter
            timezone(timedelta(hours=-7)),  # the same zone, in summer
            timezone(timedelta(hours=13)),  # past the date line
        ],
    )
    def test_the_accepted_counter_is_the_utc_counter(self, tz):
        """
        A correct code must be accepted, and the counter recorded for the replay
        guard must be the UTC one, whatever offset the caller's clock carries.

        ⚠️ THE COUNTER IS THE POINT, NOT JUST ACCEPTANCE. It is stored as
        `last_used_counter` and every later code is rejected if its counter is
        not greater. A counter derived through local time would be an hour of
        steps away from the one the next verification computes, so a DST shift
        would either lock the user out or silently reopen the replay window.
        """
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret)
        moment = datetime.now(tz)

        counter = verify_totp_code(secret, totp.at(moment), now=moment)

        assert counter is not None, "a code generated for this instant was rejected"
        assert counter == calendar.timegm(moment.utctimetuple()) // totp.interval

    def test_the_same_instant_gives_the_same_counter_in_every_zone(self):
        """
        One instant, five clocks. The counter must not depend on which of them
        reported it — that is what "UTC-based" means, and it is exactly what
        `time.mktime` does not guarantee.
        """
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret)
        instant = datetime.now(UTC)

        counters = {
            verify_totp_code(secret, totp.at(instant), now=instant.astimezone(tz))
            for tz in (UTC, timezone(timedelta(hours=5)), timezone(timedelta(hours=-8)))
        }

        assert len(counters) == 1, f"the counter varied by the caller's zone: {counters}"
        assert None not in counters
