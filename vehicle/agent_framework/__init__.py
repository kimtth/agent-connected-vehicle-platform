from importlib import import_module
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
__version__ = "1.0.0"

Agent = import_module("agent_framework._agents").Agent
tool = import_module("agent_framework._tools").tool

__all__ = ["Agent", "tool", "__version__"]