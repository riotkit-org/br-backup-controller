import os
from io import StringIO

from testcontainers.core.container import DockerContainer
from unittest.mock import patch

from rkd.api.inputoutput import IO
from rkd.api.testing import BasicTestingCase
from bahub.model import ServerAccess, Encryption
from bahub.transports.sidedocker import Transport
from bahub.adapters.filesystem import Definition as FilesystemBackupDefinition


class TestSideDockerTransport(BasicTestingCase):
    """
    Functional test - requires docker daemon and docker client tools
    """

    _nginx_container: DockerContainer

    @patch('bahub.transports.docker.create_backup_maker_command')
    def test_transport_executes_command_inside_temporary_container(self, create_backup_maker_command):
        transport = self._create_example_transport()
        definition = self._create_example_definition(transport)

        create_backup_maker_command.return_value = ["ls", "-la", "/mnt"]

        io = IO()
        out = StringIO()

        with definition.transport(binaries=[]):
            transport.schedule(
                command="--mocked--", definition=definition,
                is_backup=True, version=""
            )

            with io.capture_descriptors(stream=out, enable_standard_out=True):
                transport.watch()

        # at /mnt was mounted ./.github directory from repository (see setUp())
        self.assertIn('workflows', out.getvalue(),
                      msg="Failed asserting that backup container on Alpine Linux has same volumes "
                          "as application container with NGINX image")

    # ================
    # Technical stuff
    # ================

    def setUp(self) -> None:
        super().setUp()
        self._nginx_container = DockerContainer(image='quay.io/bitnami/nginx:1.21-debian-10')\
            .with_name("nginx-side-docker").with_volume_mapping(os.getcwd() + "/.github", "/mnt").start()

    def tearDown(self) -> None:
        super().tearDown()
        self._nginx_container.stop(force=True, delete_volume=True)

    @staticmethod
    def _create_example_definition(transport) -> FilesystemBackupDefinition:
        return FilesystemBackupDefinition.from_config(cls=FilesystemBackupDefinition, config={
            "meta": {
                "access": ServerAccess(
                    url="http://localhost:8080",
                    token="test"
                ),
                "collection_id": "1111-2222-3333-4444",
                "encryption": Encryption.from_config(name="enc", config={
                    "passphrase": "riotkit",
                    "email": "test@riotkit.org",
                    "public_key_path": "",
                    "private_key_path": "test/env/config_factory_test/gpg-key.asc"
                }),
                "transport": transport
            },
            "spec": {
                "paths": ["/app"]
            },
        }, name="fs")

    @staticmethod
    def _create_example_transport() -> Transport:
        return Transport(
            spec={
                'orig_container': "nginx-side-docker",
                'temp_container_image': 'ghcr.io/mirrorshub/docker/alpine:3.14',
                'shell': '/bin/sh'
            },
            io=IO()
        )
