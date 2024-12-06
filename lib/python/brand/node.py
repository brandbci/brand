# BRAND node template
# Author: Mattia Rigotti
# Adapted from code by: David Brandman and Kushant Patel

import argparse
import gc
import json
import logging
import signal
import sys

from redis import Redis

from .redis import RedisLoggingHandler

class BRANDNode():
    def __init__(self):

        # parse input arguments
        argp = argparse.ArgumentParser()
        argp.add_argument('-n', '--nickname', type=str, required=True, default='node')
        argp.add_argument('-i', '--redis_host', type=str, required=True, default='localhost')
        argp.add_argument('-p', '--redis_port', type=int, required=True, default=6379)
        argp.add_argument('-s', '--redis_socket', type=str, required=False)
        args = argp.parse_args()

        len_args = len(vars(args))
        if(len_args < 3):
            print("Arguments passed: {}".format(len_args))
            print("Please check the arguments passed")
            sys.exit(1)

        self.NAME = args.nickname
        redis_host = args.redis_host
        redis_port = args.redis_port
        redis_socket = args.redis_socket

        # connect to Redis
        self.r = self.connectToRedis(redis_host, redis_port, redis_socket)

        # initialize parameters
        self.parameters = {}
        self.supergraph_id = '0-0'
        self.initializeParameters()

        # set up logging
        loglevel = self.parameters.setdefault('log', 'INFO')
        numeric_level = getattr(logging, loglevel.upper(), None)

        if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: %s' % loglevel)

        logging.basicConfig(format=f'[{self.NAME}] %(levelname)s: %(message)s',
                            level=numeric_level)
        self.redis_log_handler = RedisLoggingHandler(self.r, self.NAME)
        logging.getLogger().addHandler(self.redis_log_handler)

        signal.signal(signal.SIGINT, self.terminate)

        sys.excepthook = self._handle_exception

    def connectToRedis(self, redis_host, redis_port, redis_socket=None):
        """
        Establish connection to Redis and post initialized status to respective Redis stream
        If we supply a -h flag that starts with a number, then we require a -p for the port
        If we fail to connect, then exit status 1
        # If this function completes successfully then it executes the following Redis command:
        # XADD nickname_state * code 0 status "initialized"        
        """
        try:
            if redis_socket:
                r = Redis(unix_socket_path=redis_socket)
                print(f"[{self.NAME}] Redis connection established on socket:"
                      f" {redis_socket}")
            else:
                r = Redis(redis_host, redis_port, retry_on_timeout=True)
                print(f"[{self.NAME}] Redis connection established on host:"
                      f" {redis_host}, port: {redis_port}")
        except ConnectionError as e:
            print(f"[{self.NAME}] Error with Redis connection, check again: {e}")
            sys.exit(1)

        initial_data = {
            'code':0,
            'status':'initialized',
        }
        r.xadd(self.NAME + '_state', initial_data)

        return r

    def getParametersFromSupergraph(self, complete_supergraph=False):
        """
        Read node parameters from Redis

        Parameters
        ----------
        complete_supergraph : (optional) boolean
            False returns just the node's parameters.
            True returns the complete supergraph
            straight from the Redis xrange call.

        Returns
        -------
        new_params : list of dict
            Each list item will be a dictionary of the
            node's parameters in that supergraph
        """
        model_stream_entries = self.r.xrange(b'supergraph_stream', '('+self.supergraph_id, '+')

        if not model_stream_entries:
            return None
        
        self.supergraph_id = model_stream_entries[-1][0]
        self.supergraph_id = self.supergraph_id.decode('utf-8')

        if complete_supergraph:
            return model_stream_entries

        new_params = [{} for i in model_stream_entries] # {} means the node was not listed in the corresponding supergraph

        for i, entry in enumerate(model_stream_entries):

            model_data = json.loads(entry[1][b'data'].decode())

            for node in model_data['nodes']:
                if model_data['nodes'][node]['nickname'] == self.NAME:
                    new_params[i] = model_data['nodes'][node]['parameters']

        return new_params

    def initializeParameters(self):
        """
        Read node parameters from Redis.
        ...
        """
        node_parameters = self.getParametersFromSupergraph()
        if node_parameters is None:
            print(f"[{self.NAME}] No model published to supergraph_stream in Redis")
            sys.exit(1)

        for key,value in node_parameters[-1].items():
            self.parameters[key] = value

    def run(self):

        while True:
            self.work()
            self.updateParameters()

    def work(self):
        """
        # This is the business logic for the function. 
        # At the end of its cycle, it should output the following:
        # XADD nickname_streamOutputName [inputRun M] run nRuns parameter N name1 value1 name2 value2
        # where streamOutputName is the name provided in the YAML file (usually: output)
        # and the name1 is the name variable for the output stream, and the value being the payload
        # and N is the value of parameter_count global variable
        # Note there is an exact match between the name value pairs and what is specified in the YAML
        # If inputs is not [] in the YAML file, then inputRun contains the 
        # nRuns count of the previous input used for populating this stream output       
        """
        pass

    # def write_brand(self):

    #     self.sync_dict_json = json.dumps(self.sync_dict)

    #     self.output_entry[self.time_key] = time.monotonic()
    #     self.output_entry[self.sync_key] = self.sync_dict_json.encode()

    #     self.r.xadd(self.output_stream, self.output_entry)


    def updateParameters(self):
        """
        This function reads from the nickname_parameters stream, 
        and knows how to parse all parameters that (1) do not have static variable
        specified, or (2) are static: false specified
        It does not block on the XREAD call. Whenever there is a new stream value,
        it assumes that the new value is meaningful (since it should have been checked
        by the supervisor node) and then updates the parameters = {} value
        If this function updates the parameters{} dictionary, then it increments parameter_count
        """
        pass

    def terminate(self, sig, frame):
        logging.info('SIGINT received, Exiting')
        self.cleanup()
        self.r.close()
        gc.collect()
        sys.exit(0)

    def cleanup(self):
        # Does whatever cleanup is required for when a SIGINT is caught
        # When this function is done, it wriest the following:
        #     XADD nickname_state * code 0 status "done"
        pass

    def _handle_exception(self, exc_type, exc_value, exc_traceback):
        """
        Handle uncaught exceptions by logging them.
        """
        if self.r.ping():
            logging.exception('', exc_info=(exc_type, exc_value, exc_traceback))
        else:
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
