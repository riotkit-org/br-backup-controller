"""
Generic Kubernetes methods for building Kubernetes transports
"""
import json
import os
import time
from typing import List, Callable
import yaml
from tempfile import TemporaryDirectory

from kubernetes.client import CoreV1Api, V1PodList, V1Pod, V1ObjectMeta, V1Scale, V1ScaleSpec, AppsV1Api, ApiException
from kubernetes.stream.ws_client import WSClient, ERROR_CHANNEL
from rkd.api.inputoutput import IO
from kubernetes import client
from kubernetes.stream import stream

from ..exception import KubernetesError
from ..fs import FilesystemInterface


class ExecResult(object):
    """
    Result of operation like `kubectl exec`
    """

    _process: WSClient
    _io: IO

    def __init__(self, process: WSClient, io: IO):
        self._process = process
        self._io = io

    def read(self) -> str:
        """
        Wait till process exit, then read output
        """

        self._process.run_forever()
        return self._process.read_all()

    def watch(self, printer: Callable) -> None:
        """
        Watches process for output
        """

        while self._process.is_open():
            self._process.update(timeout=1)

            out = [
                self._process.readline_stdout() if self._process.peek_stdout() else "",
                self._process.readline_stderr() if self._process.peek_stderr() else ""
            ]

            for line in out:
                if line:
                    printer(line)

    def is_still_running(self) -> bool:
        return self._process.is_open()

    def has_exited_with_success(self) -> bool:
        if self.is_still_running():
            return True

        errors = yaml.load(self._process.read_channel(ERROR_CHANNEL), yaml.FullLoader)

        if errors and "details" in errors:
            for error in errors['details']['causes']:
                if "reason" not in error:
                    self._io.error(error['message'])
                    return False

                if error['reason'] == 'ExitCode' and int(error['message']) > 0:
                    self._io.error(f"Process inside POD exited with status {int(error['message'])}")
                    return False

        return True


def pod_exec(pod_name: str, namespace: str, cmd: List[str], io: IO) -> ExecResult:
    """
    Execute a command inside a POD
    """

    return ExecResult(
        stream(
            client.CoreV1Api().connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            command=cmd,
            stderr=True,
            stdout=True,
            stdin=False,
            _preload_content=False
        ),
        io
    )


def find_pod_name(api: CoreV1Api, selector: str, namespace: str, io: IO) -> str:
    """
    Returns a POD name

    :raises: When no matching POD found
    """

    pods: V1PodList = api.list_namespaced_pod(namespace,  label_selector=selector, limit=1)

    if len(pods.items) == 0:
        raise Exception(f'No pods found matching selector {selector} in {namespace} namespace')

    pod: V1Pod = pods.items[0]
    pod_metadata: V1ObjectMeta = pod.metadata

    io.debug(f"Found POD name: '{pod_metadata.name}' in namespace '{namespace}'")

    return pod_metadata.name


def wait_for_pod_to_be_ready(api: CoreV1Api, pod_name: str, namespace: str, io: IO, timeout: int = 120):
    """
    Waits for POD to reach a valid state

    :raises: When timeout hits
    """

    io.debug("Waiting for POD to be ready...")

    for i in range(0, timeout):
        pod: V1Pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)

        if pod.status.phase in ["Ready", "Healthy", "True", "Running"]:
            _wait_for_pod_containers_to_be_ready(api, pod_name, namespace, timeout, io)
            io.info(f"POD entered '{pod.status.phase}' state")
            time.sleep(1)

            return True

        io.debug(f"Pod not ready. Status: {pod.status.phase}")
        time.sleep(1)

    raise KubernetesError.from_timed_out_waiting_for_pod(pod_name, namespace)


def _wait_for_pod_containers_to_be_ready(api: CoreV1Api, pod_name: str, namespace: str, timeout: int, io: IO):
    """
    POD can be running, but containers could be still initializing - this method waits for containers
    """

    for i in range(0, timeout):
        pod: V1Pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)

        if all([(c.state.running and not c.state.waiting and not c.state.terminated)
                for c in pod.status.container_statuses]):
            io.info("All containers in a POD have started")
            return


