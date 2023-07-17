#!/usr/env/python

import argparse
from brand import *



# -----------------------------------------------------------
# running the function as a script -- for C and Bash usage
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

