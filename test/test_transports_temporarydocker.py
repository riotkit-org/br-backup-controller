import os
from io import StringIO

from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

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

    def setUp(self) -> None:
        super().setUp()
        self._nginx_container = DockerContainer(image='nginx:1.19-alpine').with_name("nginx-side-docker").start()

    def tearDown(self) -> None:
        super().tearDown()
        self._nginx_container.stop(force=True, delete_volume=True)

    # def test_captures_output(self):
    #     self.assertIn(b'PG_VERSION=13', self._create_example_transport().capture('env').strip())

    def test_transport_executes_command(self):
        transport = self._create_example_transport()
        definition = self._create_example_definition(transport)

        with definition.transport(binaries=[]):
            transport.schedule(
                command="ls -la", definition=definition,
                is_backup=True, version=""
            )

        io = IO()
        out = StringIO()

        with io.capture_descriptors(stream=out, enable_standard_out=True):
            transport.watch()

        print('!!!', out.getvalue())

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
                "paths": [os.getcwd() + "/.github"]
            },
        }, name="fs")

    @staticmethod
    def _create_example_transport() -> Transport:
        return Transport(
            spec={
                'orig_container': "nginx-side-docker",
                'temp_container_image': 'nginx:1.18-alpine',
                'shell': '/bin/bash'
            },
            io=IO()
        )