def scale_resource(api: AppsV1Api, name: str, namespace: str, replicas: int, io: IO):
    """
    Scale down given Deployment/ReplicationController/StatefulSet
    """

    io.info(f"Scaling deployment/{name} in {namespace} namespace to replicas '{replicas}'")
    scale_spec = V1Scale(
        metadata=V1ObjectMeta(name=name, namespace=namespace),
        spec=V1ScaleSpec(
            replicas=replicas
        )
    )
    api.replace_namespaced_deployment_scale(name, namespace, scale_spec)

    # then wait for it to be applied
    for i in range(0, 3600):
        deployment_as_dict = json.loads(api.read_namespaced_deployment(name=name, namespace=namespace,
                                                                       _preload_content=False).data)

        current_replicas_num = int(deployment_as_dict['spec']['replicas'])

        if current_replicas_num == int(replicas):
            io.info(f"POD's controller scaled to {replicas}")
            return

        io.debug(f"Waiting for cluster to scale POD's controller to {replicas}, currently: {current_replicas_num}")
        time.sleep(1)

    raise KubernetesError.cannot_scale_resource(name, namespace, replicas)


def create_pod(api: CoreV1Api, pod_name: str, namespace, specification: dict, io: IO):
    io.info(f"Creating temporary POD '{pod_name}'")
    specification['metadata']['name'] = pod_name

    try:
        api.create_namespaced_pod(namespace=namespace, body=specification)

    except ApiException as e:
        if e.reason == "Conflict" and "AlreadyExists" in str(e.body):
            raise KubernetesError.from_pod_creation_conflict(pod_name) from e

        raise e


class KubernetesPodFilesystem(FilesystemInterface):
    io: IO
    pod_name: str
    namespace: str

    def __init__(self, pod_name: str, namespace: str, io: IO):
        self.io = io
        self.pod_name = pod_name
        self.namespace = namespace

    def _exec(self, cmd: List[str], msg: str, exit_code_hack: bool = False):
        if exit_code_hack:
            cmd = ["/bin/sh", "-c", (" ".join(cmd)) + " && echo '@<br-exit-ok>'"]

        proc = pod_exec(self.pod_name, self.namespace, cmd, self.io)
        result = proc.read()

        assert proc.has_exited_with_success(), f"{msg}. {result}"

        if exit_code_hack:
            assert "@<br-exit-ok>" in result, f"Process exited with failure. Output: {result}"

    def force_mkdir(self, path: str):
        self._exec(["mkdir", "-p", path], "mkdir inside POD failed, cannot create directory", exit_code_hack=True)

    def download(self, url: str, destination_path: str):
        self._exec(
            ["curl", "-s", "-L", "--output", destination_path, url],
            f"curl inside POD failed, cannot download file from '{url}' to '{destination_path}' path inside POD",
            exit_code_hack=True
        )

    def delete_file(self, path: str):
        try:
            self._exec(["rm", path], f"Cannot remove file inside POD at path '{path}' (inside POD)",
                       exit_code_hack=True)

        except AssertionError:
            self.io.debug(f"Cannot remove file inside POD at path '{path}' (inside POD). Maybe file does not exist")
            pass

    def link(self, src: str, dst: str):
        self._exec(["ln", "-s", src, dst], f"Cannot make symbolic link from '{src}' to '{dst}' (inside POD)",
                   exit_code_hack=True)

    def make_executable(self, path: str):
        self._exec(["chmod", "+x", path], f"Cannot make file executable at path '{path}' (inside POD)",
                   exit_code_hack=True)

    def copy_to(self, local_path: str, dst_path: str):
        process = stream(
            client.CoreV1Api().connect_get_namespaced_pod_exec,
            self.pod_name,
            self.namespace,
            command=["/bin/sh", "-c", f"cat - > {dst_path}"],
            stderr=True,
            stdout=True,
            stdin=True,
            _preload_content=False
        )

        with open(local_path, 'rb') as f:
            while process.is_open():
                process.update(timeout=1)
                process.write_stdin(f.read(1024*1024))

                if f.tell() == os.fstat(f.fileno()).st_size:
                    process.close()

    def pack(self, archive_path: str, src_path: str, files_list: List[str]):
        if not files_list:
            files_list = ["*", ".*"]

        self._exec(
            ["tracexit", f"env:PWD={src_path}", "tar", "-zcf", archive_path] + files_list,
            f"Cannot pack files from {src_path} into {archive_path} (inside POD)"
        )

    def unpack(self, archive_path: str, dst_path: str):
        self._exec(
            ["tar", "xf", archive_path, "--directory", dst_path],
            f"Cannot unpack files from '{archive_path}' to '{dst_path}'"
        )

    def file_exists(self, path: str) -> bool:
        try:
            self._exec(["test", "-f", path], f"File does not exist", exit_code_hack=True)

        except AssertionError:
            return False

        return True

    def find_temporary_dir_path(self) -> str:
        return TemporaryDirectory().name

    def move(self, src: str, dst: str):
        self._exec(
            ["mv", src, dst],
            f"Cannot move file {src} to {dst} inside POD",
            exit_code_hack=True
        )
