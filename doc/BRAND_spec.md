# BRAND requirements specification (v0.1.0)

## 1. Folder organization / Directory Structure

The directory organization should follow the below structure:

```
/brand
    /supervisor
    /libs
        /c 
        /python
        /hiredis
        /nxjson
        /redis
/brand-modules
    /<module-name> (where <module-name> = davis, emory, northwestern etc.)
        /nodes
        /graphs
        /derivatives
```

## 2. Naming conventions for files

The naming conventions for the files should follow the below conventions so as to avoid any potential pitfalls persisting in code execution
- `<nodename.extension>` for nodes.
- `<graphname.yaml>` for graphs.

## 3. Existence of files in folders with specific names

Further, the "/nodes" folder for a specific module must contain following subdirectories:
```
/nodes
    /nodename
    /src [optional]
    Makefile
    README.md (for documentation on what node is supposed to do)
    <nodename>.bin (file for execution, generated at build)
```

## 4. Structure for YAML graph files

All the graph files should follow the below structure for running the node
```
metadata:
  [...]
nodes:
  - name: <node name>
    nickname: <nickname>
    module: <module name>
    run_priority: <run priority>
    machine: <machine name>   
    cpu_affinity: <cpu affinity> [optional]
    parameters:
      <parameter_name>: <parameter_value>
```

## 5. Specification that node binary files must accept certain flags

Each node binary file should parse the following flags upon for a successful execution from supervisor: 
- `-i`: Host or IP to bind to (optional)
- `-n`: Nickname of the node
- `-p`: Port to bind to (optional)
- `-s`: Redis socket to bind (optional)

Logic for Redis connection:
- The node should always try to connect first to the Unix socket (if provided)
- If no Unix socket is provided, then use the IP/port 
- If you cannot connect to either option, then fail regardless

Nodes ignore flags they don't recognize.

## 6. Binary files must have a concept of a “state” which is communicated through Redis

Each node must specify its current state to a corresponding Redis stream: `<nickname>_state`. The node status must be included as the key, and the following states are allowed:
- Required:
  - `NODE_STARTED`: node has been initialized.
  - `NODE_READY`: node is in a ready state for publishing data.
  - `NODE_SHUTDOWN`: shutdown state
  - `NODE_FATAL_ERROR`: node shuts down because of a fatal error
- Optional:
  - `NODE_WARNING`: any kind of warning that might not cause a node to shutdown but could potentially produce errors in execution of node or publishing data.
  - `NODE_INFO`: Info about a node (in brief)
 
## 7. Binary files must shut-down cleanly with SIGINT 

The following procedure must be ensured by node execution to shutdown without any fatal crashes: 
1. Emit a status for `NODE_SHUTDOWN` on the `<nickname>_state` stream.
2. Node shutdown (in case of C code, make sure to free memory).

## 8. IPC through Redis streams

(no specification in current version)

## 9. The supervisor and booter

Supervisor runs as a daemon process in BRAND for booting nodes, killing nodes and maintaining the internal model of the state of a graph with the PIDs and most recent published status of each node. 

Booter is a daemon that starts and stops nodes according to commands sent by supervisor from any machine. 

To boot nodes on multiple machines, use a booter. 

Supervisor acts as a host machine and booter runs as a client machine to execute nodes

The `<machine>` parameter must be included in multi-machine graph yaml files to indicate which machine the node is being run on.

Inclusion of –machine / -m flag for supervisor and booter:
- `supervisor -m <name> -i <ip_host> -p <port> -s <socket>`
- `booter -m <name> -i <ip_host> -p <port>` 

## 10. All nodes receive their parameters by reading from a well-known stream that contains a master JSON (supergraph_stream) for each node to interpret

Since we are using Redis streams for interprocess communication, the following standard conventions for naming Redis streams are used:
 - `supervisor_ipstream` for running supervisor commands, e.g. startGraph, stopGraph, etc.
 - `supergraph_stream` for checking the master JSON dictionary for nodes and their parameters.

## 11. Concept of derivative

A derivative is code that is run offline, based initially on an .rdb file.

The derivatives live in specific folder, and can be thought of as “analysis modules”.

Examples of derivatives include:
- Code that produces plots of latencies of various nodes in the system
- Code that exports .nwb files based on .rdb files

## 12. Supervisor commands

A command is code that is designed to be run ONLINE, based on functions specified within supervisor.

Examples of supervisor commands include:
-  Code to start graphs
-  Code to stop graphs
-  Code to update graphs

