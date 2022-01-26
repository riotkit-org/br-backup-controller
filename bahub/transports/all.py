from .docker import Transport as DockerTransport
from .sh import Transport as ShellTransport
from .docker_sidecontainer import Transport as TemporaryDockerTransport
from .kubernetes_podexec import Transport as KubernetesPodExecTransport
from .kubernetes_sidepod import Transport as KubernetesSidePodTransport


def transports():
    return [ShellTransport, DockerTransport, TemporaryDockerTransport,
            KubernetesPodExecTransport, KubernetesSidePodTransport]
