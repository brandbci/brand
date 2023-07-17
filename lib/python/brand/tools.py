import redis
import yaml
import argparse

# -----------------------------------------------------------
def get_parameter_value(yaml_path, field):
    """
    Get the parameter specified by 'field' from a file

    Parameters
    ----------
    yaml_path : str
        Path of the YAML file
    field : str
        Name of the parameter to be loaded

    Returns
    -------
    object
        Value of the parameter
    """
    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f)

    for record in yamlData['parameters']:
        if record['name'] == field:
            return record['value']


# -----------------------------------------------------------
def get_node_parameter_value(yaml_path, node, field):
    """
    Get the parameter specified by 'field' from the 'node' in a file

    Parameters
    ----------
    yaml_path : str
        Path of the YAML file
    node : str
        Name of the node to use
    field : str
        Name of the parameter to be loaded

    Returns
    -------
    object
        Value of the parameter
    """
    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f)

    for node_list in yamlData['Nodes']:
        if node_list['Name'].split('.')[0] == node:
            return node_list['Parameters'][field]


# -----------------------------------------------------------
def get_node_parameter_dump(yaml_path, node):
    """
    Get all parameters the 'node' in a file

    Parameters
    ----------
    yaml_path : str
        Path of the YAML file
    node : str
        Name of the node to use

    Returns
    -------
    dict
        All parameters in "parameter" section
        for given node
    """
    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f) # load the parameters file

        if node is not None:        # if we got a node name, return its parameters
            for node_list in yamlData['Nodes']:
                if node_list['Name'].split('.')[0] == node:
                    return node_list['Parameters']
        else:                       # otherwise, return the full "nodes" dictionary
            return yamlData['Nodes']


# -----------------------------------------------------------
def initializeRedisFromYAML(yaml_path, processName=None):
    """
    Create a redis.Redis object according to the configuration in a YAML file

    Parameters
    ----------
    yaml_path : str
        Path of the YAML file
    processName : str, optional
        Name of the process that is calling this function, by default None

    Returns
    -------
    redis.Redis
        Instance of the redis.Redis class
    """
    pname = f"[{processName}] " if processName is not None else ""
    print(f"{pname}connecting to Redis using: {yaml_path}")

    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f)

    redis_params = yamlData['RedisConnection']
    # connect to redis, figure out the streams of interest
    if ('redis_realtime_socket' in redis_params
            and redis_params['redis_realtime_socket'] is not None):
        redis_socket = redis_params['redis_realtime_socket']
        print(f'{pname}Redis Socket Path {redis_socket}')
        r = redis.Redis(unix_socket_path=redis_socket)
    else:
        redis_ip = redis_params['redis_realtime_ip']
        redis_port = redis_params['redis_realtime_port']
        print(f'{pname}Redis IP: {redis_ip}, Redis port: {redis_port}')
        r = redis.Redis(host=redis_ip, port=redis_port)

    print(f"{pname}Initialized Redis")

    return r




# -----------------------------------------------------------
def get_redis_info(yaml_path,field):
    """
    Create a string with redis connection info -- either IP
    or port

    Parameters
    ----------
    yaml_path : str
        Path of the YAML file
    field     : str
        "ip" or "port"

    Returns
    -------
    string
        ip or port address
    """
    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f)
        returnValue = yamlData['RedisConnection'][field]

    return returnValue


# -----------------------------------------------------------
def get_node_io(yaml_path,node):
    """
    Return information about the edges of a specific node, as
    defined by the graph settings yaml file

    Parameters
    ----------
    yaml_path : str
        path of the YAML graph settings file
    node      : str
        name of the node we're inspecting

    Returns:
    dict
        a dictionary with two nested dictionaries: one named
        'redis_inputs' and one named 'redis_outputs'. 
    """

    # initialize the io dict
    io = {'redis_inputs':{}, 'redis_outputs':{}}
    redis_inputs = None
    redis_outputs = None


    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f)


        # get the list of inputs and outputs for the matching node
        for node_data in yamlData['Nodes']:
            if node_data['Name'].split('.')[0] == node:
                redis_inputs = node_data['redis_inputs']
                redis_outputs = node_data['redis_outputs']
                if type(redis_inputs) is str:
                    redis_inputs = [redis_inputs]
                if type(redis_outputs) is str:
                    redis_outputs = [redis_outputs]

        if redis_inputs is not None:
            for in_stream in redis_inputs:
                io['redis_inputs'][in_stream] = yamlData['RedisStreams'][in_stream]
        if redis_outputs is not None:
            for out_stream in redis_outputs:
                io['redis_outputs'][out_stream] = yamlData['RedisStreams'][out_stream]
                
    return io

