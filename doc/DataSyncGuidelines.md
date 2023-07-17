# Guidelines for Data Alignment in BRAND

BRAND is designed to run nodes in an asynchronous graph. To protect data integrity, we need to track flow of data through the graph. Nodes interacting with data `read` from and `add` to Redis streams. To track flow, we create a data label for every data entry to a Redis stream, and we record a global timestamp for when that data entry is queued for transfer to the Redis database.

## Data Labels

There are two types of data writes within BRAND.

1. A node introduces data to the system (i.e. from a sensor)
2. A node produces processed data that derives from some consumed data

Both of these types of interactions should use labels in a different way.

### New Data to the System

Consider a node that parses incoming information from a different system not a part of BRAND. The data coming from that system will be introduced to BRAND, where the interfacing node is the generator of a stream with data from that external system. A few examples of this are:

* The Cerebus records information from a cortical implant. A `cerebusAdapter` node is designed to read that data and introduce it to BRAND by storing it in a Redis `stream`.
* A microphone records ambient audio. A `microphoneAdapter` node is designed to read in that ambient audio and introduce it to BRAND by storing it in a Redis `stream`.
* A mouse tracks user movements. A `mouseAdapter` node is designed to read mouse inputs and introduce it to BRAND by storing it in a Redis `stream`.
* In a more abstract case: a function generator node records the passage of time and generates some waverform as a function of time. A `functionGenerator` node is built to store this waveform in a Redis `stream`.

The node that introduces data to BRAND must include a label for that data within the data's entry. Logically this can take any form, but for logging purposes it often helps if this is some clock. Within the entry, there should be a key named `sync`. This label should take the form:

```
{'sync':{<label_name>:<label>}}
```

or more specifically for `cerebusAdapter`:

```
{'sync':{'nsp1_clock':<clk_val>}}
```

### Processed Data that Derives from Existing Data

Consider a node that consumes data from one or more streams (meaning the data has already been introduced to the system). To track flow of the data through the system, a node must output the labels of the entries it used to compute the output. This should be a nested dictionary entry looking like

```
{'sync':{<label_1_name>:<label_1>, <label_2_name>:<label_2>, ...}}
```

or more specifically for a node that may combine a `cerebusAdapter` output stream with a `mouseAdapter` stream, the `sync` key would look like:

```
{'sync':{'nsp1_clock':<clk_1_val>, 'mouse_clock':<clk_mouse_val>}}
```

This way, how data introduced to the BRAND system is processed through the graph can always be traced.

Due to the asynchronous nature of BRAND, each node must wait for one or more new stream entries before it may run its computations. In other words, the node must be blocked from execution until sufficient samples have been acquired. Since different streams need not have the same entry rates, only one stream should be used to block each node. It is up to the node's developer to decide which is being used to block. However, in all cases, it is *strongly recommended* that the higher time-resolution stream should be used for blocking, but the most recent label for all input streams should be included in the label key.

## Global Timestamps

In addition to tracking data flow through a graph, it is also important to track latencies of computations as the data flows through the graph. To do this, each node must also include an entry in each of its streams stating an accurate and precise measure of system time. For now, this entry should derive from the Linux [`monotonic_clock_ns`](https://linux.die.net/man/3/clock_gettime). The nanosecond monotonic clock time should be stored in each stream entry as an unsigned 64-bit integer encoded to bytes. The timing key within the output stream will look like:
```
{<time_key>:<monotonic_ns_time_value>}
```
Note that this feature only works if the BRAND system is on one computer, so a distributed solution will be introduced in the future. 
