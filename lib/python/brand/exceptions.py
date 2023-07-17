import subprocess

# brand-specific exceptions
class GraphError(Exception):
    def __init__(self, message='', graph=''):
        super().__init__(message)
        self.graph = graph

    def __repr__(self):
        return f"GraphError(message={str(self)}, graph={self.graph})"
    
class NodeError(Exception):
    def __init__(self, message='', graph='', node=''):
        super().__init__(message)
        self.graph = graph
        self.node = node

    def __repr__(self):
        return f"NodeError(message={str(self)}, graph={self.graph}, node={self.node})"

class BooterError(Exception):
    def __init__(self, message='', machine='', graph='', booter_tb='', source_exc=''):
        super().__init__(message)
        self.machine = machine
        self.graph = graph
        self.booter_tb = booter_tb
        self.source_exc = source_exc
    
    def __repr__(self):
        return f"BooterError(message={str(self)}, machine={self.machine}, graph={self.graph}, booter_tb={self.booter_tb}, source_exc={self.source_exc})"

class DerivativeError(Exception):
    def __init__(self, message='', derivative='', graph='', process:subprocess.CompletedProcess=subprocess.CompletedProcess([], 0)):
        super().__init__(message)
        self.derivative = derivative
        self.graph = graph
        self.process = process

class CommandError(Exception):
    def __init__(self, message='', process='', command='', details=''):
        super().__init__(message)
        self.process = process
        self.command = command
        self.details = details

class RedisError(Exception):
    pass