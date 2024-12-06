"""
Booter is a daemon that starts and stops nodes according to commands
sent by Supervisor
"""
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

from threading import Event

from .derivative import RunDerivative
from .exceptions import CommandError, DerivativeError, GraphError, NodeError
from .redis import RedisLoggingHandler

DEFAULT_REDIS_IP = '127.0.0.1'
DEFAULT_REDIS_PORT = 6379


class Booter():
    """
    Booter is a class for starting and stopping nodes
    
    Attributes
    ----------
    model : dict
        Configuration set that defines the current supergraph
    children : dict
        Child processes that are currently running. Keys are node nicknames
        and values are subprocess.Popen instances for each running node.
    """

    def __init__(self,
                 machine,
                 host=DEFAULT_REDIS_IP,
                 port=DEFAULT_REDIS_PORT,
                 log_level=logging.INFO) -> None:
        """
        Booter starts and stops nodes according to commands received from
        the Supervisor via Redis

        Parameters
        ----------
        machine : str
            Unique name for this machine. To start a node with this Booter
            instance, you must specify a 'machine' parameter that matches the
            'machine' parameter for this Booter instance.
        host : str, optional
            Redis IP address, by default DEFAULT_REDIS_IP
        port : int, optional
            Redis port, by default DEFAULT_REDIS_PORT
        log_level : int, optional
            Logging level, by default logging.INFO
        """
        self.host = host
        self.port = port
        self.machine = machine
        # make a logger
        self.logger = logging.getLogger(f'booter-{self.machine}')
        coloredlogs.install(level=log_level, logger=self.logger)
        self._persistent_log_level = "DEBUG" # default log level, applied to all commands
        self._command_log_level = self._persistent_log_level  # log level for current command
        # instatiate run variables
        self.model = {}
        self.child_nodes = {}
        self.derivative_threads = {}
        self.derivative_stop_events = {}
        self.derivative_continue_on_error = True
        # set the base directory as the current working directory
        self.brand_base_dir = os.getcwd()
        # connect to Redis
        self.r = redis.Redis(self.host, self.port, socket_connect_timeout=1)
        # add a Redis logging handler
        self.redis_log_handler = RedisLoggingHandler(self.r, f'booter_{self.machine}')
        self.logger.addHandler(self.redis_log_handler)
        # register signal handler
        signal.signal(signal.SIGINT, self.terminate)
        # get ping-related streams
        self.booter_ping_stream = 'booter_ping'
        self.booter_ping_request_stream = 'booter_ping_request'


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
            self.redis_log_handler.setLevel(self._command_log_level)

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


    def get_node_executable(self, module, name):
        """
        Get the path to the node executable

        Parameters
        ----------
        module : str
            Path to the module in which the node is located
        name : str
            Name of the node

        Returns
        -------
        filepath : str
            Absolute path to the node executable
        """
        filepath = os.path.join(self.brand_base_dir, module, 'nodes', name,
                                f'{name}.bin')
        filepath = os.path.abspath(filepath)
        if not os.path.exists(filepath):
            raise NodeError(
                f'{name} executable was not found at {filepath}',
                self.model['graph_name'],
                name)
        return filepath

    def load_graph(self, graph: dict):
        """
        Load a new supergraph into Booter

        Parameters
        ----------
        graph : dict
            Dictionary containing the supergraph parameters
        """
        # load node information
        self.model = graph

        node_names = list(self.model['nodes'])
        for node, cfg in self.model['nodes'].items():
            if 'machine' in cfg and cfg['machine'] == self.machine:
                # get paths to node executables
                filepath = self.get_node_executable(cfg['module'], cfg['name'])
                self.model['nodes'][node]['binary'] = filepath

        deriv_names = list(self.model['derivatives'])
        for deriv, cfg in self.model['derivatives'].items():
            if 'machine' in cfg and cfg['machine'] == self.machine:
                # verify the given filepath exists
                if not os.path.exists(cfg['filepath']):
                    raise DerivativeError('Derivative filepath does not exist',
                                          deriv,
                                          self.model['graph_name'])

        self.logger.info(f'Loaded graph with nodes {node_names} and derivatives {deriv_names}')
        self.r.xadd("booter_status", {"machine": self.machine, "status": f"{self.model['graph_name']} graph loaded successfully"})

    def start_graph(self):
        """
        Start the nodes in the graph that are assigned to this machine
        """
        if self.model:
            for node, cfg in self.model['nodes'].items():
                # specify defaults
                cfg.setdefault('root', True)
                # run the node if it is assigned to this machine
                if 'machine' in cfg and cfg['machine'] == self.machine:
                    node_stream_name = cfg["nickname"]
                    # build CLI command
                    args = []
                    if not cfg['root'] and 'SUDO_USER' in os.environ:
                        # run nodes as the current user, not root
                        args += [
                            'sudo', '-u', os.environ['SUDO_USER'], '-E', 'env',
                            f"PATH={os.environ['PATH']}"
                        ]
                    args += [
                        cfg['binary'], '-n', node_stream_name, '-i', self.host,
                        '-p',
                        str(self.port)
                    ]
                    # root permissions are needed to set real-time priority
                    if 'run_priority' in cfg:  # if priority is specified
                        priority = cfg['run_priority']
                        if priority:  # if priority is not None or empty
                            chrt_args = ['chrt', '-f', str(int(priority))]
                            args = chrt_args + args
                    if 'cpu_affinity' in cfg:  # if affinity is specified
                        affinity = cfg['cpu_affinity']
                        if affinity:  # if affinity is not None or empty
                            taskset_args = ['taskset', '-c', str(affinity)]
                            args = taskset_args + args
                    p = subprocess.Popen(args)
                    self.logger.debug(' '.join(args))
                    self.child_nodes[node] = p

            self.r.xadd("booter_status", {"machine": self.machine, "status": f"{self.model['graph_name']} graph started successfully"})
        else:
            raise CommandError("No graph loaded", f'booter_{self.machine}', 'startGraph')

    def stop_graph(self):
        """
        Stop the nodes on this machine that correspond to the running graph
        """
        if 'graph_name' in self.model:
            graph = self.model['graph_name']
        else:
            graph = 'None'
        self.r.xadd("booter_status", {"machine": self.machine, "status": f"{graph} graph stopping"})
        self.kill_nodes()
        self.r.xadd("booter_status", {"machine": self.machine, "status": f"{graph} graph stopped successfully"})

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
            self.logger.info(f"Started derivative(s): {started_derivatives}")

        if failed_derivatives:
            raise CommandError(f"Derivative(s) failed to start: {failed_derivatives}", f'booter_{self.machine}', 'runDerivative')

    def kill_derivatives(self, derivative_names):
        '''
        Kills a list of derivatives
        '''
        # for later logging of method outcomes
        killed_derivatives = []
        failed_derivatives = {}

        # loop through derivatives and kill each if able
        for derivative in derivative_names:
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
        
        if killed_derivatives:
            self.logger.info(f"Killed derivative(s): {killed_derivatives}")
            
        if failed_derivatives:
            raise CommandError(f"Derivative(s) failed to kill: {failed_derivatives}", f'booter_{self.machine}', 'killDerivative')

    def make(self, graph=None, node=None, derivative=None, module=None):
        '''
        Makes nodes and derivatives, defaults to all unless graph, node, or derivative is specified
        '''
        # Run make

        proc_cmd = ['make', '-j']

        if graph is not None:
            proc_cmd += [f'graph="{graph}"']

        if node is not None:
            proc_cmd += [f'node="{node}"']

        if derivative is not None:
            proc_cmd += [f'derivative="{derivative}"']

        if module is not None:
            proc_cmd += [f'module="{module}"']

        proc_cmd += [f'machine="{self.machine}"']

        p_make = subprocess.run(proc_cmd,
                                capture_output=True)

        if p_make.returncode == 0:
            self.r.xadd("booter_status", {"machine": self.machine, "status": "Make completed successfully"})
            self.logger.info(f"Make completed successfully")
        elif p_make.returncode > 0:
            raise CommandError(
                f"Make returned exit code {p_make.returncode}.",
                f'booter_{self.machine}',
                'make',
                'STDOUT:\n' + p_make.stdout.decode('utf-8') + '\nSTDERR:\n' + p_make.stderr.decode('utf-8'))
        elif p_make.returncode < 0:
            self.logger.info(f"Make was halted during execution with return code {p_make.returncode}, {signal.Signals(-p_make.returncode).name}")

    def ping(self):
        '''
        Responds to ping requests from Supervisor
        '''
        # tell supervisor this machine requests a ping
        entry_id = self.r.xadd(self.booter_ping_request_stream, {"machine": self.machine})

        # get final ID of previous ms to ensure we xread the soonest possible supervisor reply
        entry_id = str(int(entry_id.split(b'-')[0])-1)+'-'+str(0xFFFFFFFFFFFFFFFF)

        # wait for a ping request directed to this machine:
        while True:

            request = self.r.xread({self.booter_ping_stream: entry_id}, block=1000, count=1)

            # if we have a response
            if request:
                entry_id, entry_data = request[0][1][0]
                # check if pinging this machine
                if entry_data[b'machine'].decode('utf-8') == self.machine:
                    # tell booter our current monotonic time
                    self.r.xadd(
                        self.booter_ping_stream,
                        {"machine": self.machine,
                         "timestamp_ns": time.monotonic_ns()})
                    break

                entry_id = entry_id.decode('utf-8')

            else:
                # if no response, log a warning and exit
                self.logger.warning("Ping request timed out, exiting command")
                break


    def parse_command(self, entry):
        """
        Parse an entry from the 'booter' stream and run the corresponding
        command

        Parameters
        ----------
        entry : dict
            An entry from the 'booter' stream containing a 'command' key
        """
        self.set_command_log_level_to_default()
        log_level = entry.get(b'log_level')
        if log_level is not None:
            self.command_log_level = log_level.decode()

        command = entry[b'command'].decode()
        self.logger.info(f'Received {command} command')

        if command == 'startGraph':
            if b'graph' in entry:
                graph_dict = json.loads(entry[b'graph'])
                self.load_graph(graph_dict)
            self.start_graph()
        elif command == 'loadGraph':
            graph_dict = json.loads(entry[b'graph'])
            self.load_graph(graph_dict)
        elif command == 'stopGraph':
            self.stop_graph()
        elif command == "stopChildProcess":
            if b"nickname" not in entry:
                raise CommandError("stopChildProcess command requires a 'nickname' key", f'booter_{self.machine}', 'stopChildProcess')
            nickname = entry[b"nickname"].decode('utf-8')
            # Kill the process if it is here
            if nickname in self.child_nodes:
                self.kill_nodes([nickname])
            elif nickname in self.derivative_threads:
                self.kill_derivatives([nickname])
        elif command == 'make':
            graph = entry[b'graph'].decode('utf-8') if b'graph' in entry else None
            node = entry[b'node'].decode('utf-8') if b'node' in entry else None
            derivative = entry[b'derivative'].decode('utf-8') if b'derivative' in entry else None
            module = entry[b'module'].decode('utf-8') if b'module' in entry else None
            self.make(graph=graph, node=node, derivative=derivative, module=module)
        elif command == 'startAutorunDerivatives':
            self.start_autorun_derivatives()
        elif command == 'killAutorunDerivatives':
            self.kill_autorun_derivatives()
        elif command in ["runDerivative", "runDerivatives"]:
            if b'derivatives' in entry:
                derivatives = entry[b'derivatives']
            elif b'derivative' in entry:
                derivatives = entry[b'derivative']
            else:
                raise CommandError("runDerivative(s) command requires a 'derivative' or 'derivatives' key", f'booter_{self.machine}', 'runDerivatives')

            derivatives = derivatives.decode('utf-8').split(',')
            self.run_derivatives(derivatives)
        elif command in ["killDerivative", "killDerivatives"]:
            if b'derivatives' in entry:
                derivatives = entry[b'derivatives']
            elif b'derivative' in entry:
                derivatives = entry[b'derivative']
            else:
                raise CommandError("killDerivative(s) command requires a 'derivative' or 'derivatives' key", f'booter_{self.machine}', 'killDerivatives')
            
            derivatives = derivatives.decode('utf-8').split(',')
            self.kill_derivatives(derivatives)
        elif command == "setDerivativeContinueOnError":
            if b'continue_on_error' in entry:
                if entry[b'continue_on_error'] not in [b'0', b'1']:
                    raise CommandError("continue_on_error must be 0 or 1", f'booter_{self.machine}', 'setDerivativeContinueOnError')
                self.derivative_continue_on_error = bool(int(entry[b'continue_on_error']))
                self.logger.info(f"Set derivative continue on error to {self.derivative_continue_on_error}")
        elif command == "setLogLevel":
            if b'level' in entry:
                self.persistent_log_level = entry[b'level'].decode()
        elif command == "ping":
            self.ping()


    def run(self):
        """
        Listen for commands on the booter stream and execute them. Catch
        and log any exceptions encountered when executing commands.
        """
        entry_id = '$'
        self.logger.info('Listening for commands')
        self.r.xadd("booter_status", {"machine": self.machine, "status": "Listening for commands"})
        while True:

            for derivative in list(self.derivative_threads.keys()):
                if not self.derivative_threads[derivative].is_alive():
                    del self.derivative_threads[derivative]
                    del self.derivative_stop_events[derivative]
                    
            try:
                streams = self.r.xread({'booter': entry_id},
                                       block=5000,
                                       count=1)
                if streams:
                    _, stream_data = streams[0]
                    entry_id, entry_data = stream_data[0]
                    self.parse_command(entry_data)

            except redis.exceptions.ConnectionError as exc:
                self.logger.error('Could not connect to Redis: ' + repr(exc))
                self.terminate()

            except (CommandError, DerivativeError, GraphError, NodeError) as exc:
                # if a node has an error, stop the graph and kill all nodes
                self.r.xadd("booter_status",
                    {'machine': self.machine,
                    'status': exc.__class__.__name__,
                    'message': str(exc),
                    'traceback': 'Booter ' + self.machine + ' ' + traceback.format_exc()})
                self.r.xadd("booter_status",
                    {'machine': self.machine, 'status': 'Listening for commands'})
                if exc is NodeError:
                    self.logger.error(f"Error with the {exc.node} node in the {exc.graph} graph")
                elif exc is GraphError:
                    self.logger.error(f"Error with the {exc.graph} graph")
                elif exc is DerivativeError:
                    self.logger.error(f"Error with the {exc.derivative} derivative in the {exc.graph} graph")
                elif exc is CommandError:
                    self.logger.error(f"Error with the {exc.command} command")
                self.logger.error(str(exc))

            except Exception as exc:
                self.r.xadd('booter_status',
                    {'machine': self.machine,
                    'status': 'Unhandled exception',
                    'message': str(exc),
                    'traceback': 'Booter ' + self.machine + ' ' + traceback.format_exc()})
                self.logger.exception(f'Could not execute command. {repr(exc)}')
                self.r.xadd("booter_status", {"machine": self.machine, "status": "Listening for commands"})

    def terminate(self, *args, **kwargs):
        """
        End this booter process when SIGINT is received
        """
        self.logger.info('SIGINT received, Exiting')

        # attempt to kill nodes
        try:
            self.kill_nodes()
        except Exception as exc:
            self.logger.warning(f"Could not kill nodes. Exiting anyway. {repr(exc)}")

        # attempt to kill derivatives
        try:
            for event in self.derivative_stop_events.values():
                event.set()
        except Exception as exc:
            self.logger.warning(f"Could not kill derivatives. Exiting anyway. {repr(exc)}")

        # attempt to post an exit message to Redis
        try:
            self.r.xadd("booter_status", {"machine": self.machine, "status": "SIGINT received, Exiting"})
        except Exception as exc:
            self.logger.warning(f"Could not write exit message to Redis. Exiting anyway. {repr(exc)}")
        sys.exit(0)


    def parse_booter_args():
        """
        Parse command-line arguments for Booter

        Returns
        -------
        args : Namespace
            Booter arguments
        """
        ap = argparse.ArgumentParser()
        ap.add_argument("-m",
                        "--machine",
                        required=True,
                        type=str,
                        help="machine on which this booter is running")
        ap.add_argument("-i",
                        "--host",
                        required=False,
                        type=str,
                        default=DEFAULT_REDIS_IP,
                        help="ip address of the redis server"
                        f" (default: {DEFAULT_REDIS_IP})")
        ap.add_argument("-p",
                        "--port",
                        required=False,
                        type=int,
                        default=DEFAULT_REDIS_PORT,
                        help="port of the redis server"
                        f" (default: {DEFAULT_REDIS_PORT})")
        ap.add_argument("-l",
                        "--log-level",
                        default=logging.INFO,
                        type=lambda x: getattr(logging, x),
                        help="Configure the logging level")
        args = ap.parse_args()
        return args
