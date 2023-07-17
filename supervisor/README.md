# Supervisor
> Supervisor is a core process in BRAND serving the following functions - 
1. Boots nodes
    - Boots up a single graph with all the nodes and supervisor maintains PIDs of each independently running nodes.
2. Kills nodes
    - Receives command to stop all nodes.
3. Maintain internal model of the state of the graph
    - List of nodes running and their PIDs.
    - Most recent published status of each node.

## Execution
```
$ python supervisor/supervisor.py -g <name_of_the_graph_yaml_file>
```
Can also be run without defining a graph file on start:
```
$ python supervisor/supervisor.py
```
## BRAND convention for graph yaml files
- `graph.yaml`: The graph yaml file should specify the following parameters and it's mandatory otherwise the program will not run:
    - `module`: This refers to the site module that the graph is to be run in.
    - `node name`: This refers node name within the module.
    - `version_name`: This refers to the version of the node.

## Graph/Nodes modules Directory structure
> All internal graphs are required to follow the below mentioned directory structure
```
    |---<nodes>
        |
        |---<nodename>
            |
            |---README.md
            |---src
                |---<Headerfiles>
                |---<nodename>.c
                |---<nodename>.cpp
                |---<nodename>.m
                |---<nodename>.py
            |---<nodename>.bin
            |---<nodename>.out
            |---Makefile 
    |
    |
    |---<graphs>
        |---module_name
            |
            |---<graphname.yaml>
            |---<graphname.pptx>
```


## External modules Directory structure
> All modules are required to follow the below mentioned directory structure

```
---<brand-modules>
    |
    |---<module-name>
        |
        |---<nodes>
            |
            |---<nodename>
                |
                |---README.md
                |---src
                    |---<Headerfiles>
                    |---<module-name>_nodename.c
                    |---<module-name>_nodename.cpp
                    |---<module-name>_nodename.m
                    |---<module-name>_nodename.py
                |---<module-name>_nodename.bin
                |---<module-name>_nodename.out
                |---Makefile   
        |
        |---<graphs>
            |
            |---<graphname.yaml>
            |---<graphname.pptx>
```

## Utilities structure
> All utilities used in brand are required to follow the below mentioned directory structure

```
    |---<lib>
    |
    |---<nodes>
            |
            |---<language-utilies(c/python/m/cpp)>
    |---<packages>
            |
            |---<Core packages like hiredis/json which can be used by other modules>
    |---<supervisor_utility>
            |
            |---<README.md>
            |---<requirements.txt>
            |---<supervisor.py> 
```



## Graph 


## Working logic of the supervisor
```
1. Parses the command line arguments for a valid graph yaml file.
2. Reads the graph yaml file and creates a graph dictionary.
3. A redis instance is created based on the host and port specified in the graph yaml file and the redis instance is connected to the redis server. 
4. The model is published on a redis stream.
5. A redis listener is created to listen to the stream and when a message is received either for startGraph or stopGraph, the message is parsed and the corresponding command is executed.
6. If the command is startGraph, the node is Steps 1-5 are repeated for each node in the graph and each node runs as independent child processes.
7. If the command is stopGraph, all the child processes are killed and the graph is stopped.
```


## Execution of the supervisor
```
Follow the below instructions and commands for running supervisor utility:

1. Start the supervisor by running either of the following commands:
```    
        $ python3 supervisor/supervisor.py -g <name_of_the_graph_yaml_file>
        $ run -g <name_of_the_graph_yaml_file> 
```
 >Optionally, you can also use extra arguments with the supervisor utility. Below are the extra arguments that can be used:
 - `-g` / `--graph` : Name of the graph yaml file.
 - `-i` / `--ip` : IP address to bind the server node to.
 - `-p` / `--port` : Port number to bind the server node to.
 - `-c`/ `--cfg` : Name of the config file specific to redis server.
 - `-m` / `--machine` : Name of the machine on which the supervisor is running.


2. Once, the supervisor has started, you can open a separate terminal and run the following commands (-h and -p flags are optional if you're running on default host and port):
```
$ redis-cli -h <hostname> -p <port>
```
3. Inside the redis-cli, run the following commands to start the graph:
```
    $ XADD supervisor_ipstream * commands startGraph
```
4. (Optional) If you want to start the graph with a specific file, run the following command:
```
    $ XADD supervisor_ipstream * commands startGraph file       <name_of_the_graph_yaml_file>
```    
5. Now that the nodes have started, you can check the status of the graph using the following command in redis-cli:
```
    $ XREVRANGE graph_status + - COUNT 1
```

6. To check the metadata published in form of a master dictionary, run the following command in redis-cli:
```
    $ XREVRANGE supergraph_stream + - COUNT 1
```
7. To stop the graph, run the following command in redis-cli:
```
    $ XADD supervisor_ipstream * commands stopGraph
```
8. To stop the graph and save NWB export files, run the following command in redis-cli:
```
    $ XADD supervisor_ipstream * commands stopGraphAndSaveNWB
```


## Redis streams used in supervisor
1. `supergraph_stream` : This stream is used to publish the metadata of the graph.
2. `graph_status` : This stream is used to publish the status of the graph.
3. `supervisor_ipstream` : This stream is used to publish the commands to the supervisor.
4. `<node_name>_stream` : This stream is used for checking data on the <node_name> stream, where <node_name> is the name of the node.
5. `<node_name>_state` : This stream is used to publish the status of the node.

### Graph status codes on `graph_status` stream
> The following are the status codes that are published on `graph_status` stream:
```
    initialized             - Graph is initialized.
    parsing                 - Graph is being parsed for nodes and parameters.
    graph_failed            - Graph failed to initialize due to some error.
    running                 - Graph is parsed and running.
    published               - Graph is published on supergraph_stream as a master dictionary.
    stopped/not initialized - Graph is stopped or not initialized.
```


## Supervisor glossary
`parse_vargs`:
Parses the command line arguments using `argparse` module and checks if the graph yaml file has been loaded and if it's valid.he graph yaml file and returns a graph dictionary.

`search_node_yaml_file`: returns a yaml file based on module, name and version of the node.

`search_node_bin_file`: returns a binary file based on module, name and version of the node (currently has been disabled since there wasn't an executable file for the node).

`load_graph`:  comprises of the working logic behind the supervisor. Creates the model of the graph and starts the nodes after rule checking and validation.

`start_graph`: starts the graph by calling the `load_graph` function after validation of rules and types/names/value in the node parameters.
Publishes a model of the graph on the redis stream using XADD and forks parent process to create more child processes for the nodes. 

`stop_graph`: stops the graph by killing all the child processes.

`parseCommand` : parses the redis-cli commands for starting and stopping the graph.

`read_commands_from_redis`: reads the redis-cli commands from the redis stream.

## Known issues
None as of now.
