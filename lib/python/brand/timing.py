import ctypes
import time
from ctypes import Structure, c_long, pointer
from datetime import datetime

TIMEVAL_LEN = 16  # bytes
TIMESPEC_LEN = 16  # bytes
TIMER_ABSTIME = 1

libc = ctypes.CDLL('libc.so.6')


class timespec(Structure):
    """
    timespec struct from sys/time.h
    """
    _fields_ = [("tv_sec", c_long), ("tv_nsec", c_long)]


class timeval(Structure):
    """
    timeval struct from sys/time.h
    """
    _fields_ = [("tv_sec", c_long), ("tv_usec", c_long)]


def clock_nanosleep(time_ns, clock=time.CLOCK_REALTIME):
    """
    Sleep until a specified clock time. This is a wrapper for the C
    clock_nanosleep function.

    Parameters
    ----------
    time_ns : int
        Absolute time (in nanoseconds) as measured by the `clock`.
        clock_nanosleep() suspends the execution of the calling thread until
        this time.
    clock : int, optional
        Clock against which the sleep interval is to be measured, by default
        time.CLOCK_REALTIME. Another option is time.CLOCK_MONOTONIC.

    Returns
    -------
    out : int
        Exit code for the clock_nanosleep function. A non-zero code indicates
        an error.
    """
    deadline_s = time_ns // 1_000_000_000
    deadline_ns = time_ns - (deadline_s * 1_000_000_000)
    deadline = timespec(int(deadline_s), int(deadline_ns))
    out = libc.clock_nanosleep(clock, TIMER_ABSTIME, pointer(deadline), None)
    return out


def timeval_to_datetime(val):
    """
    Convert a C timeval object to a Python datetime
    Parameters
    ----------
    val : bytes
        timeval object encoded as bytes
    Returns
    -------
    datetime
        Python datetime object
    """
    ts = timeval.from_buffer_copy(val)
    timestamp = datetime.fromtimestamp(ts.tv_sec + ts.tv_usec * 1e-6)
    return timestamp


def timeval_to_timestamp(val):
    """
    Convert a C timeval object to a timestamp
    Parameters
    ----------
    val : bytes
        timeval object encoded as bytes
    Returns
    -------
    float
        timestamp (in seconds)
    """
    ts = timeval.from_buffer_copy(val)
    timestamp = ts.tv_sec + ts.tv_usec * 1e-6
    return timestamp


def timespec_to_timestamp(val):
    """
    Convert a C timespec object to a timestamp (in seconds)
    Parameters
    ----------
    val : bytes
        timespec object encoded as bytes
    Returns
    -------
    float
        Time in seconds
    """
    ts = timespec.from_buffer_copy(val)
    timestamp = ts.tv_sec + ts.tv_nsec * 1e-9
    return timestamp


def timevals_to_timestamps(vals):
    """
    Convert a list of C timeval objects to a list of timestamps (in seconds)
    Parameters
    ----------
    vals : bytes
        timeval objects encoded as bytes
    Returns
    -------
    list
        List of timestamps in units of seconds
    """
    tlen = TIMEVAL_LEN
    n_timevals = int(len(vals) / tlen)
    ts = [
        timeval_to_timestamp(vals[i * tlen:(i + 1) * tlen])
        for i in range(n_timevals)
    ]
    return ts


def timespecs_to_timestamps(vals):
    """
    Convert a list of C timespec objects to a list of timestamps (in seconds)
    Parameters
    ----------
    vals : bytes
        timespec objects encoded as bytes
    Returns
    -------
    list
        List of timestamps in units of seconds
    """
    tlen = TIMESPEC_LEN
    n_timespecs = int(len(vals) / tlen)
    ts = [
        timespec_to_timestamp(vals[i * tlen:(i + 1) * tlen])
        for i in range(n_timespecs)
    ]
    return ts
