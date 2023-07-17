import argparse
import json
import logging
import os
import re
import sh
from sh import git
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime

import coloredlogs
import redis
import yaml
from redis import Redis

from .exceptions import (GraphError, NodeError, BooterError, DerivativeError, CommandError, RedisError)

logger = logging.getLogger(__name__)
coloredlogs.install(level='DEBUG', logger=logger)
DEFAULT_DATA_DIR = os.path.abspath(os.path.join(os.getcwd(), '..', 'Data'))

class Supervisor:
    def __init__(self):
        ''' Initialize the supervisor class and load the graph file loaded from the command line '''
        self.logger = logger

        self.model = {}
        self.r = None
        self.parent = None
        self.children = {}

        self.BRAND_BASE_DIR = os.getcwd()
        self.BRAND_MOD_DIR = os.path.abspath(os.path.join(self.BRAND_BASE_DIR,'../brand-modules/')) # path to the brand modules directory

        self.state = ("initialized", "parsing", "graph failed", "running",
                      "published", "stopped/not initialized")

        self.git_hash = str(git('-C', self.BRAND_BASE_DIR, 'rev-parse', 'HEAD')).splitlines()[0]

        self.graph_file = None
        self.redis_pid = None

        self.booter_status_id = '0-0'

        signal.signal(signal.SIGINT, self.terminate)

        graph_dict = self.parse_args()

        self.start_redis_server()
        self.r.xadd("graph_status", {'status': self.state[5]})

        if self.graph_file is not None: self.load_graph(graph_dict)


    def handler(signal_received,self):
        raise KeyboardInterrupt("SIGTERM received")


    def parse_args(self)->dict:
        ''' Parse the graph file loaded from the command line and return the graph dictionary using -g option/cmdline argument
        Returns:
            graph_dict: graph dictionary
        '''
        ap =  argparse.ArgumentParser()
        ap.add_argument("-g", "--graph", required=False, help="path to graph file")
        ap.add_argument("-i", "--host", required=False, help="ip address to bind redis server to")
        ap.add_argument("-p", "--port", required=False, help="port to bind redis server to")
        ap.add_argument("-s", "--socket", required=False, help="unix socket to bind redis server to")
        ap.add_argument("-c", "--cfg", required=False, help="cfg file for redis server")
        ap.add_argument("-m", "--machine", type=str, required=False, help="machine on which this supervisor is running")
        ap.add_argument("-r", "--redis-priority", type=int, required=False, help="priority to use for the redis server")
        ap.add_argument("-a", "--redis-affinity", type=str, required=False, help="cpu affinity to use for the redis server")
        ap.add_argument("-l", "--log-level", default=logging.DEBUG, type=lambda x: getattr(logging, x.upper()), required=False, help="supervisor logging level")
        ap.add_argument("-d", "--data-dir", type=str, default=DEFAULT_DATA_DIR, required=False, help="root data directory for supervisor's save path")
        args = ap.parse_args()

        self.redis_args = []

        if args.cfg is not None:
            self.redis_args.append(args.cfg)
        else:
            self.redis_args.append(
                os.path.join(self.BRAND_BASE_DIR,
                             'lib/python/brand/redis.supervisor.conf'))
        if args.host is not None:
            self.redis_args.append('--bind')
            self.redis_args.append(args.host)
            self.host = args.host
        else:
            self.host = '127.0.0.1'
        if args.port is not None:
            self.redis_args.append('--port')
            self.redis_args.append(args.port)
            self.port = args.port
        else:
            self.port = 6379

        self.unixsocket = args.socket
        if self.unixsocket is not None:
            self.redis_args += ['--unixsocket', self.unixsocket]

        self.machine = args.machine
        self.redis_priority = args.redis_priority
        self.redis_affinity = args.redis_affinity

        logger.setLevel(args.log_level)

        self.data_dir = args.data_dir
        self.save_path = args.data_dir
        self.save_path_rdb = args.data_dir

        self.graph_file = args.graph
        graph_dict = {}
        if self.graph_file is not None:
            try:
                with open(args.graph, 'r') as stream:
                    graph_dict = yaml.safe_load(stream)
                    graph_dict['graph_name'] = os.path.splitext(os.path.split(args.graph)[-1])[0]
                    self.graph_file = args.graph
            except FileNotFoundError as exc:
                raise GraphError(f"Could not find the graph at {args.graph}", args.graph) from exc
            except yaml.YAMLError as exc:
                raise GraphError("Error parsing graph YAML file", args.graph) from exc
            logger.info("Graph file parsed successfully")
        return graph_dict


    def search_node_bin_file(self, module, name) -> str:
        ''' Search the node bin/exec file and return the bin/exec file path 
        Args:
            module: module name
            name : node name
        '''
        filepath = os.path.join(self.BRAND_BASE_DIR, module, 'nodes', name,
                                f'{name}.bin')
        filepath = os.path.abspath(filepath)
        return filepath

    def get_graph_status(self,state)->str:
        '''
        Utility function to get the graph status
        Args:
            state: graph status from redis stream using xrevrange
        '''
        if state:
            key,messages = state[0]
            current_status = messages[b'status'].decode("utf-8")
        else:
            logger.info("No status found in redis stream")
        return current_status


    def check_graph_not_running(self, cmd=''):
        '''
        Checks that a graph is not currently executing, generating an exception if it is
        '''
        # validate graph is not running
        graph_status = self.r.xrevrange('graph_status', '+', '-', count=1)
        if self.get_graph_status(graph_status) == self.state[3]:
            raise CommandError(f'Cannot run {cmd} command while a graph is running', 'supervisor', cmd)


    def start_redis_server(self):
        redis_command = ['redis-server'] + self.redis_args
        if self.redis_priority:
            chrt_args = ['chrt', '-f', f'{self.redis_priority :d}']
            redis_command = chrt_args + redis_command
        if self.redis_affinity:
            redis_command = ['taskset', '-c', self.redis_affinity
                             ] + redis_command
        logger.info('Starting redis: ' + ' '.join(redis_command))
        # get a process name by psutil
        proc = subprocess.Popen(redis_command, stdout=subprocess.PIPE)
        self.redis_pid = proc.pid
        try:
            out, _ = proc.communicate(timeout=1)
            if out:
                logger.debug(out.decode())
            if 'Address already in use' in str(out):
                raise RedisError("Could not run redis-server (address already in use). Is supervisor already running?")
            else:
                raise RedisError("Launching redis-server failed for an unknown reason, check supervisor logs. Aborting.")
        except subprocess.TimeoutExpired:  # no error message received
            logger.info('redis-server is running')
        self.r = Redis(self.host,self.port,socket_connect_timeout=1)

        # Set rdb save directory
        if not os.path.exists(self.save_path_rdb):
            os.makedirs(self.save_path_rdb)
        self.r.config_set('dir', self.save_path_rdb)
        logger.info(f"RDB save directory set to {self.save_path_rdb}")
        # Set new rdb filename
        self.rdb_filename =  'idle_' + datetime.now().strftime(r'%y%m%dT%H%M') + '.rdb'
        self.r.config_set('dbfilename', self.rdb_filename)
        logger.info(f"RDB file name set to {self.rdb_filename}")


    def get_save_path(self, graph_dict:dict={}):
        """
        Get the path where the RDB and NWB files should be saved
        Parameters
        ----------
        graph_dict : (optional) dict
            Dictionary containing the supergraph parameters
        Returns
        -------
        save_path : str
            Path where data should be saved
        """
        # Check if the participant file exists
        has_participant_file = (
            'metadata' in graph_dict
            and 'participant_file' in graph_dict['metadata']
            and os.path.exists(graph_dict['metadata']['participant_file']))

        # Get participant and session info
        if has_participant_file:
            with open(graph_dict['metadata']['participant_file'], 'r') as f:
                participant_info = yaml.safe_load(f)
            participant_id = participant_info['metadata']['participant_id']
        elif 'metadata' in graph_dict and 'participant_id' in graph_dict['metadata']:
            participant_id = graph_dict['metadata']['participant_id']
        else:
            participant_id = 0

        # Make paths for saving files
        session_str = datetime.today().strftime(r'%Y-%m-%d')
        session_id = f'{session_str}'
        save_path = os.path.join(self.data_dir, str(participant_id), session_id, 'RawData')
        save_path = os.path.abspath(save_path)
        return save_path


    def load_graph(self,graph_dict,rdb_filename=None,publish_graph=True):
        ''' Running logic for the supervisor graph, establishes a redis connection on specified host & port  
        Args:
            graph_dict: graph dictionary
        '''

        if set(["graph_name", "nodes"]).issubset(graph_dict):
            self.graph_name = graph_dict["graph_name"]
            nodes = graph_dict["nodes"]
        else:
            raise GraphError(
                "KeyError: "
                f"{list(set(['graph_name', 'nodes'])-set(graph_dict))}"
                f" field(s) missing in {self.graph_file}",
                self.graph_file)

        self.r.xadd("graph_status", {'status': self.state[0]}) #status 1 means graph is running

        model = {}
        model["redis_host"] = self.host
        model["redis_port"] = self.port
        model["brand_hash"] = self.git_hash
        model["graph_name"] = self.graph_name
        model["graph_loaded_ts"] = time.monotonic_ns()

        # Set rdb save directory
        self.save_path = self.get_save_path(graph_dict)
        self.save_path_rdb = os.path.join(self.save_path, 'RDB')
        if not os.path.exists(self.save_path_rdb):
            os.makedirs(self.save_path_rdb)
        self.r.config_set('dir', self.save_path_rdb)
        logger.info(f"RDB save directory set to {self.save_path_rdb}")

        # Set rdb filename
        if rdb_filename is None:
            self.rdb_filename =  self.save_path.split(os.path.sep)[-3] + '_' + datetime.now().strftime(r'%y%m%dT%H%M') + '_' + self.graph_name + '.rdb'
        else:
            self.rdb_filename = rdb_filename
        self.r.config_set('dbfilename', self.rdb_filename)
        logger.info(f'rdb filename: {self.rdb_filename}')

        # Load node information
        model["nodes"] = {}
        self.r.xadd("graph_status", {'status': self.state[1]})  # status 2 means graph is parsing

        # catch key errors for nodes that are not in the graph
        try:
            for n in nodes:
                # Check for duplicate nicknames
                if n["nickname"] in model["nodes"]:
                    raise NodeError(
                        f"Duplicate node nicknames found: {n['nickname']}",
                        self.graph_name,
                        n["nickname"])
                # Loading the nodes and graph into self.model dict
                model["nodes"][n["nickname"]] = {}
                model["nodes"][n["nickname"]].update(n)
                bin_f = self.search_node_bin_file(n["module"],n["name"])
                model["nodes"][n["nickname"]]["binary"] = bin_f
                if ('machine' not in n or n["machine"] == self.machine):
                    if not os.path.exists(bin_f):
                        raise NodeError(
                            f'{n["name"]} executable was not found at {bin_f}',
                            self.graph_name,
                            n["name"])
                try:
                    # read Git hash for the node
                    with open(os.path.join(os.path.split(bin_f)[0], 'git_hash.o'), 'r') as f:
                        model["nodes"][n["nickname"]]["git_hash"] = f.read().splitlines()[0]

                    # read Git hash from the repository
                    git_hash_from_repo = str(git('-C', os.path.split(bin_f)[0], 'rev-parse', 'HEAD')).splitlines()[0]

                    # check repository hash is same as git_hash
                    if git_hash_from_repo != model["nodes"][n["nickname"]]["git_hash"]:
                        logger.warning(f"Git hash for {n['nickname']} node nickname does not match the repository's Git hash, remake")

                except sh.ErrorReturnCode: # not in a git repository, manual git_hash.o file written, so use that hash
                    pass
                except FileNotFoundError: # git_hash.o file not found
                    model["nodes"][n["nickname"]]["git_hash"] = ''
                    logger.warning(f"Could not log Git hash for {n['nickname']} nickname, could not find compiled git_hash.o file")
                except Exception as e: # unknown reason
                    model["nodes"][n["nickname"]]["git_hash"] = ''
                    logger.warning(f"Could not log Git hash for {n['nickname']} nickname for an unknown reason")
                    logger.warning(repr(e))

                logger.info("%s is a valid node" % n["nickname"])

            if "derivatives" in graph_dict:
                model["derivatives"] = {}
                derivatives = graph_dict['derivatives']
                for a in derivatives:
                    a_name = list(a.keys())[0]
                    a_values = a[a_name]
                    model["derivatives"][a_name] = a_values
                    if 'script_path' in model["derivatives"][a_name]:
                        script_path = os.path.join(self.BRAND_BASE_DIR, model["derivatives"][a_name]['script_path'])

                        if not os.path.exists(script_path):
                            raise GraphError(f'Could not find derivative at {script_path}', self.graph_file)

                        try:
                            # read Git hash for the derivative
                            with open(os.path.join(os.path.split(script_path)[0], 'git_hash.o'), 'r') as f:
                                model["derivatives"][a_name]["git_hash"] = f.read().splitlines()[0]

                            # read Git hash from the repository
                            git_hash_from_repo = str(git('-C', os.path.split(script_path)[0], 'rev-parse', 'HEAD')).splitlines()[0]

                            # check repository hash is same as git_hash
                            if git_hash_from_repo != model["derivatives"][a_name]["git_hash"]:
                                logger.warning(f"Git hash for {a_name} derivative does not match the repository's Git hash, remake")

                        except sh.ErrorReturnCode: # not in a git repository, manual git_hash.o file written, so use that hash
                            pass
                        except FileNotFoundError: # git_hash.o file not found
                            model["derivatives"][a_name]["git_hash"] = ''

                    else:
                        model["derivatives"][a_name]["git_hash"] = ''

        except KeyError as exc:
            if "nickname" in n:
                name = n["nickname"]
            elif "name" in n:
                name = n["name"]
            else:
                raise NodeError(
                    "KeyError: "
                    "'name' and 'nickname' fields missing in graph YAML",
                    self.graph_name,
                    "NodeNameAndNicknameNotFound") from exc
            raise NodeError(
                "KeyError: "
                f"{exc} field missing in graph YAML "
                f"for node {name}",
                self.graph_name,
                name) from exc

        # model is valid if we make it here
        self.model = model
        if publish_graph:
            self.publish_graph()

    def publish_graph(self):
        model_pub = json.dumps(self.model)
        payload = {
            "data": model_pub
        }
        self.r.xadd("supergraph_stream",payload)
        logger.info("Supergraph Stream (Model) published successfully with payload")
        self.r.xadd("graph_status", {'status': self.state[4]}) # status 4 means graph is running and supergraph is published


    def start_graph(self):
        ''' Start the graph '''
        self.r.xadd('booter', {
            'command': 'startGraph',
            'graph': json.dumps(self.model)
        })
        current_state = self.r.xrevrange("graph_status", count=1)
        current_graph_status = self.get_graph_status(current_state)
        logger.info("Current status of the graph is: %s" % current_graph_status)
        logger.info("Validation of the graph is successful")
        host = self.model["redis_host"]
        port = self.model["redis_port"]
        for node, node_info in self.model["nodes"].items():
            node_stream_name = node_info["nickname"]
            if ('machine' not in node_info
                    or node_info["machine"] == self.machine):

                binary = node_info["binary"]

                # validate binary version
                try:
                    # read Git hash for the node
                    with open(os.path.join(os.path.split(binary)[0], 'git_hash.o'), 'r') as f:
                        hash = f.read().splitlines()[0]
                except FileNotFoundError: # git hash file not found
                    hash = ''
                if hash != self.model["nodes"][node_info["nickname"]]["git_hash"]:
                    logging.warning(f'Git hash for {node_info["nickname"]} '
                                    'node nickname does not match supergraph')

                logger.info("Binary for %s is %s" % (node,binary))
                logger.info("Node Stream Name: %s" % node_stream_name)
                args = [binary, '-n', node_stream_name]
                args += ['-i', host, '-p', str(port)]
                if self.unixsocket:
                    args += ['-s', self.unixsocket]
                if 'run_priority' in node_info:  # if priority is specified
                    priority = node_info['run_priority']
                    if priority:  # if priority is not None or empty
                        chrt_args = ['chrt', '-f', str(int(priority))]
                        args = chrt_args + args
                if 'cpu_affinity' in node_info:  # if affinity is specified
                    affinity = node_info['cpu_affinity']
                    if affinity:  # if affinity is not None or empty
                        taskset_args = ['taskset', '-c', str(affinity)]
                        args = taskset_args + args
                proc = subprocess.Popen(args)
                proc.name = node
                logger.info("Child process created with pid: %s" % proc.pid)
                logger.info("Parent process is running and waiting for commands from redis")
                self.parent = os.getpid()
                logger.info("Parent Running on: %d" % os.getppid())
                self.children[node] = proc

        self.checkBooter()

        # status 3 means graph is running and publishing data
        self.r.xadd("graph_status", {'status': self.state[3]})


    def stop_graph(self):
        '''
        Stops the graph
        '''
        self.r.xadd('booter', {'command': 'stopGraph'})
        # Kill child processes (nodes)
        self.r.xadd("graph_status", {'status': self.state[5]})
        self.kill_nodes()

    def kill_nodes(self):
        '''
        Kills child processes
        '''
        for node, proc in self.children.items():
            try:
                # check if process exists
                os.kill(proc.pid, 0)
            except OSError:
                self.logger.warning(f"'{node}' (pid: {proc.pid})"
                                    " isn't running and may have crashed")
                self.children[node] = None
            else:
                # process is running
                # send SIGINT
                proc.send_signal(signal.SIGINT)
                try:
                    # check if it terminated
                    proc.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    self.logger.warning(f"Could not stop '{node}' "
                                        f"(pid: {proc.pid}) using SIGINT")
                    # if not, send SIGKILL
                    proc.kill()
                    try:
                        # check if it terminated
                        proc.communicate(timeout=15)
                    except subprocess.TimeoutExpired:
                        pass  # delay error message until after the loop
                    else:
                        self.logger.info(f"Killed '{node}' "
                                         f"(pid: {proc.pid}) using SIGKILL")
                        self.children[node] = None
                else:
                    self.logger.info(f"Stopped '{node}' "
                                     f"(pid: {proc.pid}) using SIGINT")
                    self.children[node] = None
        # remove killed processes from self.children
        self.children = {
            n: p
            for n, p in self.children.items() if p is not None
        }
        # raise an error if nodes are still running
        if self.children:
            running_nodes = [
                f'{node} ({p.pid})' for node, p in self.children.items()
            ]
            message = ', '.join(running_nodes)
            self.logger.exception('Could not kill these nodes: '
                                  f'{message}')

    def update_params(self, new_params):
        '''
        Updates parameters from an input dictionary
        and writes a new supergraph

        Parameters
        ----------
        new_params : dict
            a dictionary with the following structure:
                keys correspond to the encoded
                    nicknames of nodes that have
                    parameter updates
                values are dicts represented as
                    strings (i.e. from `json.dumps`).
                    These dicts have keys that are the
                    parameter name and values that are
                    the new parameter value
        '''

        # validate the new parameters
        if self.model:
            for nickname in new_params:
                nn_dec = nickname.decode("utf-8")
                if nn_dec in self.model["nodes"]:
                    # validate correct JSON format
                    try:
                        json.loads(new_params[nickname].decode())
                    except json.decoder.JSONDecodeError as exc:
                        raise GraphError(
                            "JSONDecodeError: Redis strings should be single quotes (\')"
                            " and strings for JSON keys/values should be double quotes (\")",
                            self.graph_file)
                else:
                    raise GraphError(
                        f"There is no {nn_dec} nickname in the supergraph, skipped all parameter updates",
                        self.graph_file)
        else:
            raise GraphError(
                "Could not update graph parameters since no graph has been loaded yet",
                self.graph_file)

        # if we make it out of the above loop without error, then the parameter update is valid, so overwrite the existing model
        for nickname in new_params:
            nn_dec = nickname.decode("utf-8")
            nickname_params = json.loads(new_params[nickname].decode())
            for param, value in nickname_params.items():
                self.model["nodes"][nn_dec]["parameters"][param] = value

        # write the new supergraph
        model_pub = json.dumps(self.model)
        payload = {
            "data": model_pub
        }
        self.r.xadd("supergraph_stream", payload)
        logger.info("Supergraph updated successfully")
        self.r.xadd("graph_status", {'status': self.state[4]}) # status 4 means graph is published
        self.r.xadd("graph_status", {'status': self.state[3]}) # status 3 means graph is running

    def save_rdb(self):
        '''
        Saves an RDB file of the current database
        '''
        # Save rdb file
        self.r.save()
        logger.info(f"RDB data saved to file: {self.rdb_filename}")

    def save_nwb(self):
        '''
        Saves an NWB file from the most recent supergraph
        '''
        self.check_graph_not_running(cmd='saveNwb')

        # Make path for saving NWB file
        save_path_nwb = os.path.join(self.save_path, 'NWB')

        # Generate NWB dataset
        p_nwb = subprocess.run(['python',
                            'derivatives/exportNWB/exportNWB.py',
                            self.rdb_filename,
                            self.host,
                            str(self.port),
                            save_path_nwb],
                            capture_output=True)

        if len(p_nwb.stdout) > 0:
            logger.debug(p_nwb.stdout.decode())

        if p_nwb.returncode == 0:
            logger.info(f"NWB data saved to file: {os.path.join(self.save_path, 'NWB', os.path.splitext(self.rdb_filename)[0]+'.nwb')}")
        elif p_nwb.returncode > 0:
            raise DerivativeError(
                f"exportNWB returned exit code {p_nwb.returncode}.",
                'exportNWB',
                self.graph_file,
                p_nwb)
        elif p_nwb.returncode < 0:
            logger.info(f"exportNWB was halted during execution with return code {p_nwb.returncode}, {signal.Signals(-p_nwb.returncode).name}")

    def flush_db(self):
        '''
        Flushes the RDB
        '''
        # Flush database
        self.r.flushdb()

        # Set new rdb filename (to avoid overwriting what we just saved)
        self.rdb_filename = 'idle_' + datetime.now().strftime(r'%y%m%dT%H%M') + '.rdb'
        self.r.config_set('dbfilename', self.rdb_filename)
        logger.info(f"New RDB file name set to {self.rdb_filename}")

        # New RDB, so need to reset graph status
        self.r.xadd("graph_status", {'status': self.state[5]})

    def stop_graph_and_save_nwb(self):
        '''
        Stops the graph
        '''
        # Kill child processes (nodes)
        self.stop_graph()

        # Make path for saving NWB file
        save_path_nwb = os.path.join(self.save_path, 'NWB')
        # Save rdb file
        self.r.save()
        logger.info(f"RDB data saved to file: {self.rdb_filename}")

        # Generate NWB dataset
        p_nwb = subprocess.Popen(['python',
                            'derivatives/exportNWB/exportNWB.py',
                            self.rdb_filename,
                            self.host,
                            str(self.port),
                            save_path_nwb])
        p_nwb.wait()

        # Flush database
        self.r.flushdb()

        # Set new rdb filename (to avoid overwriting what we just saved)
        self.rdb_filename = 'idle_' + datetime.now().strftime(r'%y%m%dT%H%M') + '.rdb'
        self.r.config_set('dbfilename', self.rdb_filename)
        logger.info(f"New RDB file name set to {self.rdb_filename}")

        # New RDB, so need to reset graph status
        self.r.xadd("graph_status", {'status': self.state[5]})

    def make(self):
        '''
        Makes all nodes and derivatives
        '''
        self.check_graph_not_running(cmd='make')

        # Run make
        self.r.xadd('booter', {'command': 'make'})
        p_make = subprocess.run(['make'],
                                capture_output=True)

        if p_make.returncode == 0:
            logger.info(f"Make completed successfully")
        elif p_make.returncode > 0:
            raise CommandError(
                f"Make returned exit code {p_make.returncode}.",
                'supervisor',
                'make',
                'STDOUT:\n' + p_make.stdout.decode('utf-8') + '\nSTDERR:\n' + p_make.stderr.decode('utf-8'))
        elif p_make.returncode < 0:
            logger.info(f"Make was halted during execution with return code {p_make.returncode}, {signal.Signals(-p_make.returncode).name}")


    def terminate(self, sig, frame):
        logger.info('SIGINT received, Exiting')
        try:
            self.r.xadd("supervisor_status", {"status": "SIGINT received, Exiting"})
        except Exception as exc:
            logger.warning(f"Could not write exit message to Redis. Exiting anyway. {repr(exc)}")
        sys.exit(0)


    def parseCommands(self, data):
        '''
        Parses the command and calls the appropriate function(s)
        Args:
            data: contains the command to run in data[b'commands']
                and other information needed to execute the command
        '''
        cmd = (data[b'commands']).decode("utf-8").lower()

        if cmd in ["loadgraph", "startgraph"]:
            if self.children:
                raise GraphError("Graph already running, run stopGraph before initiating another graph", self.graph_file)

            if b'rdb_filename' in data:
                rdb_filename = data[b'rdb_filename'].decode("utf-8")
            else:
                rdb_filename = None

            if b'file' in data:
                logger.info(f"{cmd} command received with file")
                file = data[b'file'].decode("utf-8")
                graph_dict = {}
                try:
                    with open(file, 'r') as stream:
                        graph_dict = yaml.safe_load(stream)
                        graph_dict['graph_name'] = os.path.splitext(os.path.split(file)[-1])[0]
                        self.graph_file = file
                except FileNotFoundError as exc:
                    raise GraphError(f"Could not find the graph at {file}", file) from exc
                except yaml.YAMLError as exc:
                    raise GraphError("Error parsing graph YAML file", file) from exc
                self.load_graph(graph_dict,rdb_filename=rdb_filename)
                if cmd == "startgraph":
                    self.start_graph()
            elif b'graph' in data:
                logger.info(f"{cmd} command received with graph dict")
                self.load_graph(json.loads(data[b'graph']))
                if cmd == "startgraph":
                    self.start_graph()
            elif cmd == "startgraph":
                logger.info(f"{cmd} command received")
                if not self.model:
                    raise GraphError("No graph provided with startGgraph command and no graph previously loaded",
                    self.graph_file)
                self.start_graph()
            else: # command was loadGraph with insufficient inputs
                raise GraphError("Error loading graph, a graph YAML must be provided with the 'file' key or a graph dictionary must be provided with the 'graph' key", self.graph_file)
        elif cmd == "updateparameters":
            logger.info("Update parameters command received")
            new_params = {k:data[k] for k in data if k not in [b"commands"]}
            self.update_params(new_params)
        elif cmd == "stopgraph":
            logger.info("Stop graph command received")
            self.stop_graph()
        elif cmd == "stopgraphandsavenwb":
            logger.info("Stop graph and save NWB command received")
            self.stop_graph_and_save_nwb()
        elif cmd == "saverdb":
            logger.info("Save RDB command received")
            self.save_rdb()
        elif cmd == "savenwb":
            logger.info("Save NWB command received")
            self.save_nwb()
        elif cmd == "flushdb":
            logger.info("Flush DB command received")
            self.flush_db()
        elif cmd == "setdatadir":
            rel_path = os.path.relpath(self.save_path, self.data_dir)
            if b'path' in data:
                logger.info(f"Set data directory command received, setting to {data[b'path'].decode('utf-8')}")
                self.data_dir = data[b'path'].decode('utf-8')
            else:
                logger.info(f"Set data directory command received, setting to the default {DEFAULT_DATA_DIR}")
                self.data_dir = DEFAULT_DATA_DIR
            self.save_path = os.path.join(self.data_dir, rel_path)
            self.save_path_rdb = os.path.join(self.save_path, 'RDB')
            if not os.path.exists(self.save_path_rdb):
                os.makedirs(self.save_path_rdb)
            self.r.config_set('dir', self.save_path_rdb)
        elif cmd == "make":
            logger.info("Make command received")
            self.make()
        else:
            logger.warning("Invalid command")


    def checkBooter(self):
        '''
        Checks status of booter nodes
        '''
        statuses = self.r.xrange('booter_status', '('+self.booter_status_id, '+')
        if len(statuses) > 0:
            for entry in statuses:
                status = entry[1][b'status'].decode('utf-8')
                if status in ['NodeError', 'GraphError', 'CommandError']:
                    # get messages starting from the error
                    self.booter_status_id = entry[0].decode('utf-8')
                    raise BooterError(
                        f"{entry[1][b'machine'].decode('utf-8')} machine encountered an error: {entry[1][b'message'].decode('utf-8')}",
                        entry[1][b'machine'].decode('utf-8'),
                        self.graph_file,
                        entry[1][b'traceback'].decode('utf-8'),
                        status)

            self.booter_status_id = statuses[-1][0].decode('utf-8')


    def main(self):
        last_id = '$'
        logger.info('Listening for commands')
        self.r.xadd("supervisor_status", {"status": "Listening for commands"})
        while(True):
            try:
                self.checkBooter()
                cmd = self.r.xread({"supervisor_ipstream": last_id},
                                    count=1,
                                    block=5000)
                if cmd:
                    key,messages = cmd[0]
                    last_id,data = messages[0]
                    if b'commands' in data:
                        self.parseCommands(data)
                    else:
                        self.r.xadd("supervisor_status", {"status": "Invalid supervisor_ipstream entry", "message": "No 'commands' key found in the supervisor_ipstream entry"})
                        logger.error("'commands' key not in supervisor_ipstream entry")
                        self.r.xadd("supervisor_status", {"status": "Listening for commands"})

            except redis.exceptions.ConnectionError as exc:
                logger.error('Could not connect to Redis: ' + repr(exc))
                sys.exit(0)

            except GraphError as exc:
                # if the graph has an error, it was never executed, so log it
                self.r.xadd("graph_status",
                    {'status': self.state[2],
                    'message': str(exc),
                    'traceback': 'Supervisor ' + traceback.format_exc()})
                if self.children:
                    status = self.r.xrevrange("graph_status", '+', '-', count=2)
                    self.r.xadd("graph_status",
                        {'status': status[-1][1][b'status']})
                else:
                    self.r.xadd("graph_status", {'status': self.state[5]})
                graph = 'None' if exc.graph is None else exc.graph
                logger.error(f"Graph operation failed for {graph} graph")
                logger.error(str(exc))

            except NodeError as exc:
                # if a node has an error, stop the graph
                self.r.xadd("graph_status",
                    {'status': self.state[2],
                    'message': str(exc),
                    'traceback': 'Supervisor ' + traceback.format_exc()})
                self.r.xadd("supervisor_ipstream",
                    {'commands': 'stopGraph'})
                logger.error(f"Error with the {exc.node} node in the {exc.graph} graph")
                logger.error(str(exc))

            except BooterError as exc:
                # if a booter has a CommandError, report it
                if exc.source_exc == 'CommandError':
                    self.r.xadd("supervisor_status",
                        {'status': exc.source_exc,
                        'message': str(exc),
                        'traceback': exc.booter_tb + '\nSupervisor ' + traceback.format_exc()})
                # if a booter has a different error, stop the graph and kill all nodes
                else:
                    self.r.xadd("graph_status",
                        {'status': self.state[2],
                        'message': str(exc),
                        'traceback': exc.booter_tb + '\nSupervisor ' + traceback.format_exc()})
                    self.r.xadd("supervisor_ipstream",
                        {'commands': 'stopGraph'})
                logger.error(f"Error with the {exc.machine} machine")
                logger.error(str(exc))

            except DerivativeError as exc:
                # if a derivative has an error, then note that in the RDB
                derivative_tb = ''
                if exc.process.stdout is None:
                    derivative_tb += 'STDOUT: None\n'
                else:
                    derivative_tb += 'STDOUT: ' + exc.process.stdout.decode('utf-8') + '\n'

                if exc.process.stderr is None:
                    derivative_tb += 'STDERR: None\n'
                else:
                    derivative_tb += 'STDERR: ' + exc.process.stderr.decode('utf-8') + '\n'

                self.r.xadd("graph_status",
                    {'status': self.state[2],
                    'message': str(exc),
                    'traceback': 'Supervisor ' + traceback.format_exc() + '\n' + derivative_tb})
                # rewrite previous graph_status
                if self.children:
                    status = self.r.xrevrange("graph_status", '+', '-', count=2)
                    self.r.xadd("graph_status",
                        {'status': status[-1][1][b'status']})
                else:
                    self.r.xadd("graph_status", {'status': self.state[5]})

                logger.error(f"Error with the {exc.derivative} derivative")
                logger.error(str(exc))
                if exc.process.stderr is not None and len(exc.process.stderr) > 0:
                    logger.debug(exc.process.stderr.decode('utf-8'))

            except CommandError as exc:
                # if a command has an error, then note that in the RDB
                self.r.xadd("supervisor_status",
                    {"status": "Command error",
                    "message": str(exc),
                    "traceback": "Supervisor " + traceback.format_exc() + '\nDetails:\n' + exc.details})

                logger.error(f"Could not execute {exc.command} command.")
                logger.error(str(exc))
                self.r.xadd("supervisor_status", {"status": "Listening for commands"})

            except Exception as exc:
                self.r.xadd("supervisor_status",
                    {"status": "Unhandled exception",
                    "message": str(exc),
                    "traceback": "Supervisor " + traceback.format_exc()})
                logger.exception(f'Could not execute command. {repr(exc)}')
                self.r.xadd("supervisor_status", {"status": "Listening for commands"})