# -----------------------------------------------------------
# Moving all node settings into Redis
def nodes_into_redis(yaml_path):
    """
    Takes all node and stream information from the passed Graph YAML
    settings file, and puts it into a series of Redis streams


    Parameters
    ----------
    yaml_path : str
        path of the YAML graph settings file

    Returns:
    failure   : int
        0 : loaded into Redis without a problem,
        1 : generic error
    """
    
    r = initializeRedisFromYAML(yaml_path, 'yamlIntoRedis')

    node_params = get_node_parameter_dump(yaml_path) # get the full "node" dictionary

    p = r.pipeline() # create a new pipeline -- we'll just spit this all in at once
    
    for node,params in node_params.items():
        p.xadd(f"{node}_params", params)


# -----------------------------------------------------------
# parsing variable type information from the streams section
def unpack_string(yaml_path, stream):
    """
    Helper function to create a string for the pack/unpack struct
    functions for python to read from data written in C. Uses
    the sample_type field in the graph settings yaml
    """

    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f)

    sample_type = yamlData['RedisStreams'][stream]['sample_type']
    num_chans = yamlData['RedisStreams'][stream]['chan_per_stream']
    num_samp = yamlData['RedisStreams'][stream]['samp_per_stream']
    
    if sample_type in ['int16', 'short']:
        packString = 'h'
    elif sample_type in ['int32', 'int', 'Int']:
        packString = 'i'
    elif sample_type in ['uInt32', 'uInt']:
        packString = 'I'
    elif sample_type == 'char':
        packString = 'b'
    else:
        return -1

    # output string = <#values><var type> -- 10I, 960h etc
    packString = str(num_chans * num_samp) + packString
    return packString

 
# -----------------------------------------------------------
# list of processes for a particular stage
def node_stage(yaml_path, stage):
    """
    Returns the names of all of the nodes that have been associated
    with that stage of the run process
    """
    
    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f)

    # return the list of node names that match the desired stage
    stage_nodes = []
    for nodes in yamlData['Nodes']:
        if nodes['Stage'].lower() == stage.lower():
            stage_nodes.append(nodes['Name'])
    
    return ' '.join(stage_nodes) # create a single string of all of the items with spaces between -- for bash convenience

# -----------------------------------------------------------
# get module name for a given node
def get_node_module(yaml_path, node_name):
    """
    Get the module name from the node name in a yaml file

    Parameters
    ----------
    yaml_path : str
        Path of the YAML file
    node_name : str
        Name of the node to use

    Returns
    -------
    str
        Module name for node
    """

    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f)

    for node in yamlData['Nodes']:
        if node['Name'].split('.')[0] == node_name:
            return node['Module']

# -----------------------------------------------------------
# running the function as a script -- for C and Bash usage
def main():

    description = """
        Tools for initializing processes. The default behavior is to look into a YAML file
        and then initialize all of the variables from the YAML script into Redis. This
        behavior, by default, is verbose. 

        If you supply an --ip or --port flag, then the script will look specifically for
        the script will look specifically for the redis_ip or redis_port variable from
        the script and print it. 
        
        the --stage flag is used with "start", "main" or "end" to return a list of nodes
        that will run during that process period. Refer to the run script for more info

        This should be used only for c or bash."""

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--name', help='Return the value in the YAML file', type=str)
    parser.add_argument('--node', help='Which node to use', type=str)
    parser.add_argument('--module', type=str, help='Return module name for given node')
    parser.add_argument('file', default="", type=str, help='The YAML file to be loaded')
    parser.add_argument('--redis', help="Return the port and ip for the redis instance")
    parser.add_argument('--stage', type=str, help="Returns list of Start, Main or End modules")
    redisGroup = parser.add_mutually_exclusive_group()
    redisGroup.add_argument('--ip', help='IP for the redis instance', action="store_true")
    redisGroup.add_argument('--port', help='port for the redis instance',  action="store_true")

    args = parser.parse_args()

    if args.ip:
        print(get_redis_info(args.file,'redis_realtime_ip'))
    elif args.port:
        print(get_redis_info(args.file,'redis_realtime_port'))
    elif args.node: ## if we got a node name, look inside of that specific node -- standard behavior now!
        if args.name: # if we have a particular value
            print(get_node_parameter_value(args.file, args.node, args.name), end="")
        else: # return all values
            print(get_node_parameter_dump(args.file, args.node), end="")
    elif args.name: # if no node name is supplied... probably mostly for the redis connection
        print(get_parameter_value(args.file, args.name), end="")
    elif args.stage:
        print(node_stage(args.file, args.stage), end="")
    elif args.module: # if we ask for module name for a node
        print(get_node_module(args.file, args.module), end="")


if __name__ == '__main__':
    main()




