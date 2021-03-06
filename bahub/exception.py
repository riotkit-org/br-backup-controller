
class ApplicationException(Exception):
    pass


class TransportException(ApplicationException):
    pass


class DockerContainerError(TransportException):
    @staticmethod
    def from_container_not_found(container_id: str) -> 'DockerContainerError':
        return DockerContainerError('Container "{}" is not created'.format(container_id))

    @staticmethod
    def from_container_not_running(container_id: str, status: str) -> 'DockerContainerError':
        return DockerContainerError('Container "{}" is not running but actually {}'.format(container_id, status))


class KubernetesError(TransportException):
    @classmethod
    def from_timed_out_waiting_for_pod(cls, pod_name: str, namespace: str) -> 'KubernetesError':
        return cls(f"Timed out while waiting for pod '{pod_name}' in namespace '{namespace}'")

    @classmethod
    def cannot_scale_resource(cls, name: str, namespace: str, replicas: int):
        return cls(f"Cannot achieve desired state of '{replicas}' replicas for '{name}' in '{namespace}' namespace")

    @classmethod
    def from_pod_creation_conflict(cls, pod_name: str):
        return cls(f"POD '{pod_name}' already exists or is terminating, "
                   f"please wait a moment - cannot start process in parallel, "
                   f"it may break something")


class ConfigurationFactoryException(ApplicationException):
    pass


class ConfigurationError(ApplicationException):
    pass


class SpecificationError(ConfigurationError):
    pass


class ApiException(ApplicationException):
    pass


class HttpException(ApiException):
    pass


class InvalidResponseException(HttpException):
    _json = None
    _exit_code = 0

    def __init__(self, msg, _json: dict, _exit_code: int):
        super().__init__(msg)
        self._json = _json
        self._exit_code = _exit_code

    def get_json(self) -> dict:
        return self._json

    def get_error(self):
        return self._json['error'] if 'error' in self._json else str(self._json)


class ParsingException(ApplicationException):
    """Errors related to parsing YAML/Python syntax"""

    @classmethod
    def from_import_error(cls, import_str: str, error: Exception) -> 'ParsingException':
        return cls(
            'Import "%s" is invalid - error: %s' % (
                import_str, str(error)
            )
        )

    @classmethod
    def from_class_not_found_in_module_error(cls, import_str: str, class_name: str) -> 'ParsingException':
        return cls(
            'Import "%s" is invalid. Class or method "%s" not found in module' % (
                import_str, class_name
            )
        )


class BufferingError(ApplicationException):
    @staticmethod
    def from_early_buffer_exit(stream_description: str) -> 'BufferingError':
        return BufferingError('Buffering of stream "{}" ended earlier with error'.format(stream_description))


class BackupProcessError(ApplicationException):
    """Errors related to backup/restore streaming"""


class BackupRestoreError(BackupProcessError):
    """When we cannot restore a backup - at least one stage failed in the process"""

    @staticmethod
    def from_generic_restore_failure(stream) -> 'BackupRestoreError':
        return BackupRestoreError("Restore error. Process exited with a failure - read logs above.\nFailure cause: {}"
                                  .format(stream.find_failure_cause()))
