import argparse
import coloredlogs
import json
import logging
import os
import psutil
import redis
import signal
import subprocess
import sys
import time
import traceback
import yaml

from datetime import datetime

from redis import Redis

from threading import Event

from .derivative import AutorunDerivatives, RunDerivative
from .exceptions import (BooterError, CommandError, DerivativeError,
                         GraphError, NodeError, RedisError)
from .redis import RedisLoggingHandler

logger = logging.getLogger(__name__)
coloredlogs.install(level='DEBUG', logger=logger)

class Supervisor:
    def __init__(self):
        ''' Initialize the supervisor class and load the graph file loaded from the command line '''
        self.logger = logger

        self.model = {}
        self.r = None
        self.parent = None
        self.child_nodes = {}

        self.BRAND_BASE_DIR = os.getcwd()
        self.BRAND_ROOT_DIR = os.path.abspath(os.path.join(self.BRAND_BASE_DIR, '..')) # path to the brand root directory
        self.BRAND_MOD_DIR = os.path.abspath(os.path.join(self.BRAND_ROOT_DIR, 'brand-modules')) # path to the brand modules directory
        self.DEFAULT_DATA_DIR = os.path.abspath(os.path.join(self.BRAND_ROOT_DIR, 'Data')) # path to the default brand data directory

        self.BOOTER_PING_STREAM = 'booter_ping'
        self.BOOTER_PING_REQUEST_STREAM = 'booter_ping_request'

        self.state = ("initialized", "parsing", "graph failed", "running",
                      "published", "stopped/not initialized")

        self.graph_file = None
        self.redis_pid = None

        self.booter_status_id = '0-0'
        self.booter_status_dict = {}

        self.derivative_threads = {}
        self.derivative_stop_events = {}
        self.derivative_continue_on_error = True

        self._persistent_log_level = "DEBUG" # default log level, applied to all commands
        self._command_log_level = self._persistent_log_level  # log level for current command

        signal.signal(signal.SIGINT, self.terminate)

        graph_dict = self.parse_args()

        self.start_redis_server()

        self.redis_log_handler = RedisLoggingHandler(self.r, 'supervisor')
        self.logger.addHandler(self.redis_log_handler)

        self.r.xadd("graph_status", {'status': self.state[5]})

        if self.graph_file is not None:
            self.load_graph(graph_dict)


    @property
    def command_log_level(self):
        return self._command_log_level
    
    @command_log_level.setter
    def command_log_level(self, value:str):
        try:
            logging._checkLevel(value.upper())
        except (ValueError, TypeError):
            self.logger.warning(f"Invalid command log level: {value}, skipping log level change.")
        else:
            self._command_log_level = value.upper()
            self.redis_log_handler.setLevel(self.command_log_level)

    def set_command_log_level_to_default(self):
        self.command_log_level = self.persistent_log_level

    @property
    def persistent_log_level(self):
        return self._persistent_log_level

    @persistent_log_level.setter
    def persistent_log_level(self, value:str):
        try:
            logging._checkLevel(value.upper())
        except (ValueError, TypeError):
            self.logger.warning(f"Invalid log level: {value}, skipping default log level change.")
        else:
            self._persistent_log_level = value.upper()
            self.set_command_log_level_to_default()
            self.logger.info(f"Default log level set to {self.persistent_log_level}")
            self.r.xadd("booter", { # sync the log level with the booter
                            'command': 'setLogLevel',
                            'level': self.persistent_log_level,
                            'log_level': self.command_log_level})


    def handler(signal_received,self):
        raise KeyboardInterrupt("SIGTERM received")


    def parse_args(self)->dict:
        ''' Parse the graph file loaded from the command line and return the graph dictionary using -g option/cmdline argument
        Returns:
            graph_dict: graph dictionary
        '''
        ap =  argparse.ArgumentParser()
        ap.add_argument("-g", "--graph", required=False, help="path to graph file")
        ap.add_argument("-i", "--host", required=False, help="ip address of the redis server (default: 127.0.0.1)")
        ap.add_argument("-p", "--port", required=False, help="port of the redis server (default: 6379)")
        ap.add_argument("-s", "--socket", required=False, help="unix socket to bind redis server to")
        ap.add_argument("-c", "--cfg", required=False, help="cfg file for redis server")
        ap.add_argument("-m", "--machine", type=str, default='supervisor', required=False, help="machine on which this supervisor is running")
        ap.add_argument("-r", "--redis-priority", type=int, required=False, help="priority to use for the redis server")
        ap.add_argument("-a", "--redis-affinity", type=str, required=False, help="cpu affinity to use for the redis server")
        ap.add_argument("-l", "--log-level", default=logging.DEBUG, type=lambda x: getattr(logging, x.upper()), required=False, help="supervisor logging level")
        ap.add_argument("-d", "--data-dir", type=str, default=self.DEFAULT_DATA_DIR, required=False, help="root data directory for supervisor's save path")
        ap.add_argument(
            "--bind",
            type=str,
            required=False,
            help=
            "network interfaces to bind the redis-server to (defaults to the"
            " same IP address as --host). To use the bind directives listed in"
            " the Redis config, set this to an empty string ('').")
        args = ap.parse_args()

        self.redis_args = []

        if args.cfg is not None:
            self.redis_args.append(args.cfg)
        else:
            self.redis_args.append(
                os.path.join(self.BRAND_BASE_DIR,
                             'lib/python/brand/redis.supervisor.conf'))

        if args.bind is not None:
            # --bind specified
            if args.bind:
                self.redis_args.append('--bind')
                self.redis_args += args.bind.split()
            # do nothing if --bind is an empty string ('')
        elif args.host is not None:
            # --bind not specified, but --host is
            self.redis_args.append('--bind')
            self.redis_args.append(args.host)

        if args.host is not None:
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
        
    def update_rdb_save_configs(self, rdb_save_path=None, rdb_filename=None):
        if rdb_save_path:
            # Set rdb save directory
            if not os.path.exists(rdb_save_path):
                os.makedirs(rdb_save_path)
            self.r.config_set('dir', rdb_save_path)
            if self.model:
                self.model["rdb_dirpath"] = rdb_save_path
            logger.info(f"RDB save directory set to: {rdb_save_path}")

        if rdb_filename:
            # Set rdb filename
            self.r.config_set('dbfilename', rdb_filename)
            if self.model:
                self.model["rdb_filename"] = rdb_filename
            logger.info(f'New RDB filename set to: {rdb_filename}')

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

        # Set new rdb filename
        self.rdb_filename =  'idle_' + datetime.now().strftime(r'%y%m%dT%H%M') + '.rdb'
        self.update_rdb_save_configs(self.save_path_rdb, self.rdb_filename)


    def get_save_path(self, graph_dict:dict={}):
        """
        Get the path where the RDB files should be saved
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
        return save_path, str(participant_id)


    def load_graph(self,graph_dict,rdb_filename=None, publish_graph=True):
        ''' Running logic for the supervisor graph, establishes a redis connection on specified host & port  
        Args:
            graph_dict: graph dictionary
            rdb_filename: Str filename to eventually save the .rdb to
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
        model["graph_name"] = self.graph_name
        model["graph_loaded_ts"] = time.monotonic_ns()

        # Set rdb save directory
        self.save_path, self.participant_id = self.get_save_path(graph_dict)
        self.save_path_rdb = os.path.join(self.save_path, 'RDB')

        # Set rdb filename
        if rdb_filename is None:
            self.rdb_filename =  self.participant_id + '_' + datetime.now().strftime(r'%y%m%dT%H%M') + '_' + self.graph_name + '.rdb'
        else:
            self.rdb_filename = rdb_filename

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
                
                # supervisor defaults to running all nodes without a machine specified
                if 'machine' not in n:
                    n.setdefault('machine', self.machine)

                if n["machine"] == self.machine:
                    bin_f = self.search_node_bin_file(n["module"],n["name"])
                    if not os.path.exists(bin_f):
                        raise NodeError(
                            f'{n["name"]} executable was not found at {bin_f}',
                            self.graph_name,
                            n["name"])
                else:
                    bin_f = None

                # Loading the nodes and graph into self.model dict
                model["nodes"][n["nickname"]] = {}
                model["nodes"][n["nickname"]].update(n)
                model["nodes"][n["nickname"]]["binary"] = bin_f

                logger.info("%s is a valid node" % n["nickname"])                

        except KeyError as exc:
            if "nickname" in n:
                name = n["nickname"]
            elif "name" in n:
                name = n["name"]
            else:
                raise GraphError(
                    "KeyError: "
                    "'name' and 'nickname' fields missing in graph YAML node(s)",
                    self.graph_name) from exc
            raise GraphError(
                "KeyError: "
                f"{exc} field missing in graph YAML "
                f"for node {name}",
                self.graph_name) from exc
        
        try:
            derivatives = graph_dict.get("derivatives", [])
            model['derivatives'] = {}
            for d in derivatives:
                # Check for duplicate nicknames
                if d['nickname'] in model['derivatives']:
                    raise DerivativeError(
                        f"Duplicate derivative nicknames found: {d['nickname']}",
                        d['nickname'],
                        self.graph_name)

                # supervisor defaults to running all derivatives without a machine specified
                if 'machine' not in d:
                    d['machine'] = self.machine
                
                # ensure sufficient file paths are provided
                if 'name' in d and 'module' in d:
                    filepath = os.path.join(
                        self.BRAND_BASE_DIR,
                        d['module'],
                        "derivatives",
                        os.path.splitext(d['name'])[0],
                        d['name'])
                    filepath = os.path.relpath(filepath, self.BRAND_BASE_DIR)
                elif 'full_path' in d:
                    filepath = d['full_path']
                else:
                    raise DerivativeError(
                        f"Derivative {d['nickname']} does not have complete path information",
                        d['nickname'],
                        self.graph_name)
                
                # ensure the file exists
                if (d['machine'] == self.machine and not os.path.exists(filepath)):
                    raise DerivativeError(
                        f"Derivative {d['nickname']} executable was not found at {filepath}",
                        d['nickname'],
                        self.graph_name)
                d['filepath'] = filepath
                
                model['derivatives'][d['nickname']] = {}
                model['derivatives'][d['nickname']].update(d)                

        except KeyError as exc:
            if "nickname" in d:
                name = d["nickname"]
            elif "name" in d:
                name = d["name"]
            else:
                raise GraphError(
                    "KeyError: "
                    "'name' and 'nickname' fields missing in graph YAML derivative(s)",
                    self.graph_name) from exc
            raise GraphError(
                "KeyError: "
                f"{exc} field missing in graph YAML "
                f"for derivative {name}",
                self.graph_name) from exc
        
        # ensure that node and derivative nicknames are not shared
        node_nicknames = set(model['nodes'].keys())
        derivative_nicknames = set(model['derivatives'].keys())
        shared_nicknames = node_nicknames & derivative_nicknames

        if shared_nicknames:
            raise GraphError(
                f"Node and derivative nicknames must be unique. "
                f"Duplicate nicknames found: {shared_nicknames}",
                self.graph_name)

        # model is valid if we make it here
        self.model = model

        self.update_rdb_save_configs(self.save_path_rdb, self.rdb_filename)
        
        if publish_graph:
            self.publish_graph()

    def publish_graph(self):
        model_pub = json.dumps(self.model)
        payload = {
            "data": model_pub
        }
        self.r.xadd("supergraph_stream",payload)
        self.r.xadd("booter", {
                        'command': 'loadGraph',
                        'graph': model_pub,
                        'log_level': self.command_log_level})
        logger.info("Supergraph Stream (Model) published successfully with payload")
        self.r.xadd("graph_status", {'status': self.state[4]}) # status 4 means graph is published


    def start_graph(self):
        ''' Start the graph '''
        self.r.xadd("booter", {
                        'command': 'startGraph',
                        'graph': json.dumps(self.model),
                        'log_level': self.command_log_level})
        current_state = self.r.xrevrange("graph_status", count=1)
        current_graph_status = self.get_graph_status(current_state)
        logger.info("Current status of the graph is: %s" % current_graph_status)
        logger.info("Validation of the graph is successful")
        host = self.model["redis_host"]
        port = self.model["redis_port"]
        for node, node_info in self.model["nodes"].items():
            # specify defaults
            node_info.setdefault('root', True)
            # run the node if it is assigned to this machine
            node_stream_name = node_info["nickname"]
            if ('machine' not in node_info
                    or node_info["machine"] == self.machine):

                binary = node_info["binary"]

                logger.info("Binary for %s is %s" % (node,binary))
                logger.info("Node Stream Name: %s" % node_stream_name)
                # build CLI command
                args = []
                if not node_info['root'] and 'SUDO_USER' in os.environ:
                    # run nodes as the current user, not root
                    args += [
                        'sudo', '-u', os.environ['SUDO_USER'], '-E', 'env',
                        f"PATH={os.environ['PATH']}"
                    ]
                args += [binary, '-n', node_stream_name]
                args += ['-i', host, '-p', str(port)]
                if self.unixsocket:
                    args += ['-s', self.unixsocket]
                # root permissions are needed to set real-time priority
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
                self.child_nodes[node] = proc

        self.checkBooter()

        # status 3 means graph is running and publishing data
        self.r.xadd("graph_status", {'status': self.state[3]})

    def start_autorun_derivatives(self):
        """Starts autorun derivatives"""
    
        # check if autorun derivatives are already running
        if 'supervisor_autorun' in self.derivative_threads:
            if self.derivative_threads['supervisor_autorun'].is_alive():
                raise CommandError("Autorun derivatives already running.", 'supervisor', 'startAutorunDerivatives')
            
        # create a stop event for the autorun derivatives
        self.derivative_stop_events['supervisor_autorun'] = Event()
        # create the thread that will keep track of autorunning derivatives
        autorun_derivative_thread = AutorunDerivatives(
            model=self.model,
            host=self.host,
            port=self.port,
            stop_event=self.derivative_stop_events['supervisor_autorun'],
            continue_on_error=self.derivative_continue_on_error)
        # start the thread
        autorun_derivative_thread.start()
        # add the thread to track it
        self.derivative_threads['supervisor_autorun'] = autorun_derivative_thread
        
    def kill_autorun_derivatives(self):
        """Kills autorun derivatives"""
        if 'supervisor_autorun' in self.derivative_threads:
            # set the stop event to stop the autorun derivatives
            self.derivative_stop_events['supervisor_autorun'].set()
            # delete the event and thread instances
            del self.derivative_stop_events['supervisor_autorun']
            del self.derivative_threads['supervisor_autorun']
            logger.info(f"Autorun derivatives killed.")
        else:
            raise CommandError("Autorun derivatives not running.", 'supervisor', 'killAutorunDerivatives')

    def stop_graph(self, do_save=False, do_derivatives=False, booters_stop_timeout=30):
        '''
        Stops the graph
        '''
        self.r.xadd("booter", {
                        'command': 'stopGraph', 
                        'log_level': self.command_log_level})
        # Kill child processes (nodes)
        self.r.xadd("graph_status", {'status': self.state[5]})
        self.kill_nodes()

        # Get booter count by status
        get_booter_count_by_status = lambda status_suffix: len([machine for machine, status in self.booter_status_dict.items() if status.endswith(status_suffix)])

        num_booters_stopping, num_booters_stopped = -1, -1 # Initialize to invalid values, make sure to wait for at least one iteration
        
        # Wait for booter to handle stopGraph command
        booters_handle_stop_command_start = time.time()
        while time.time() - booters_handle_stop_command_start < 3 and num_booters_stopping + num_booters_stopped < len(self.booter_status_dict):
            self.checkBooter()
            num_booters_stopping = get_booter_count_by_status('graph stopping')
            num_booters_stopped = get_booter_count_by_status('graph stopped successfully')

            time.sleep(1)

        # Log the number of booters handling stopGraph command (in stopping and stopped states)
        logging_message = f"Booters handling stopGraph command ({num_booters_stopped + num_booters_stopping} / {len(self.booter_status_dict)}): {num_booters_stopping} stopping, {num_booters_stopped} stopped."
        if num_booters_stopping + num_booters_stopped < len(self.booter_status_dict):
            logger.warning(logging_message)
        else:
            logger.info(logging_message)
        
        # Wait for booters to finish stopping
        booters_stop_wait_start = time.time()
        while (time.time() - booters_stop_wait_start < booters_stop_timeout or booters_stop_timeout < 0) and num_booters_stopped < len(self.booter_status_dict):
            self.checkBooter()
            num_booters_stopped = get_booter_count_by_status('graph stopped successfully')
            time.sleep(1)

        if num_booters_stopped == len(self.booter_status_dict): # All booters stopped successfully
            logger.info(f"Booters stopped successfully!")
        else: # Some booters did not stop successfully (still stopping or errored out)
            logger.warning(f"Booters did not stop successfully within timeout. Booter statuses: {self.booter_status_dict}")

        if do_save:
            # Save the .rdb file.
            self.r.xadd("supervisor_status", {"status": "Saving rdb"})
            logger.info("Saving RDB file...")
            self.r.save()
            save_filepath = os.path.join(self.save_path_rdb, self.rdb_filename)
            logger.info(f"RDB file saved as {save_filepath}")

            # Store info about the save.
            last_save_info = {
                "filepath": save_filepath,
                "timestamp": self.r.lastsave().timestamp(),
            }
            self.r.xadd("last_saved_rdb", last_save_info)

            # Set new rdb filename (to avoid overwriting what we just saved)
            self.rdb_filename =  'idle_' + datetime.now().strftime(r'%y%m%dT%H%M') + '.rdb'
            self.update_rdb_save_configs(rdb_filename=self.rdb_filename)

        if do_derivatives:
            if self.model:
                # Run derivatives.
                logger.info("Starting auto-run derivatives...")
                self.start_autorun_derivatives()

    def kill_nodes(self, node_list=None):
        '''
        Kills child processes
        '''

        def kill_proc_tree(pid, sig=signal.SIGTERM, include_parent=True):
            """
            Kill a process tree (including grandchildren) with signal "sig"
            """
            parent = psutil.Process(pid)
            children = parent.children(recursive=False)
            if include_parent:
                children.append(parent)
            for p in children:
                try:
                    p.send_signal(sig)
                except psutil.NoSuchProcess:
                    pass
        
        if node_list is None:
            node_list = list(self.child_nodes.keys())

        for node, proc in self.child_nodes.items():
            if node in node_list:
                try:
                    # check if process exists
                    os.kill(proc.pid, 0)
                except OSError:
                    self.logger.warning(f"'{node}' (pid: {proc.pid})"
                                            " isn't running and may have crashed")
                    self.child_nodes[node] = None
                    node_list.remove(node)
                else:
                    # process is running
                    # send SIGINT
                    kill_proc_tree(proc.pid, signal.SIGINT)
                    try:
                        # check if it terminated
                        proc.communicate(timeout=15)
                    except subprocess.TimeoutExpired:
                        self.logger.warning(f"Could not stop '{node}' "
                                                f"(pid: {proc.pid}) using SIGINT")
                        # if not, send SIGKILL
                        kill_proc_tree(proc.pid, signal.SIGKILL)
                        try:
                            # check if it terminated
                            proc.communicate(timeout=15)
                        except subprocess.TimeoutExpired:
                            pass  # delay error message until after the loop
                        else:
                            self.logger.info(f"Killed '{node}' "
                                                f"(pid: {proc.pid}) using SIGKILL")
                            self.child_nodes[node] = None
                            node_list.remove(node)
                    else:
                        self.logger.info(f"Stopped '{node}' "
                                            f"(pid: {proc.pid}) using SIGINT")
                        self.child_nodes[node] = None
                        node_list.remove(node)
        # remove killed processes from self.children
        self.child_nodes = {
            n: p
            for n, p in self.child_nodes.items() if p is not None
        }
        # raise an error if nodes are still running
        if node_list:
            message = ', '.join(node_list)
            self.logger.exception('Could not kill these nodes: '
                                    f'{message}')
            
    def run_derivatives(self, derivative_names):
        '''
        Runs a list of derivatives
        '''

        # for later logging of method outcomes
        started_derivatives = []
        failed_derivatives = {}

        # first check for valid derivatives
        for derivative in derivative_names:
            if derivative not in self.model['derivatives']:
                failed_derivatives[derivative] = 'not in graph'

        derivative_names = [d for d in derivative_names if d not in failed_derivatives]

        self.r.xadd("booter", {
                        'command': 'runDerivatives',
                        'derivatives': ','.join(derivative_names),
                        'log_level': self.command_log_level})

        # loop through derivatives and start each if able
        for derivative in derivative_names:
            # only attempt to run derivatives specified for this machine
            if self.model['derivatives'][derivative]['machine'] == self.machine:
                # check if derivative is already running
                if derivative in self.derivative_threads:
                    if self.derivative_threads[derivative].is_alive():
                        failed_derivatives[derivative] = 'already running'
                # make sure derivative is not already running
                if derivative not in failed_derivatives:
                    # generate a stop event for this derivative
                    self.derivative_stop_events[derivative] = Event()
                    # start the derivative
                    derivative_thread = RunDerivative(
                        derivative_info=self.model['derivatives'][derivative],
                        host=self.host,
                        port=self.port,
                        stop_event=self.derivative_stop_events[derivative])
                    derivative_thread.start()
                    # add the derivative to the list of running derivatives
                    self.derivative_threads[derivative] = derivative_thread
                    started_derivatives.append(derivative)

        if started_derivatives:
            logger.info(f"Started derivative(s): {started_derivatives}")

        if failed_derivatives:
            raise CommandError(f"Derivative(s) failed to start: {failed_derivatives}", 'supervisor', 'runDerivative')

    def kill_derivatives(self, derivative_names):
        '''
        Kills a list of derivatives
        '''

        # for later logging of method outcomes
        killed_derivatives = []
        failed_derivatives = {}

        # first check for valid derivatives
        for derivative in derivative_names:
            if derivative not in self.model['derivatives']:
                failed_derivatives[derivative] = 'not in graph'

        derivative_names = [d for d in derivative_names if d not in failed_derivatives]

        self.r.xadd("booter", {
                        'command': 'killDerivatives',
                        'derivatives': ','.join(derivative_names),
                        'log_level': self.command_log_level})

        # loop through derivatives and kill each if able
        for derivative in derivative_names:
            # check if derivative in graph
            if derivative in self.model['derivatives']:
                # only kill derivatives on this machine
                if self.model['derivatives'][derivative]['machine'] == self.machine:
                    # check if derivative is running
                    if derivative in self.derivative_threads:
                        # set the stop event for this derivative
                        self.derivative_stop_events[derivative].set()
                        # clear derivative and event instances
                        del self.derivative_stop_events[derivative]
                        del self.derivative_threads[derivative]
                        killed_derivatives.append(derivative)
                    else:
                        # derivative is not running
                        failed_derivatives[derivative] = 'not running'
            else:
                # derivative is not in graph
                failed_derivatives[derivative] = 'not in graph'
        
        if killed_derivatives:
            logger.info(f"Killed derivative(s): {killed_derivatives}")

        if failed_derivatives:
            raise CommandError(f"Derivative(s) failed to kill: {failed_derivatives}", 'supervisor', 'killDerivative')

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
                nickname_decoded = nickname.decode("utf-8")
                if nickname_decoded in self.model["nodes"] or nickname_decoded in self.model["derivatives"]:
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
                        f"There is no {nickname_decoded} nickname in the supergraph, skipped all parameter updates",
                        self.graph_file)
        else:
            raise GraphError(
                "Could not update graph parameters since no graph has been loaded yet",
                self.graph_file)

        # if we make it out of the above loop without error, then the parameter update is valid, so overwrite the existing model
        for nickname in new_params:
            nickname_decoded = nickname.decode("utf-8")
            nickname_params = json.loads(new_params[nickname].decode())
            for param, value in nickname_params.items():
                if nickname_decoded in self.model["nodes"]:
                    self.model["nodes"][nickname_decoded]["parameters"][param] = value
                elif nickname_decoded in self.model["derivatives"]:
                    self.model["derivatives"][nickname_decoded]["parameters"][param] = value

        # write the new supergraph
        model_pub = json.dumps(self.model)
        payload = {
            "data": model_pub
        }
        self.r.xadd("supergraph_stream", payload)
        self.r.xadd("booter", {
                        'command': 'loadGraph',
                        'graph': model_pub,
                        'log_level': self.command_log_level})
        logger.info("Supergraph updated successfully")
        

    def save_rdb(self):
        '''
        Saves an RDB file of the current database
        '''
        # Save rdb file
        self.r.save()
        logger.info(f"RDB data saved to file: {self.rdb_filename}")

    def flush_db(self):
        '''
        Flushes the RDB
        '''
        # Flush database
        self.r.flushdb()

        # Set new rdb filename (to avoid overwriting what we just saved)
        self.rdb_filename = 'idle_' + datetime.now().strftime(r'%y%m%dT%H%M') + '.rdb'
        self.update_rdb_save_configs(rdb_filename=self.rdb_filename)

        # New RDB, so need to reset graph status
        self.r.xadd("graph_status", {'status': self.state[5]})

    def make(self, graph=None, node=None, derivative=None, module=None):
        '''
        Makes nodes and derivatives, defaults to all unless graph, node, or derivative is specified
        '''
        self.check_graph_not_running(cmd='make')

        booter_cmd = {'command': 'make', 'log_level': self.command_log_level}
        proc_cmd = ['make', '-j']

        if (graph == "true" or graph == "1"):
            if self.model:
                proc_cmd += [f'graph="{self.graph_file}"']
                booter_cmd['graph'] = self.graph_file
            else:
                raise CommandError("No graph loaded, cannot make graph", 'supervisor', 'make')
        elif graph is not None:
            proc_cmd += [f'graph="{graph}"']
            booter_cmd['graph'] = graph

        if node is not None:
            proc_cmd += [f'node="{node}"']
            booter_cmd['node'] = node

        if derivative is not None:
            proc_cmd += [f'derivative="{derivative}"']
            booter_cmd['derivative'] = derivative

        if module is not None:
            proc_cmd += [f'module="{module}"']
            booter_cmd['module'] = module        

        self.r.xadd("booter", booter_cmd)

        p_make = subprocess.run(proc_cmd,
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

    def ping(self):
        '''
        Instructs supervisor to ping booters
        '''
        # send the ping instruction to booters
        self.r.xadd("booter", {
                        'command': 'ping', 
                        'log_level': self.command_log_level})

        # wait for booters to respond
        booter_ping_request_id = '$'
        booter_ping_times = {}
        got_ping = False
        while True:

            # wait for a booter to request a ping
            booter_to_ping = self.r.xread({self.BOOTER_PING_REQUEST_STREAM: booter_ping_request_id}, block=1000, count=1)

            # if we have a response
            if booter_to_ping:
                booter_ping_request_id, booter_ping_request_entry = booter_to_ping[0][1][0]
                # get the machine we're currently pinging
                machine_to_ping = booter_ping_request_entry[b'machine'].decode('utf-8')
                # get start time of the ping
                start_timestamp = time.monotonic_ns()
                # send the ping request
                booter_ping_response_id = self.r.xadd(self.BOOTER_PING_STREAM, {'machine': machine_to_ping})
                # wait for the ping response
                ping_response = self.r.xread(
                    {self.BOOTER_PING_STREAM: booter_ping_response_id},
                    block=1000,
                    count=1)
                # if we have a response
                if ping_response:
                    # get the end time of the ping
                    end_timestamp = time.monotonic_ns()
                    # get the response
                    booter_ping_response_id, ping_response_entry = ping_response[0][1][0]
                    # guarantee that the response is from the machine we pinged
                    if ping_response_entry[b'machine'].decode('utf-8') == machine_to_ping:
                        # calculate the round trip time
                        round_trip_time = end_timestamp - start_timestamp
                        # log the round trip time
                        booter_ping_times[machine_to_ping] = {
                            'round_trip_time_ns': round_trip_time,
                            'supervisor_booter_timestamps_ns': [
                                int(sum([start_timestamp, end_timestamp])/2),
                                int(ping_response_entry[b'timestamp_ns'])]}
                        got_ping = True
                    else:
                        logger.warning(f"Booter {ping_response_entry[b'machine'].decode('utf-8')}"
                                        f" responded to ping when {machine_to_ping} was expected")
                else:
                    logger.warning(f"Booter {machine_to_ping} did not respond to ping")
            else:
                if got_ping:
                    logger.info(f"Booter ping times: {booter_ping_times}")
                    self.r.xadd("ping_times", {machine: json.dumps(times) for machine, times in booter_ping_times.items()})
                else:
                    logger.warning("No booters responded to ping")
                break


    def terminate(self, sig, frame):
        logger.info('SIGINT received, Exiting')
        self.cleanup()

    def cleanup(self):
        # attempt to kill nodes
        try:
            self.kill_nodes()
        except Exception as exc:
            logger.warning(f"Could not kill nodes before exiting. Exiting anyway. {repr(exc)}")

        # attempt to kill derivatives
        try:
            for event in self.derivative_stop_events.values():
                event.set()
        except Exception as exc:
            logger.warning(f"Could not kill autorun derivatives before exiting. Exiting anyway. {repr(exc)}")

        # attempt to post an exit message to Redis
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
                and other information needed to execute the command.
        '''
        self.set_command_log_level_to_default()
        log_level = data.get(b'log_level')
        if log_level is not None:
            self.command_log_level = log_level.decode()
        
        cmd = (data[b'commands']).decode("utf-8").lower()

        if cmd in ["loadgraph", "startgraph"]:
            if self.child_nodes:
                raise GraphError("Graph already running, run stopGraph before initiating another graph", self.graph_file)

            if b'rdb_filename' in data:
                rdb_filename = data[b'rdb_filename'].decode("utf-8")
            else:
                rdb_filename = None

            if b'file' in data:
                logger.info(f"{cmd} command received with file")

                file = data[b'file'].decode("utf-8")
                if data.get(b'relative'):
                    file = os.path.join(self.BRAND_ROOT_DIR, file)
                    
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
                    raise GraphError("No graph provided with startGraph command and no graph previously loaded",
                    self.graph_file)
                self.start_graph()
            else: # command was loadGraph with insufficient inputs
                raise GraphError("Error loading graph, a graph YAML must be provided with the 'file' key or a graph dictionary must be provided with the 'graph' key", self.graph_file)
        elif cmd == "updateparameters":
            logger.info("Update parameters command received")
            new_params = {k:data[k] for k in data if k not in [b"commands", b"log_level"]}
            self.update_params(new_params)
        elif cmd == "stopgraph":
            logger.info("Stop graph command received")
            do_save = bool(int(data.get(b"do_save", False)))
            do_derivatives = bool(int(data.get(b"do_derivatives", False)))
            timeout = int(data.get(b"timeout", 30))
            self.stop_graph(do_save=do_save, do_derivatives=do_derivatives, booters_stop_timeout=timeout)
        elif cmd == "stopchildprocess":
            logger.info("Stop child process command received")
            if b"nickname" not in data:
                raise CommandError("stopChildProcess command requires a 'nickname' key", 'supervisor', 'stopChildProcess')
            nickname = data[b"nickname"].decode('utf-8')
            # Forward the command to booter as well
            self.r.xadd("booter", {
                            "command": "stopChildProcess",
                            "nickname": nickname,
                            "log_level": self.command_log_level})
            # Kill the process if it is here
            if nickname in self.child_nodes:
                self.kill_nodes([nickname])
            elif nickname in self.derivative_threads:
                self.kill_derivatives([nickname])
        elif cmd == "saverdb":
            logger.info("Save RDB command received")
            self.save_rdb()
        elif cmd == "flushredis":
            logger.info("Flush Redis command received")
            self.flush_db()
        elif cmd == "setdatadir":
            rel_path = os.path.relpath(self.save_path, self.data_dir)
            if b'path' in data:
                logger.info(f"Set data directory command received, setting to {data[b'path'].decode('utf-8')}")
                self.data_dir = data[b'path'].decode('utf-8')
            else:
                logger.info(f"Set data directory command received, setting to the default {self.DEFAULT_DATA_DIR}")
                self.data_dir = self.DEFAULT_DATA_DIR
            self.save_path = os.path.join(self.data_dir, rel_path)
            self.save_path_rdb = os.path.join(self.save_path, 'RDB')
            self.update_rdb_save_configs(rdb_save_path=self.save_path_rdb)
        elif cmd == "setrdbfilename":
            if b'filename' in data:
                self.rdb_filename = data[b'filename'].decode('utf-8')
                logger.info(f"Set data filename command received, setting to {self.rdb_filename}")

                self.update_rdb_save_configs(rdb_filename=self.rdb_filename)
            else:
                logger.info(f"Set data filename command received, no new filename specified, keeping the default filename: {self.rdb_filename}")
        elif cmd == "killautorunderivatives":
            logger.info("Kill autorun derivatives command received")
            self.kill_autorun_derivatives()
        elif cmd in ["runderivative", "runderivatives"]:
            logger.info("Run derivative(s) command received")
            if b'derivatives' in data:
                derivatives = data[b'derivatives']
            elif b'derivative' in data:
                derivatives = data[b'derivative']
            else:
                raise CommandError("runDerivative(s) command requires a 'derivative' or 'derivatives' key", 'supervisor', 'runDerivatives')

            derivatives = derivatives.decode('utf-8').split(',')
            self.run_derivatives(derivatives)
        elif cmd in ["killderivative", "killderivatives"]:
            logger.info("Kill derivative(s) command received")
            if b'derivatives' in data:
                derivatives = data[b'derivatives']
            elif b'derivative' in data:
                derivatives = data[b'derivative']
            else:
                raise CommandError("killDerivative(s) command requires a 'derivative' or 'derivatives' key", 'supervisor', 'killDerivatives')
            
            derivatives = derivatives.decode('utf-8').split(',')
            self.kill_derivatives(derivatives)
        elif cmd == "make":
            logger.info("Make command received")
            graph = data[b'graph'].decode('utf-8') if b'graph' in data else None
            node = data[b'node'].decode('utf-8') if b'node' in data else None
            derivative = data[b'derivative'].decode('utf-8') if b'derivative' in data else None
            module = data[b'module'].decode('utf-8') if b'module' in data else None
            self.make(graph=graph, node=node, derivative=derivative, module=module)
        elif cmd == "setderivativecontinueonerror":
            if b'continue_on_error' in data:
                if data[b'continue_on_error'] not in [b'0', b'1']:
                    raise CommandError("continue_on_error must be 0 or 1", 'supervisor', 'setDerivativeContinueOnError')
                self.derivative_continue_on_error = bool(int(data[b'continue_on_error']))
                self.r.xadd("booter", {
                                'command': 'setDerivativeContinueOnError',
                                'continue_on_error': int(self.derivative_continue_on_error),
                                'log_level': self.command_log_level})
                logger.info(f"Set derivative continue on error to {self.derivative_continue_on_error}")
        elif cmd == "setloglevel":
            if b'level' in data:
                self.persistent_log_level = data[b'level'].decode()
        elif cmd == "ping":
            logger.info("Ping command received")
            self.ping()
        else:
            logger.warning("Invalid command")


    def checkBooter(self):
        '''
        Checks status of booter nodes
        '''
        statuses = self.r.xrange('booter_status', '('+self.booter_status_id, '+')
        if len(statuses) > 0:
            for entry in statuses:
                self.booter_status_id = entry[0].decode('utf-8')
                status = entry[1][b'status'].decode('utf-8')
                if status in ['NodeError', 'GraphError', 'CommandError']:
                    # get messages starting from the error
                    raise BooterError(
                        f"{entry[1][b'machine'].decode('utf-8')} machine encountered an error: {entry[1][b'message'].decode('utf-8')}",
                        entry[1][b'machine'].decode('utf-8'),
                        self.graph_file,
                        entry[1][b'traceback'].decode('utf-8'),
                        status)
                else:
                    self.booter_status_dict[entry[1][b'machine'].decode('utf-8')] = status

    def handle_redis_connection_error(self, exc):
        logger.error('Could not connect to Redis: ' + repr(exc))
        self.cleanup()

    def handle_graph_error(self, exc):
        # if the graph has an error, it was never executed, so log it
        self.r.xadd("graph_status",
            {'status': self.state[2],
            'message': str(exc),
            'traceback': 'Supervisor ' + traceback.format_exc()})
        if self.child_nodes:
            status = self.r.xrevrange("graph_status", '+', '-', count=2)
            self.r.xadd("graph_status",
                {'status': status[-1][1][b'status']})
        else:
            self.r.xadd("graph_status", {'status': self.state[5]})
        graph = 'None' if exc.graph is None else exc.graph
        logger.error(f"Graph operation failed for {graph} graph")
        logger.error(str(exc))

    def handle_node_error(self, exc):
        # if a node has an error, stop the graph
        self.r.xadd("graph_status",
            {'status': self.state[2],
            'message': str(exc),
            'traceback': 'Supervisor ' + traceback.format_exc()})
        logger.error(f"Error with the {exc.node} node in the {exc.graph} graph")
        logger.error(str(exc))
    
    def handle_booter_error(self, exc):
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

    def handle_derivative_error(self, exc):
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
        if self.child_nodes:
            status = self.r.xrevrange("graph_status", '+', '-', count=2)
            self.r.xadd("graph_status",
                {'status': status[-1][1][b'status']})
        else:
            self.r.xadd("graph_status", {'status': self.state[5]})

        logger.error(f"Error with the {exc.derivative} derivative")
        logger.error(str(exc))
        if exc.process.stderr is not None and len(exc.process.stderr) > 0:
            logger.debug(exc.process.stderr.decode('utf-8'))

    def handle_command_error(self, exc, redis_available=True):
        # if a command has an error, then note that in the RDB
        if redis_available:
            self.r.xadd("supervisor_status",
                {"status": "Command error",
                "message": str(exc),
                "traceback": "Supervisor " + traceback.format_exc() + '\nDetails:\n' + exc.details})

        logger.error(f"Error executing {exc.command} command.")
        logger.error(str(exc))

        if redis_available:
            self.r.xadd("supervisor_status", {"status": "Listening for commands"})

    def handle_exception(self, exc):
        self.r.xadd("supervisor_status",
                    {"status": "Unhandled exception",
                    "message": str(exc),
                    "traceback": "Supervisor " + traceback.format_exc()})
        logger.exception(f'Could not execute command. {repr(exc)}')
        self.r.xadd("supervisor_status", {"status": "Listening for commands"})

    def main(self):
        last_id = '$'
        logger.info('Listening for commands')
        self.r.xadd("supervisor_status", {"status": "Listening for commands"})
        while True:

            self.set_command_log_level_to_default()

            for derivative in list(self.derivative_threads.keys()):
                if not self.derivative_threads[derivative].is_alive():
                    del self.derivative_threads[derivative]
                    del self.derivative_stop_events[derivative]

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
                self.handle_redis_connection_error(exc)

            except GraphError as exc:
                self.handle_graph_error(exc)

            except NodeError as exc:
                self.handle_node_error(exc)

            except BooterError as exc:
                self.handle_booter_error(exc)

            except DerivativeError as exc:
                self.handle_derivative_error(exc)

            except CommandError as exc:
                self.handle_command_error(exc)

            except Exception as exc:
                self.handle_exception(exc)
