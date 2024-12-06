import logging
import numpy as np
import redis


def xread_count(r, stream, count, startid=0, block=None) -> list:
    """
    Block and read multiple entries from a single stream

    Parameters
    ----------
    r : redis.Redis
        instance of the redis.Redis interface
    stream : bytes
        Name of the stream
    count : int
        Number of items to return
    startid : int
        The starting ID to be used for XREAD. This ID indicates the last ID
        already seen.
    block : int, optional
        Number of milliseconds to wait in each XREAD call, by default None
    Returns
    -------
    out : list
        List of entries for each stream
    """
    entry_id = startid
    n_samples = count

    # Initialize the output
    stream_entries = [None] * n_samples
    out = [[stream, stream_entries]]
    # Read from the stream
    while count > 0:
        all_streams = r.xread({stream: entry_id}, count=count, block=block)
        if len(all_streams) > 0:
            stream_entries = all_streams[0][1]
            for entry in stream_entries:
                out[0][1][n_samples - count] = entry
                entry_id = entry[0]
                count -= 1
    return out


def xread_sync(self,
               streams,
               sync_field,
               sync_dtype='uint32',
               count=1,
               block=None) -> list:
    """
    Read and sync entries from multiple streams

    Parameters
    ----------
    streams : bytes
        dict of stream names to stream IDs, where IDs indicate the last ID
        already seen.
    sync_field : bytes
        Field in each stream containing a value that should match in the
        synchronized data
    count : int
        Number of items to return
    block : int, optional
        Number of milliseconds to wait in each XREAD call, by default None
    Returns
    -------
    out : list
        List of entries for each stream
    """
    # Data type of the sync field
    dtype = np.dtype(sync_dtype)

    # stream names and entry IDs
    stream_names, entry_ids = zip(*streams.items())
    entry_ids = list(entry_ids)

    # Number of streams
    n_streams = len(stream_names)
    # Data from each stream
    entry_data = [None] * n_streams
    # Starting timestamps of each stream's entry. Used for synchronization.
    t0 = np.zeros(n_streams, dtype=dtype)

    # Initialize the synchronized output
    out = [[name, [None] * count] for name in stream_names]

    for i_c in range(count):
        # Block for entries from multiple streams at once. Return when all
        # streams have new values.
        p = self.pipeline(transaction=False)
        for i_s in range(n_streams):
            p.xread({stream_names[i_s]: entry_ids[i_s]}, block=block, count=1)
        replies = p.execute()

        # Get timestamps from both streams
        for i_s in range(n_streams):
            reply = replies[i_s][0]
            entry_ids[i_s], entry_data[i_s] = reply[1][0]
            sync_val = entry_data[i_s][sync_field][:dtype.itemsize]
            t0[i_s] = np.frombuffer(sync_val, dtype=dtype)[0]

        # Synchronize the streams by reading the next entry in the lagging
        # stream until it matches the leading stream.
        while np.min(t0) < np.max(t0):
            # repeat until all timestamps match (if there are more than 2)
            i_min = np.argmin(t0)  # index of the lagging stream
            i_max = np.argmax(t0)  # index of the leading stream
            while t0[i_min] < t0[i_max]:
                # repeat until the minimum and maximum timestamps match
                replies = self.xread({stream_names[i_min]: entry_ids[i_min]},
                                     block=block,
                                     count=1)
                entry_ids[i_min], entry_data[i_min] = replies[0][1][0]
                sync_val = entry_data[i_min][sync_field][:dtype.itemsize]
                t0[i_min] = np.frombuffer(sync_val, dtype=dtype)[0]

        # save the output
        for i_s in range(n_streams):
            out[i_s][1][i_c] = (entry_ids[i_s], entry_data[i_s])

    return out  # Return the synchronized output

class RedisLoggingHandler(logging.Handler):
    """
    Send `logging` messages to a particular stream in Redis. (This stream can then be
    read from and displayed in a custom GUI, for example.)
    """

    LOG_STREAM_NAME = "console_logging"

    def __init__(self, redis_conn, name):
        logging.Handler.__init__(self)

        self.redis_conn = redis_conn

        self.setFormatter(
            logging.Formatter(
                fmt=f"%(asctime)s.%(msecs)03d [{name}] %(levelname)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    def emit(self, record):
        try:
            msg = self.format(record)
            self.redis_conn.xadd(self.LOG_STREAM_NAME, {"message": msg})
        except redis.exceptions.ConnectionError:
            # If not connected to redis, that's ok, just do nothing.
            pass
        except:
            self.handleError(record)
