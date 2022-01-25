"""
Kubernetes - SIDE POD
=====================

Creates a temporary POD that has access to all volumes of original POD.
Temporary POD is attempted to be scheduled closest to the original POD to mitigate the latency
"""
import json
import time
from dataclasses import dataclass
from typing import Tuple, List

from kubernetes.client import ApiException, V1Pod, V1ObjectMeta, V1OwnerReference, V1Scale, V1ScaleSpec
from rkd.api.inputoutput import IO
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

    # dynamic
    _temporary_pod_name: str
    _replicas_to_scale: List[ReplicaToScale]

    def __init__(self, spec: dict, io: IO):
        super().__init__(spec, io)
        self._image = spec.get('image')
        self._timeout = spec.get('timeout')
        self._replicas_to_scale = []
        self._scale_down = bool(spec.get('scaleDown'))

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
                    "example": "ghcr.io/riotkit-org/backup-maker-env:latest",
                    "default": "ghcr.io/riotkit-org/backup-maker-env:latest"
                },
                "timeout": {
                    "type": "integer",
                    "default": 3600,
                    "example": 3600
                },
                "scaleDown": {
                    "type": "boolean",
                    "default": False,
                    "example": False
                }
            }
        }

    def schedule(self, command: str, definition, is_backup: bool, version: str = "") -> None:
        original_pod_name = self.find_pod_name(self._selector, self._namespace)

        try:
            if self._scale_down:
                self._scale_pod_owner(original_pod_name, self._namespace)

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
        except:
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
            self._scale(owner.name, namespace, 0)

    def _scale(self, name: str, namespace: str, replicas: int):
        """
        Scale down given Deployment/ReplicationController/StatefulSet

        :param name:
        :param namespace:
        :param replicas:
        :return:
        """

        self.io().info(f"Scaling deployment/{name} in {namespace} namespace to replicas '{replicas}'")
        scale = V1Scale(
            metadata=V1ObjectMeta(name=name, namespace=namespace),
            spec=V1ScaleSpec(
                replicas=replicas
            )
        )
        self.v1_apps_api.replace_namespaced_deployment_scale(name, namespace, scale)

        # then wait for it to be applied
        for i in range(0, 3600):
            deployment_as_dict = json.loads(self.v1_apps_api.read_namespaced_deployment(name=name,
                                                                                        namespace=namespace,
                                                                                        _preload_content=False).data)

            current_replicas_num = int(deployment_as_dict['spec']['replicas'])

            if current_replicas_num == int(replicas):
                self.io().info(f"POD's controller scaled to {replicas}")
                break

            self.io().debug(f"Waiting for cluster to scale POD's controller to {replicas},"
                            f" currently: {current_replicas_num}")
            time.sleep(1)

    def _scale_back(self):
        """
        Bring back service pods

        :return:
        """

        for kind_object in self._replicas_to_scale:
            self._scale(kind_object.name, kind_object.namespace, kind_object.replicas)

    def _create_pod(self, pod_name: str, specification: dict):
        self.io().info(f"Creating temporary POD '{pod_name}'")

        try:
            self._v1_core_api.create_namespaced_pod(namespace=self._namespace, body=specification)

        except ApiException as e:
            if e.reason == "Conflict" and "AlreadyExists" in str(e.body):
                raise Exception(f"POD '{pod_name}' already exists or is terminating, "
                                f"please wait a moment - cannot start process in parallel, "
                                f"it may break something") from e

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
                        'command': ["/bin/sh"],
                        'args': ['-c', f'sleep {str(timeout)}'],
                        'restartPolicy': 'never',
                        'volumeMounts': volume_mounts
                    }
                ],
                'volumes': volumes
            }
        }
