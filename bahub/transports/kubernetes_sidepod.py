"""
Kubernetes - SIDE POD
=====================

Creates a temporary POD that has access to all volumes of original POD.
Temporary POD is attempted to be scheduled closest to the original POD to mitigate the latency
"""
import json
from typing import Tuple

from kubernetes.client import ApiException
from rkd.api.inputoutput import IO
from .kubernetes_podexec import Transport as KubernetesPodExecTransport


class Transport(KubernetesPodExecTransport):
    _image: str
    _timeout: int

    # dynamic
    _temporary_pod_name: str

    def __init__(self, spec: dict, io: IO):
        super().__init__(spec, io)
        self._image = spec.get('image')
        self._timeout = spec.get('timeout')

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
                "image": {
                    "type": "string",
                    "default": "alpine:3.12"
                    # "example": "gcr.io/riotkit-org/backup-maker-standard-env:latest",
                    # "default": "gcr.io/riotkit-org/backup-maker-standard-env:latest"
                },
                "timeout": {
                    "type": "integer",
                    "default": 3600,
                    "example": 3600
                }
            }
        }

    def schedule(self, command: str, definition, is_backup: bool, version: str = "") -> None:
        original_pod_name = self.find_pod_name(self._selector, self._namespace)

        volumes, volume_mounts = self._copy_volumes_specification_from_existing_pod(
            original_pod_name,
            namespace=self._namespace
        )

        # spawn temporary pod
        self._temporary_pod_name = f"{original_pod_name}-backup"
        self._create_pod(
            pod_name=self._temporary_pod_name,
            specification=self._create_backup_pod_definition(
                original_pod_name,
                self._temporary_pod_name,
                self._timeout,
                volumes,
                volume_mounts
            )
        )

        self._execute_in_pod_when_pod_will_be_ready(self._temporary_pod_name, command, definition, is_backup, version)

    def _create_pod(self, pod_name: str, specification: dict):
        self.io().info(f"Creating temporary POD '{pod_name}'")

        try:
            self._v1_core_api.create_namespaced_pod(namespace=self._namespace, body=specification)
        except ApiException as e:
            if e.reason == "Conflict" and "AlreadyExists" in str(e.body):
                raise Exception(f"POD '{pod_name}' already exists or is terminating, please wait a moment") from e

            raise e

    def _terminate_pod(self, pod_name: str):
        self.io().info("Clean up - deleting temporary POD")
        self._v1_core_api.delete_namespaced_pod(namespace=self._namespace, name=pod_name)

    def _copy_volumes_specification_from_existing_pod(self, pod_name: str, namespace: str) -> Tuple[dict, list]:
        self.io().debug(f"Copying volumes specification from source pod={pod_name}")
        self.wait_for_pod_to_be_ready(pod_name, namespace)
        pod = json.loads(self._v1_core_api.read_namespaced_pod(pod_name, namespace, _preload_content=False).data)

        try:
            pod_volumes = pod['spec']['volumes']
        except KeyError:
            return {}, []

        mounts = []
        _already_added_mounts = []

        # grab mounts from all containers, avoid duplications
        for container in pod['spec']['containers']:
            self.io().debug(f"Processing container with image={container['image']}")

            try:
                volume_mounts = container['volumeMounts']
            except KeyError:
                self.io().debug(f"Container with image '{container['image']}' does not have volumeMounts")
                continue

            for mount in volume_mounts:
                target_path = mount['mountPath']

                # do not mount twice :-)
                if target_path in _already_added_mounts:
                    self.io().warn(f"Container with image={container['image']} has overlapping mount "
                                   f"of other container")
                    continue

                mounts.append(mount)

        return pod_volumes, mounts

    def __exit__(self, exc_type, exc_val, exc_t) -> None:
        self._terminate_pod(self._temporary_pod_name)

    def _create_backup_pod_definition(self, original_pod_name: str, backup_pod_name: str, timeout: int,
                                      volumes: dict, volume_mounts: list) -> dict:
        return {
            'apiVersion': 'v1',
            'kind': 'Pod',
            'metadata': {
                "name": backup_pod_name,
                "namespace": self._namespace,
                "labels": {
                    "riotkit.org/original-pod": original_pod_name,
                }
            },
            'spec': {
                'containers': [
                    {
                        'image': self._image,
                        'name': backup_pod_name,
                        'args': ['sleep', str(timeout)],
                        'restartPolicy': 'never',
                        'volumeMounts': volume_mounts
                    }
                ],
                'volumes': volumes
            }
        }
