"""
Kubernetes - SIDE POD
=====================

Creates a temporary POD that has access to all volumes of original POD.
Temporary POD is attempted to be scheduled closest to the original POD to mitigate the latency
"""
import json
from dataclasses import dataclass
from typing import Tuple, List, Optional

from kubernetes.client import V1Pod, V1ObjectMeta, V1OwnerReference
from rkd.api.inputoutput import IO

from .kubernetes import wait_for_pod_to_be_ready, scale_resource, create_pod
from .kubernetes_podexec import Transport as KubernetesPodExecTransport


@dataclass
class ReplicaToScale(object):
    kind: str
    name: str
    namespace: str
    replicas: int


class Transport(KubernetesPodExecTransport):
    _image: str
    _timeout: int
    _scale_down: bool
    _pod_suffix: str

    # dynamic
    _temporary_pod_name: str
    _replicas_to_scale: List[ReplicaToScale]

    def __init__(self, spec: dict, io: IO):
        super().__init__(spec, io)
        self._image = spec.get('image', 'ghcr.io/riotkit-org/backup-maker-env:latest')
        self._replicas_to_scale = []
        self._scale_down = bool(spec.get('scaleDown', False))
        self._pod_suffix = spec.get('podSuffix', '-backup')

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
                    "default": "",
                    "description": "Label selector to find origin POD"
                },
                "namespace": {
                    "type": "string",
                    "example": "prod",
                    "default": "default",
                    "description": "Kubernetes namespace, where the POD is placed and where "
                                   "temporary POD should be placed"
                },
                "image": {
                    "type": "string",
                    "example": "ghcr.io/riotkit-org/backup-maker-env:latest",
                    "default": "ghcr.io/riotkit-org/backup-maker-env:latest",
                    "description": "Container image for a temporary backup POD"
                },
                "timeout": {
                    "type": "integer",
                    "default": 3600,
                    "example": 3600,
                    "description": "Timeout in seconds"
                },
                "scaleDown": {
                    "type": "boolean",
                    "default": False,
                    "example": False,
                    "description": "Should the original POD be scaled down for backup time?"
                },
                "podSuffix": {
                    "type": "string",
                    "default": "-backup",
                    "example": "-backup",
                    "description": "Suffix for name of a backup POD (original pod name + suffix)"
                },
            }
        }

    def schedule(self, command: str, definition, is_backup: bool, version: str = "") -> None:
        original_pod_name = self._find_pod_name(self._selector, self._namespace)

        try:
            if self._scale_down:
                self._scale_pod_owner(original_pod_name, self._namespace)

            volumes, volume_mounts = self._copy_volumes_specification_from_existing_pod(
                original_pod_name,
                namespace=self._namespace
            )

            # spawn temporary pod
            self._temporary_pod_name = f"{original_pod_name}{self._pod_suffix}"
            create_pod(
                self._v1_core_api,
                namespace=self._namespace,
                pod_name=self._temporary_pod_name,
                specification=self._create_backup_pod_definition(
                    original_pod_name,
                    self._temporary_pod_name,
                    self._timeout,
                    volumes,
                    volume_mounts
                ),
                io=self.io()
            )

            self._execute_in_pod_when_pod_will_be_ready(self._temporary_pod_name, command, definition, is_backup,
                                                        version)
        except Exception as err:
            self.io().error(f"Got error while scheduling backup in temporary POD: {err}")

            if self._scale_down:
                self._scale_back()

            raise

    def _scale_pod_owner(self, pod_name: str, namespace: str):
        """
        Tell Deployment/ReplicationController/StatefulSet etc. to scale down

        :param pod_name:
        :param namespace:
        :return:
        """

        pod: V1Pod = self._v1_core_api.read_namespaced_pod(name=pod_name, namespace=namespace)
        metadata: V1ObjectMeta = pod.metadata
        owners: List[V1OwnerReference] = metadata.owner_references

        if not owners:
            self.io().warn("No POD owner found through owner references")
            return

        self._scale_by_owner_references(owners, namespace)

    def _scale_by_owner_references(self, owners: List[V1OwnerReference], namespace: str):
        for owner in owners:
            if owner.kind == "ReplicaSet":
                rs = self.v1_apps_api.read_namespaced_replica_set(name=owner.name, namespace=namespace)
                metadata: V1ObjectMeta = rs.metadata
                rs_owners: List[V1OwnerReference] = metadata.owner_references

                self._scale_by_owner_references(rs_owners, namespace)
                continue

            elif owner.kind != "Deployment":
                self.io().warn(f"Unsupported controller type '{owner.kind}', will not attempt to scale it")
                continue

            deployment_as_dict = json.loads(self.v1_apps_api.read_namespaced_deployment(name=owner.name,
                                                                                        namespace=namespace,
                                                                                        _preload_content=False).data)

            self._replicas_to_scale.append(ReplicaToScale(
                kind='Deployment',
                name=owner.name,
                namespace=namespace,
                replicas=deployment_as_dict['spec'].get('replicas', 0)
            ))
            scale_resource(self.v1_apps_api, owner.name, namespace, 0, io=self.io())

    def _scale_back(self):
        """
        Bring back service pods

        :return:
        """

        for kind_object in self._replicas_to_scale:
            scale_resource(self.v1_apps_api, kind_object.name, kind_object.namespace,
                           kind_object.replicas, io=self.io())

    def _terminate_pod(self, pod_name: str):
        self.io().info("Clean up - deleting temporary POD")

        try:
            self._v1_core_api.delete_namespaced_pod(namespace=self._namespace, name=pod_name)
        except Exception as err:
            self.io().error(f"Error while terminating pod: {err}")

    def _copy_volumes_specification_from_existing_pod(self, pod_name: str, namespace: str) -> Tuple[dict, list]:
        self.io().debug(f"Copying volumes specification from source pod={pod_name}")
        wait_for_pod_to_be_ready(self._v1_core_api, pod_name, namespace, io=self.io(), timeout=self._timeout)
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
        """
        After operation try to clean up - terminate the temporary POD

        :param exc_type:
        :param exc_val:
        :param exc_t:
        :return:
        """

        try:
            if hasattr(self, '_temporary_pod_name'):
                self._terminate_pod(self._temporary_pod_name)
        finally:
            self._scale_back()

    def _create_backup_pod_definition(self, original_pod_name: str, backup_pod_name: str, timeout: int,
                                      volumes: Optional[dict], volume_mounts: Optional[list]) -> dict:
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
                "restartPolicy": "Never",
                'containers': [
                    {
                        'image': self._image,
                        'name': backup_pod_name,
                        'command': ["/bin/sh"],
                        'args': ['-c', f'sleep {str(timeout)}'],
                        'restartPolicy': 'never',
                        'volumeMounts': volume_mounts
                    }
                ],
                'volumes': volumes
            }
        }
