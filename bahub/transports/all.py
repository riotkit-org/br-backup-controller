from .docker import Transport as DockerTransport
from .sh import Transport as ShellTransport
from .sidedocker import Transport as TemporaryDockerTransport


def transports():
    return [ShellTransport, DockerTransport, TemporaryDockerTransport]