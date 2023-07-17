# Some helpers to work with Redis

import sys
import yaml
import redis
import datetime
import sys
import argparse
import errno


#############################################
#############################################
## Load the YAML file
#############################################
#############################################

# this is designed for the older yaml parameter style.
# should likely remove this, though I'm not sure if we
# need it for a convenient way to get redis connection
# information

def get_parameter_value(fileName, field):
    try:
        with open(fileName, 'r') as f:
            yamlData = yaml.safe_load(f)
            for record in yamlData['parameters']:
                if record['name'] == field:
                    return record['value']

    except IOError as e:
        if e.errno == errno.EPIPE:
            return "THERE HAS BEEN AN EGREGIOUS EPIPE ERROR"


#############################################
#############################################
# return specific parameters from a specific node. 
# if you're wanting the input/output info, use
# get_node_io

def get_node_parameter_value(yaml_path, node):
    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f)
        for node_list in yamlData['Nodes']:
            if node_list['Name'] == node:
                return node_list['Parameters'][field]



#############################################
#############################################
# return specific parameters from a specific node. 
# if you're wanting the input/output info, use
# get_node_io

def get_node_io(yaml_path, node):
    io = {'redis_inputs':[], 'redis_outputs':[]}
    
    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f)
        
        # get the list of inputs and outputs for the matching node
        for node_data in yamlData['Nodes']:
            if node_data['Name'] == node:
                redis_inputs = node_data['redis_inputs']
                redis_outputs = node_data['redis_outputs']
                if type(redis_inputs) == str: # we need a list
                    redis_inputs = list(redis_inputs)
                if type(redis_outputs) == str: # we need a list
                    redis_outputs = list(redis_outputs)

        # put all of the associated info from the streams into the 
        # output dictionary
        for in_stream in redis_inputs:
            io['redis_inputs'][in_stream] = yamlData['RedisStreams'][in_stream]
        for out_stream in redis_outputs:
            io['redis_outputs'][out_stream] = yamlData['RedisStreams'][out_stream]
                

    return io

#############################################
#############################################
# really just for python -- dump a dictionary with all of the
# values for the node inside of the "Parameters" section

def get_node_parameters_dump(yaml_path, node):
    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f)
        for node_list in yamlData['Nodes']:
            if node_list['Name'] == node:
                return node_list['Parameters']




#############################################
#############################################

def initializeRedisFromYAML(yaml_path, processName):


    print("[" + processName + "] connecting to Redis using: " + fileName)

    try:
        with open(yaml_path, 'r') as f:
            yamlData = yaml.safe_load(f)
            redisIP = yamlData['RedisConnection']['redis_realtime_ip']
            redisPort = yamlData['RedisConnection']['redis_realtime_port']

    except IOError:
        sys.exit( "[" + processName + "] could not read file:" + yaml_path)
    
        

    print("[" + processName + "] Initializing Redis with IP : " + redisIP + ", port: " + str(redisPort))

    # Having gotten to this point we can now create our redis connection
    r = redis.Redis(host=redisIP, port=redisPort)
    return r






#############################################
#############################################
def get_redis_info(yaml_path,field):
    # return info about the redis session from the associated yaml
    with open(yaml_path, 'r') as f:
        yamlData = yaml.safe_load(f)
        returnValue = yamlData['RedisConnection'][field]

    return returnValue


#############################################
#############################################

""" -- probably don't want to push all of the data into the redis instance repeatedly -- that will be for the graph as a whole
    print("[" + processName + "] Here are the other variables:")

    # Get the name of the process based on the filename. Expect: /path/to/processName.yaml
    processName = fileName.split("/")[-1].split(".")[0]

    for record in yamlData['parameters']:

        record['name'] = processName + "_" + record['name']

        r.delete(record['name'])

        print("     Record: ", record['name'], ": ", record['value'])


        if type(record['value']) == bool:
            if record['value']:
                record['value'] = 1
            else:
                record['value'] = 0

        if type(record['value']) == list:
            for val in record['value']:
                r.rpush(record['name'],val)

        else:
            r.set(record['name'], record['value'])
    
    return r
"""

#############################################
## Publishing data from Redis
#############################################

def publish(r, name, val):

    # Format what now is in the sqlite3 format, removing the sub-millisecond precision
    timeStamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[0:-3]
    str = timeStamp + "," + val
    r.publish(name, str)



#############################################
## Getting data from Redis
#############################################

def getFloat(r, name):
    return float(r.get(name))

def getInt(r, name):
    return int(r.get(name))

def getString(r, name):
    return (r.get(name)).decode('utf-8')

def getFloatLRange(r, name, start, end):
    return [float(x) for x in r.lrange(name, start, end)]

def getIntLRange(r, name, start, end):
    return [int(x) for x in r.lrange(name, start, end)]

def getStringLRange(r, name, start, end):
    return [x.decode('utf-8') for x in r.lrange(name, start, end)]

#############################################
## Running code like a script
#############################################

def main():

    description = """
        Tools for initializing processes. The default behavior is to look into a YAML file
        and then initialize all of the variables from the YAML script into Redis. This
        behavior, by default, is verbose. If you supply an --ip or --port flag, then
        the script will look specifically for the redis_ip or redis_port variable from
        the script and print it. This should be used only for .c processes"""

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--name', help='Return the value in the YAML file', type=str)
    parser.add_argument('--node', help='Which node to use', type=str)
    parser.add_argument('file', default="", type=str, help='The YAML file to be loaded')
    parser.add_argument('--redis', help="Return the port and ip for the redis instance")
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
            print(get_node_parameters(args.file, args.node), end="") 
    elif args.name: # if no node name is supplied... probably mostly for the redis connection
        print(get_parameter_value(args.file, args.name), end="")


if __name__ == '__main__':
    main()




