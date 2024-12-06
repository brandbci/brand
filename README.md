# Backend for Real-time Asynchronous Neural Decoding (BRAND)

## Overview
BRAND is built using a graph architecture with small, individual nodes that can be flexibly interconnected. Each node is a separate process, so as to allow for parallelization and re-prioritization of each node. Interprocess communication and data storage is all built around the [Redis](redis.io) in-memory database and caching system.

The layout of each graph is defined in its associated .yaml configuration file. Graph configuration files are organized by experimental site within modules to allow easy sharing of graphs between experimental sites while allowing per-site customization. BRAND is set up to make creation of new graphs and development of new nodes easy and consistent.

Check out [Ali et al 2024, _J Neural Eng_](https://iopscience.iop.org/article/10.1088/1741-2552/ad3b3a) for a full description of the design and validation of this software. Please cite this paper if you use BRAND in your work.

## Installation

### Requirements
* Host Machine Running Ubuntu 20.04
* Validated on PREEMPT_RT kernel version 5.15.43-rt45 [[install instructions](./doc/preempt_rt.md)]
* [Anaconda3](https://docs.conda.io/projects/conda/en/latest/user-guide/install/linux.html) for Linux

### Environment setup and Make
`bootstrap.sh` is provided to automate the environment setup. It installs debian pkg dependencies using `apt-get` and creates the real-time conda environment (rt), which is defined by `environment.yaml`. [hiredis](https://github.com/redis/hiredis) and [redis](https://github.com/antirez/redis/) have been included as submodules, which also get initialized by `bootstrap.sh`. After running bootstrap you simply need to run `make` at the project root. This will build all the project binaries including submodule dependencies. Be sure to activate the conda env before running make for Makefiles dependent on cython.

```bash
./bootstrap.sh
conda activate rt
make
```

Of note: if any of the source code is updated (for example, when developing a new node), `make` needs to be re-run for those changes to be reflected in the binaries that are run by BRAND. 

Optional `make` usages:
```bash
make graph="<path-to-graph/graph-name.yaml>" [machine="<machine-name>"] # to make nodes and derivatives relevant to a given graph yaml and optionally a specific machine
make node="<name-of-node>" [module="<module-name>"] # to make a single node instead of all nodes and derivatives and optionally specify a module
make derivative="<name-of-derivative>" [module="<module-name>"] # to make a single derivative instead of all nodes and derivatives and optionally specify a module
```

## Directory structure

BRAND follows the following directory structure (where `brand` corresponds to the main folder for this repository):

```
|---brand
    |---derivatives
    |---doc
    |---lib
        |---c
        |---python
        |---<packages>
    |---supervisor
|---brand-modules
    |---<module-name>
        |---derivatives
        |---graphs
        |---nodes
```
where `<module-name>` is the name of an external code module that extends the core BRAND code through its own nodes, graphs, and derivatives (details on this below). 

### `derivatives/`

The `derivatives` folder contains any derivative scripts. Derivatives are scripts that, when run, complete a particular operation and then exit on their own. These are useful for analysis, model, training, data export, etc. This directory's organization is:

```
|---derivatives
    |---<derivative_name>
        |---<derivative_name.EXT>
```

Presently, supported extensions are `.py` or `.bin`. Optionally, [shebangs](https://en.wikipedia.org/wiki/Shebang_(Unix)) can be used to indicate how to run the derivative if neither a `.py` or `.bin`.

### `graphs/`

The `graphs` folder contains the YAML configuration files for the graphs. This directory's organization is:

```
|---graphs
    |---<graph_name>
        |---<graph_name.yaml>
```

### `lib/`

The `lib` folder contains libraries and helper functions required for the system to work. This includes BRAND specific C or Python libraries (`c` and `python` folders) and external packages (e.g. `redis` and `hiredis`). This directory's organization is:

```
|---lib
    |---c
    |---python
    |---redis
    |---hiredis
    |---<package_name>
```

### `nodes/`

The `nodes` folder contains the code for different nodes that implement specific modular functions, each separated into its own subdirectory. Within each node subdirectory, there should be the node's source code (can be optionally organized within a `src` directory), a gnu-compatible Makefile for compiling the source code and generating the node's binary executable, and a README. Running `make` from the main BRAND directory goes thorugh all of the node subdirectories and runs the respective Makefile, which should generate the compiled executable within the same directory and have a `.bin` extension. Ensure that you follow the below directory structure for each node:

```
|---nodes
    |---<node_name>
        |---<src_code>
        |---Makefile 
        |---README.md
        |---<node_name>.bin (built after running make)
```

### `supervisor/`

This folder contains the code for the `supervisor` process, which is a core process in BRAND serving the following functions:
1. Start a Redis server
2. Load a graph and start nodes (upon receiving a "start" command)
3. Maintain an internal model with the state of the graph
    - List of nodes running and their PIDs
    - Most recent published status of each node
4. Stop graph and nodes (upon receiving a "stop" command)

### `brand-modules/`

The core BRAND directory can be extended to run additional graphs and nodes from external modules. From the core BRAND directory, external modules must be installed to a `<module-name>` folder at the following path relative to the main BRAND directory:  

```
../brand-modules/<module-name>/
```

Within each module, the directory structure is the following: 

```
|---<module-name>
    |---derivatives
    |---nodes
    |---graphs
```

where `derivatives/`, `nodes/`, and `graphs/` follow the same guidelines as the core BRAND directory. Of note: running `make` within the core directory will also go through the node Makefiles and rebuild the binary executables within all external module directories.  

## Graph YAML files

The configuration for a graph, that is, which nodes to run and using which parameters, is specified thorugh a graph YAML file. At a minimum, a graph YAML file should include a list of all nodes to run with their names, (unique) nicknames, relative path from core BRAND directory to module directory, and parameter list. Optionally, the graph YAML can also include the run priority for nodes and ID of the machine on which to run the node.
```yaml
nodes:
  - name:         <node1_name>
    nickname:     <unique_nickname>
    module:       <path_to_module>
    run_priority: <run_priority>            # optional
    machine:      <machine_id>              # optional
    parameters:
      <parameter1_name>: <parameter1_value>
      <parameter2_name>: <parameter2_value>
      ...
  - name:         <node2_name>
    nickname:     <unique_nickname>
    module:       <path_to_module>
    run_priority: <run_priority>            # optional
    machine:      <machine_id>              # optional
    parameters:
      <parameter1_name>: <parameter1_value>
      <parameter2_name>: <parameter2_value>
      ...
  ...
derivatives:
  - name:         <derivative_1_name>       # including file extension
    nickname:     <unique_nickname>
    module:       <path_to_module>
    run_priority: <run_priority>            # optional
    machine:      <machine_id>              # optional
    autorun_step: <autorun_step>            # optional
    parameters:
      <parameter1_name>: <parameter1_value>
      <parameter2_name>: <parameter2_value>
      ...
  - full_path:    <full_path_to_derivative_2>
    nickname:     <unique_nickname>
    parameters:
      <parameter1_name>: <parameter1_value>
      <parameter2_name>: <parameter2_value>
      ...
  ...
```

Nodes and derivatives have the following required parameters:
* `name`: Indicates the name of the node or derivative.
* `nickname`: Indicates the unique nickname of the node or derivative, and must be unique across all nodes and derivatives in the graph.
* `module`: Indicates the module in which the node or derivative is located.

Nodes and derivatives have the following optional parameters:
* `run_priority`: The process priority to be given to the node or derivative. Defaults to standard priority.
* `cpu_affinity`: The specific CPU "core" or list of cores (i.e. 4-5) to be given to the process. Defaults to using the operating system scheduler to assign CPU affinity.
* `machine`: The machine on which to run the node or derivative. Defaults to being run on the machine running `supervisor`.

Derivatives have the following additional optional parameters:
* `autorun_step`: Indicates the step in which to run this derivative if the `do_derivatives` `stopGraph` option is set to `1`. Derivatives with the same step number will be run in parallel. Steps will be run in increasing order and wait until all derivatives in the step are completed until proceeding to the next step. Derivatives given step `-1` will be started at the beginning and allowed to run independently of all other steps.
* `full_path`: Indicates the full path to the derivative and can replace both the required `name` and `module` parameters.

## Session workflow

After having installed and compiled the node executables, the following commands must be run to start the BRAND system:

```bash
source setup.sh
supervisor [args]
```
 - `setup.sh` is a script that defines a series of helper functions that make the workflow easier. It also sets the conda environment. 
 - `supervisor` is the core process controlling the BRAND system.

Optionally, you can include arguments when running the `supervisor` to override its defaults. Below are the extra arguments that can be used:

```
usage: supervisor.py [-h] [-g GRAPH] [-i HOST] [-p PORT] [-s SOCKET] [-c CFG] [-m MACHINE] [-r REDIS_PRIORITY] [-a REDIS_AFFINITY] [-l LOG_LEVEL] [-d DATA_DIR]

optional arguments:
  -h, --help            show this help message and exit
  -g GRAPH, --graph GRAPH
                        path to graph file
  -i HOST, --host HOST  ip address to bind redis server to
  -p PORT, --port PORT  port to bind redis server to
  -s SOCKET, --socket SOCKET
                        unix socket to bind redis server to
  -c CFG, --cfg CFG     cfg file for redis server
  -m MACHINE, --machine MACHINE
                        machine on which this supervisor is running
  -r REDIS_PRIORITY, --redis-priority REDIS_PRIORITY
                        priority to use for the redis server
  -a REDIS_AFFINITY, --redis-affinity REDIS_AFFINITY
                        cpu affinity to use for the redis server
  -l LOG_LEVEL, --log-level LOG_LEVEL
                        supervisor logging level
  -d DATA_DIR, --data-dir DATA_DIR
                        root data directory for supervisor's save path
```

### Using the `supervisor`

1. Start the `supervisor` process by running the following command:
    ```bash
    supervisor [args]
    ```
    Example usage:
    ```bash
    supervisor -i 192.168.30.6 --port 6379
    ```
    Only one `supervisor` instance can run with a given `redis-server` instance. For [multi-machine graphs](#multi-machine-graphs), use `booter` instances to interface with the `supervisor`'s `redis-server` instance.

2. Once the `supervisor` is running, it must receive a `startGraph` command through Redis to its `supervisor_ipstream` to start a graph. An example way to do this (which we suggest for testing) is to use `redis-cli`. You would have to open a separate terminal and first run the following command to open `redis-cli` (`-h` and `-p` flags are optional if you're running on default host/IP and port):
    ```bash
    redis-cli -h <host> -p <port>
    ```
    And you can then send the `startGraph`, providing the path to the graph YAML file to run: 
    ```bash
    XADD supervisor_ipstream * commands startGraph file <path_to_the_graph_yaml_file>
    ```
    The `supervisor` will log a series of outputs following this command as it goes thorugh the graph YAML file, checks for node executable binaries, and starts the nodes. All nodes from the graph YAML will be running after this.

3. To stop the graph, use the following Redis command (using `redis-cli` or other Redis interface):
    ```bash
    XADD supervisor_ipstream * commands stopGraph
    ```

At this time, `supervisor` can only execute one graph at a time. Check back in a future version of BRAND that will support running multiple graphs simultaneously.

### Supported `supervisor` commands

Commands can be sent to the `supervisor` through Redis using the following syntax: `XADD supervisor_ipstream * commands <command_name> [<arg_key> <arg_value>]`. The following commands are currently implemented:

* `loadGraph [file <path_to_file>] [graph <graph_json>]`: Load graph from YAML file path or from JSON string.
* `startGraph [file <path_to_file>] [graph <graph_json>]`: Start graph from YAML file path or from JSON string. If `file` nor `graph` are provided, it runs the previously loaded graph.
* `updateParameters [<nickname> '{"<parameter_name>":"<parameter_value>", ...}' ...]`: Updates the supergraph with specified parameter values for specified nodes. This can be executed anytime after having loaded a graph.
* `stopGraph [do_save <bool> do_derivatives <bool>]`: Stop graph, by stopping the processes for each running node.
* `stopChildProcess [nickname <nickname> process_type <node_or_derivative>]`: Stop a single child process (node or derivative).
* `saveRdb`: Dumps the database to disk as a `.rdb` file.
* `flushRedis`: **USE WITH CAUTION** Flushes the database.
* `setDataDir [path <path_to_data_directory>]`: Sets the root directory for storing data (i.e. from `saveRdb` commands).
* `setRdbFilename [filename <filename>]`: Sets the database's filename.
* `killAutorunDerivatives`: Kills all derivatives configured to automatically run after the graph ends, if enabled.
* `runDerivatives derivatives <comma-separated-nickname-list>`: Runs the derivatives in the comma-separated list of derivative nicknames a single time. This same command can be called with `runDerivative` or the key `derivative`.
* `killDerivatives derivatives <comma-separated-nickname-list>`: Kills the derivatives in the comma-separated list of derivative nicknames. This same command can be called with `killDerivative` or the key `derivative`.
* `make`: Makes binaries on the `supervisor` and `booter` machines. All `make` [specifications](#environment-setup-and-make) work with this command. There must not be a running graph to execute the `make` command.
* `setDerivativeContinueOnError continue_on_error <0/1>`: Sets the autorun derivative option whether to continue running derivative steps after one failed (defaults to `1` on boot).

### Redis streams used with the `supervisor`

* `supervisor_ipstream`: This stream is used to publish commands for the supervisor.
* `graph_status`: This stream is used to publish the status of the current graph.
* `supergraph_stream`: This stream is used to publish the metadata of the graph. Each entry should contain the key `data` and the value is a JSON string representing the supergraph.
* `supervisor_status`: This stream is used by the `supervisor` to publish its status outside of graph functionality. Any caught exceptions that are not BRAND exceptions are logged here.
* `booter_status`: This stream is used by all `booter` nodes to publish their general statuses. Each entry should contain `machine` and `status` keys.
* `<node_nickname>_state`: This set of streams are used to publish the status of nodes.
* `<data_stream>`: These are arbitrary data streams through which nodes publish their data to Redis. There are currently no naming conventions for these streams nor any rules as to how many data streams a node can publish. 

The above streams can be checked using Redis stream commands (e.g. `XREVRANGE`, `XREAD`). For example, to check the current graph published in the form of a master dictionary, you can use the following Redis command (using `redis-cli` or other Redis interface):
```bash
XREVRANGE supergraph_stream + - COUNT 1
```

### Supergraph Structure

After loading a graph with a `startGraph` command to `supervisor`, `supervisor` publishes a supergraph to the `supergraph_stream` stream. The supergraph contains all node information and the parameters set for each node. Each entry to the `supergraph_stream` contains a supergraph of the following form in a JSON string:

```json
{
    "redis_host": <redis host>,
    "redis_port": <redis port>,
    "graph_name": <graph name>,
    "graph_loaded_ts": <timestamp upon startGraph in nanoseconds>,
    "nodes": {
        "<node 1 nickname>": {
            "name": <node 1 name>,
            "nickname": <node 1 nickname>,
            "module": <node 1's source module as a relative path to the BRAND root directory>,
            "binary": <full path to node 1's binary>,
            "run_priority": <optional, node 1's realtime priority>,
            "cpu_affinity": <optional, node 1's CPU affinity>,
            "parameters": {
                "<parameter 1 name>": <parameter 1 value>,
                "<parameter 2 name>": <parameter 2 value>,
                ...
            }
        },
        "<node 2 nickname>": {
            "name": <node 2 name>,
            "nickname": <node 2 nickname>,
            "module": <node 2's source module as a relative path to the BRAND root directory>,
            "binary": <full path to node 2's binary>,
            "run_priority": <optional, node 2's realtime priority>,
            "cpu_affinity": <optional, node 2's CPU affinity>,
            "parameters": {
                "<parameter 1 name>": <parameter 1 value>,
                "<parameter 2 name>": <parameter 2 value>,
                ...
            }
        },
        ...
    },
    "derivatives": {
        "<derivative 1 nickname>": {
            "name": <derivative 1 name including extension>,
            "nickname": <derivative 1 nickname>,
            "module": <derivative 1's source module as a relative path to the BRAND root directory>,
            "machine": <optional machine on which to run derivative 1>,
            "autorun_step": <optional step in which to run derivative 1 during the autorun stage after stopping a graph>,
            "filepath": <path to file as a relative path to supervisor's working directory>,
            "parameters": <dictionary of derivative 2's parameters>
        },
        "<derivative 2 nickname>": {
            "full_path": <full path to derivative 2>,
            "nickname": <derivative 2 nickname>,
            "filepath": <path to file as a relative path to supervisor's working directory,
            "parameters": <dictionary of derivative 2's parameters>
        }
        ...
    }
}
```

Note the presence of derivatives in the graph YAML file and the supergraph is optional. The structure of a derivative's information should be defined in the derivative's documentation. Derivatives are a new feature to BRAND, so check back in the future for more documentation and functionality.

### Checking a graph's status

The following are the status codes that are published on the `graph_status` stream:
* `initialized`: Graph is initialized.
* `parsing`: Graph is being parsed for nodes and parameters.
* `graph failed`: Graph failed to initialize due to some error.
* `running`: Graph is parsed and running.
* `published`: Graph is published on `supergraph_stream` as a master dictionary.
* `stopped/not initialized`: Graph is stopped or not initialized.

You can check the status of the graph using the following Redis command (using `redis-cli` or other Redis interface):
```bash
XREVRANGE graph_status + - COUNT 1
```

#### *More details about the `graph failed` status:*

In the event of a `graph failed` status, the stream entry will also contain `message` and `traceback` keys. The `message` key contains the error message printed to the `supervisor` console log. The `traceback` key contains the exception's full traceback, including the traceback from an exception that occurred on a `booter` machine (see [Multi-machine graphs](#multi-machine-graphs) section below). See more about the types of BRAND exceptions in the [BRAND Exceptions](#brand-exceptions) section below.

## Multi-machine graphs

BRAND is capable of running nodes on several machines using the same graph. To run multi-machine graphs, you must start a `supervisor` process on the host machine that will contain your `redis-server` and a `booter` process on every client machine that will be involved in node execution.

`booter` is similar to `supervisor` except it does not start its own `redis-server`. Here are its command-line arguments:
```
usage: booter [-h] -m MACHINE [-i HOST] [-p PORT] [-l LOG_LEVEL]

optional arguments:
  -h, --help            show this help message and exit
  -m MACHINE, --machine MACHINE
                        machine on which this booter is running
  -i HOST, --host HOST  ip address of the redis server (default: 127.0.0.1)
  -p PORT, --port PORT  port of the redis server (default: 6379)
  -l LOG_LEVEL, --log-level LOG_LEVEL
                        Configure the logging level
```
To support multi-machine graphs, use the `--machine` (or `-m`) flag to assign a name for each machine when starting `supervisor` or `booter`. When `--machine` is given, `supervisor` only runs the nodes that specify the same `machine` in the graph YAML. For compatibility with single-machine graphs, `supervisor` also runs all nodes that do not provide a `machine` name in the graph YAML.

Here's an example YAML entry for a node that will run on a machine named "brand":

```yaml
nodes:
  - name:         func_generator
    nickname:     func_generator
    module:       ../brand-modules/brand-test
    run_priority: 99
    machine:      brand  # this node will run on the machine named 'brand'
    parameters:
      sample_rate:        1000
      n_features:         96
      n_targets:          2
      log:                INFO 
```

How to run a multi-machine graph (e.g. [testBooter.yaml](./graphs/testGraph/testBooter.yaml)):
1. Load the new `supervisor` and `booter` aliases.
    ```bash
    source setup.sh
    ```
2. Start `supervisor`. In this example, the host machine's local IP address is `192.168.1.101`.
    ```bash
    supervisor -m brand -i 192.168.1.101
    ```
3. Then, log into each client machine, and start a `booter` process, using a unique name for each machine. We will use one client machine called "gpc":
    ```bash
    booter -m gpc -i 192.168.1.101  # name this machine 'gpc'
    ```
4. Enter the `redis-cli`:
    ```bash
    redis-cli -h 192.168.1.101
    ```
5. Start a graph (in the `redis-cli`):
    ```bash
    XADD supervisor_ipstream * commands startGraph file graphs/testGraph/testBooter.yaml
    ```
6. Stop the graph (in the `redis-cli`):
    ```bash
    XADD supervisor_ipstream * commands stopGraph
    ```
If everything is working correctly, you should see that the `func_generator` node ran on the "brand" machine, and the `decoder` node ran on the "gpc" machine.

## BRAND exceptions

`supervisor` and `booter` are designed to run continuously, so they will catch almost any exception, log a hopefully helpful message to the console, and log the same message to a Redis stream along with a traceback. There are four BRAND-specific exceptions that `supervisor` and `booter` handle in controlled ways.

### `GraphError`

`GraphError`s are thrown if there are issues finding a graph, parsing its structure, or failing to begin parsing the graph for other reasons. `GraphError` exceptions are caught by:

1. Adding a `graph failed` entry to the `graph_status` stream (see [graph failed](#more-details-about-the-graph-failed-status) section above)
1. Rewriting the `graph_status` to what it was before the exception if another graph was already running or writing a `stopped/not initialized` status if not
1. Logging the error in the console

### `NodeError`

`NodeError`s are thrown if there are issues finding a node's executable, the node's instantiation is incomplete, there are repeated nicknames, or the node fails to initialize. `NodeError` exceptions are caught by:

1. Adding a `graph failed` entry to the `graph_status` stream (see [graph failed](#more-details-about-the-graph-failed-status) section above)
1. Killing all nodes by sending a `stopGraph` command to `supervisor_ipstream`
1. Logging the error in the console

### `BooterError`

`BooterError`s are thrown by `supervisor` if a `booter` throws any BRAND exception and are caught the same way as a [`NodeError`](#nodeerror).

### `DerivativeError`

`DerivativeError`s are thrown by `supervisor` if a derivative fails to exit gracefully. The error messages are printed and logged to the `graph_status` stream, but no other action is taken.

### `RedisError`

`RedisError`s are thrown if `supervisor` is unable to create a `redis-server` instance. `RedisError` exceptions are caught by:

1. Logging the error in the console
1. Cleanly exiting

## Redis as a mechanism for IPC

The primary mode of inter-process communication with BRAND is using Redis, focusing on [Redis streams](https://redis.io/topics/streams-intro). Briefly, Redis is an in-memory cache key-based database entry. It solves the problem of having to rapidly create, manipulate, and distribute data in memory very quickly and efficiently. 

A stream within redis has the following organization:

```bash
stream_key ID key value key value ...
```

The `ID` defaults to the millisecond timestamp of when the piece of information was collected. It has the form `MMMMMMMMM-N`, where N is a number >= 0. The idea is that if there are two entries at the same millisecond timestep, they can be uniquely identified with the N value. N begins at 0 and increments for every simultaneously created entry within the same millisecond.

When a node wants to share data with others, it does so using a stream. There are several advantages to using a stream: 

1. Data is automatically timestamped
2. Adding new data to the stream is cheap, since it's stored internally as a linked-list. 
3. It makes it easy to have a pub/sub approach to IPC, since nodes can simply call the `xread` command 
4. It makes it easy to query previously collected data using the `xrange` or `xrevrange` command. Reading new data from either the head or the tail of the stream is computationally cheap.

## Creating a new node

Nodes can be written in any language. Nodes are launched and stopped by the supervisor. Conceptually, a node should [do one thing and do it well](https://en.wikipedia.org/wiki/Unix_philosophy). Nodes are designed to be chained together in sequence. It should not be surprising if an experimental session applying real-time decoding to neural data would have on the order of 6-12 nodes running.

At a minimum, a node must:

1. Have a binary executable.
2. Parse the following command-line flags from the `supervisor`:
    * `-s`: Redis socket to bind node to.
    * `-n`: Nickname of the node.
    * `-i`: Redis server host name or IP address to bind node to.
    * `-p`: Redis server port to bind node to.
    
    A node will prioritize the socket flag over the host/port flags. Execution of a node should fail if neither `i`/`p` nor `s` flags are provided. If the node cannot connect to a Redis instance, then it should fail.
3. Load its parameters by reading from the `supergraph_stream` that contains a master JSON of the graph.
4. Have a concept of "state", which is communicated through the `<node_nickname>_state` stream in Redis. States are published to the `status` key with one of the following values.

    Nodes are required to support the following states:
    * `NODE_STARTED`: the node has been initialized.
    * `NODE_READY`: the node is in a ready state for publishing data.
    * `NODE_SHUTDOWN`: the node has shutdown.
    * `NODE_FATAL_ERROR`: the node has shutdown due to any fatal error.

    Nodes can optionally support the following states:
    * `NODE_WARNING`: the node has encountered a warning that may not cause shutdown, but could potentially produce errors during node execution or publishing data.
    * `NODE_INFO`: the node has information to share.
5. Catch `SIGINT` to publish a `NODE_SHUTDOWN` status to the `<node_nickname>_state` stream, then close gracefully.

If developing a node in Python, we suggest to implement it as a class that inherits from the `BRANDNode` class within the installed `brand` library, since it already implements the above.

### Updating Node Parameters in Python

The `BRANDNode` Python class within the `brand` library includes a helper function for updating node parameters from a new supergraph (published after calling the `supervisor`'s `updateParameters` command). The `BRANDNode.getParametersFromSupergraph` function returns a list whose length is the number of supergraphs that have been published since the node last checked for new supergraphs. Each element of the list returned by `BRANDNode.getParametersFromSupergraph` is a dictionary whose keys are the node's parameter names to be updated and values are the values for those parameters. The order of the listed supergraphs corresponds to the order of the supergraph's entries into `supergraph_stream` (i.e. the supergraph at index `0` was written before the supergraph at index `1`). The `BRANDNode.getParametersFromSupergraph` function can also return the complete supergraph as a JSON string by passing `True` to the function's optional `complete_supergraph` argument. If there are no new supergraphs, the function returns `None`.

## Performance Optimization

CPUs will scale their operating frequency according to load, which makes it difficult to get predictable timing. To get around this, we'll use `cpufrequtils`:
```
sudo apt install cpufrequtils
sudo systemctl disable ondemand
sudo systemctl enable cpufrequtils
```

Setting the CPU at its maximum allowable frequency (which will still be reduced if the CPU gets too hot):
```
sudo cpufreq-set -g performance
```

Renabling CPU scaling to save power:
```
sudo cpufreq-set -g powersave
```

This was tested on Intel CPUs. The commands may be difference for CPUs from other manufacturers.

## Gotchas

### Saving data in Redis with minimal latency

By default, Redis is configured to periodically [save](https://redis.io/topics/persistence). Given that BRAND can be processing a great deal of information quickly, the background save procedures will result in significant latencies in real-time decoding.

One option is to simply remove the `save` configuration parameters in the `.conf` file. However, if Redis is terminated using SIGTERM or SIGINT, then the [default behavior of writing to disk](https://redis.io/topics/signals) does not occur. To get around this, write something like `save NNN 1` in the configuration file, where NNN is a number much bigger than how long you ever expect to run your session. This way, Redis will gracefully exit and save your data to disk.

### hiredis library

[hiredis](https://github.com/redis/hiredis) is a C library for interacting with Redis. It is excellent, but it has undocumented behavior when working with streams. Calling `xrange` or `xrevrange` will result in a `REDIS_REPLY_ARRAY`, regardless of whether the stream exists or not. Moreover, `reply->len` will always be 0, despite possibly having many returned entries. The way around this is to first call the redis command `exists`.

### Alarms and reading from file

If a process is reading from a file descriptor and an alarm goes off, there can be unforunate consequence. For instance, if SIGALRM goes off while python is reading a file, reading will be interrupted and downstream processes can crash. If a process is setting an alarm, be sure to start it right before entering its main loop (and after the handlers have been installed), after all of the relevant configuration has been set.

### Running a script with sudo privileges within the current conda environment
```
sudo -E env "PATH=$PATH" ./myscript
```

### Removing headers from UDP packet capture
Dependencies: [tshark](https://packages.ubuntu.com/bionic/tshark), [bittwist](https://packages.ubuntu.com/bionic/bittwist)   

If you have `.pcapng` files, convert them to `.pcap`:
```
tshark -F pcap -r mypackets.pcapng -w mypackets.pcap
```
Use Wireshark to check the size of the header. In our case, the header is the first 42 bytes in each packet, so we run:
```
bittwiste -I mypackets.pcap -O mypackets_no_headers.pcap -D 1-42
```
Now `mypackets_no_headers.pcap` is a copy of our `mypackets.pcap` file with headers removed.




