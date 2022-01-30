"""
Kubernetes POD EXEC transport
=============================

Performs `exec` operation into EXISTING, RUNNING POD to run a backup operation in-place.
"""

from typing import List
from kubernetes import config, client
from rkd.api.inputoutput import IO

from bahub.bin import RequiredBinary, copy_required_tools_from_controller_cache_to_target_env, \
    copy_encryption_keys_from_controller_to_target_env
from bahub.exception import ConfigurationError
from bahub.settings import BIN_VERSION_CACHE_PATH, TARGET_ENV_BIN_PATH, TARGET_ENV_VERSIONS_PATH
from bahub.transports.base import TransportInterface, create_backup_maker_command
from bahub.transports.kubernetes import KubernetesPodFilesystem, pod_exec, ExecResult, find_pod_name, \
    wait_for_pod_to_be_ready
from bahub.transports.sh import LocalFilesystem


class Transport(TransportInterface):
    _v1_core_api: client.CoreV1Api
    _v1_apps_api: client.AppsV1Api
    _process: ExecResult
    _binaries: List[RequiredBinary]

    _namespace: str
    _selector: str
    _io: IO

    def __init__(self, spec: dict, io: IO):
        super().__init__(spec, io)
        self._namespace = spec.get('namespace', 'default')
        self._selector = spec.get('selector', '')
        self._timeout = int(spec.get('timeout', 120))

        if not self._selector:
            raise ConfigurationError("'selector' for Kubernetes type transport cannot be empty")

    @staticmethod
    def get_specification_schema() -> dict:
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "oneOf": [
                {"required": ["namespace", "selector"]},
            ],
            "properties": {
                "selector": {
                    "type": "string",
                    "example": "my-label=myvalue",
                    "default": ""
                },
                "namespace": {
                    "type": "string",
                    "example": "prod",
                    "default": "default"
                },
                "timeout": {
                    "type": "string",
                    "example": 120,
                    "default": 120
                }
            }
        }

    @property
    def v1_core_api(self) -> client.CoreV1Api:
        if not hasattr(self, '_v1_core_api'):
            config.load_kube_config()  # todo: Add support for selecting cluster
            self._v1_core_api = client.CoreV1Api()

        return self._v1_core_api

    @property
    def v1_apps_api(self) -> client.AppsV1Api:
        if not hasattr(self, '_v1_apps_api'):
            config.load_kube_config()  # todo: Add support for selecting cluster
            self._v1_apps_api = client.AppsV1Api()

        return self._v1_apps_api

    def prepare_environment(self, binaries: List[RequiredBinary]) -> None:
        self._binaries = binaries

    def schedule(self, command: str, definition, is_backup: bool, version: str = "") -> None:
        """
        Runs a `kubectl exec` on already existing POD
        """

        pod_name = self._find_pod_name(self._selector, self._namespace)
        self._execute_in_pod_when_pod_will_be_ready(pod_name, command, definition, is_backup, version)

    def __exit__(self, exc_type, exc_val, exc_t) -> None:
        """
        Todo: Delete GPG keys from POD

        :param exc_type:
        :param exc_val:
        :param exc_t:
        :return:
        """
        pass

    def _execute_in_pod_when_pod_will_be_ready(self, pod_name: str, command: str, definition,
                                               is_backup: bool, version: str = ""):
        """
        Spawns backup process in a prepared environment inside POD
        Waits for POD to be ready, injects required dependencies then starts a command
        Later command will be watched using watch() API method

        :param pod_name:
        :param command:
        :param definition:
        :param is_backup:
        :param version:
        :return:
        """

        wait_for_pod_to_be_ready(self._v1_core_api, pod_name, self._namespace, io=self.io(), timeout=self._timeout)
        self._prepare_environment_inside_pod(definition, pod_name)

        complete_cmd = create_backup_maker_command(command, definition, is_backup, version,
                                                   bin_path=TARGET_ENV_BIN_PATH)
        self.io().debug(f"POD exec: `{complete_cmd}`")

        self._process = pod_exec(
            pod_name=pod_name,
            namespace=self._namespace,
            cmd=complete_cmd,
            io=self._io
        )

    def _prepare_environment_inside_pod(self, definition, pod_name: str) -> None:
        """
        Populate with GPG keys and required tools

        :param definition:
        :param pod_name:
        :return:
        """

        pod_fs = KubernetesPodFilesystem(pod_name, self._namespace, self.io())
        copy_encryption_keys_from_controller_to_target_env(
            src_fs=LocalFilesystem(),
            pub_key_path=definition.encryption().get_public_key_path(),
            private_key_path=definition.encryption().get_private_key_path(),
            dst_fs=pod_fs,
            io=self.io()
        )
        copy_required_tools_from_controller_cache_to_target_env(
            local_cache_fs=LocalFilesystem(),
            dst_fs=pod_fs,
            io=self.io(),
            bin_path=TARGET_ENV_BIN_PATH,
            versions_path=TARGET_ENV_VERSIONS_PATH,
            local_versions_path=BIN_VERSION_CACHE_PATH,
            binaries=self._binaries
        )

    def watch(self) -> bool:
        """
        Buffers stdout/stderr to io.debug() and notifies about exit code at the end
        """

        self._process.watch(self.io().debug)
        return self._process.has_exited_with_success()

    def get_required_binaries(self):
        return []

    def _find_pod_name(self, selector: str, namespace: str) -> str:
        return find_pod_name(self.v1_core_api, selector, namespace, self.io())
