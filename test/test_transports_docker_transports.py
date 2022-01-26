import os
from testcontainers.core.container import DockerContainer
from unittest.mock import patch
from rkd.api.inputoutput import IO, BufferedSystemIO
from rkd.api.testing import BasicTestingCase
from bahub.model import ServerAccess, Encryption
from bahub.transports.docker_sidecontainer import Transport as SideDockerTransport
from bahub.transports.docker import Transport as DockerExecTransport
from bahub.adapters.filesystem import Definition as FilesystemBackupDefinition


class TestDockerTransport(BasicTestingCase):
    """
    Functional test - requires docker daemon and docker client tools
    """

    _nginx_container: DockerContainer

    @patch('bahub.transports.docker.create_backup_maker_command')
    def test_side_docker_transport_executes_command_inside_temporary_container(self, create_backup_maker_command):
        io = BufferedSystemIO()
        transport = self._create_example_side_docker_transport(io)
        definition = self._create_example_definition(transport)

        create_backup_maker_command.return_value = ["ls", "-la", "/mnt"]

        self.assertTrue(self._run_transport(definition, transport), msg='Expected that `ls -la /mnt` would not fail')

        # at /mnt was mounted ./.github directory from repository (see setUp())
        self.assertIn('workflows', io.get_value(),
                      msg="Failed asserting that backup container on Alpine Linux has same volumes "
                          "as application container with NGINX image")

    @patch('bahub.transports.docker.create_backup_maker_command')
    def test_docker_exec_transport_executes_command_inside_container(self, create_backup_maker_command):
        io = BufferedSystemIO()
        transport = self._create_example_docker_exec_transport(io)
        definition = self._create_example_definition(transport)

        create_backup_maker_command.return_value = ["ls", "/config"]

        self.assertTrue(self._run_transport(definition, transport), msg="Expected that `ls /config` would work")

        # assert that according to https://github.com/linuxserver/docker-nginx/pkgs/container/nginx
        # there are a few directories, so the `docker exec` operation works
        self.assertIn("www", io.get_value())
        self.assertIn("php", io.get_value())
        self.assertIn("nginx", io.get_value())

    @patch('bahub.transports.docker.create_backup_maker_command')
    def test_docker_exec_transport_reports_failure_when_binary_not_found(self, create_backup_maker_command):
        io = BufferedSystemIO()
        transport = self._create_example_docker_exec_transport(io)
        definition = self._create_example_definition(transport)

        create_backup_maker_command.return_value = ["not-a-valid-command"]

        self.assertFalse(self._run_transport(definition, transport),
                         msg="Expected that invalid command will result in a failure")

        self.assertIn("executable file not found in $PATH", io.get_value(),
                      msg="Expected that there will be any message")

    @patch('bahub.transports.docker.create_backup_maker_command')
    def test_docker_exec_transport_reports_failure_when_command_fails(self, create_backup_maker_command):
        io = BufferedSystemIO()
        transport = self._create_example_docker_exec_transport(io)
        definition = self._create_example_definition(transport)

        create_backup_maker_command.return_value = ["/bin/sh", "-c", "/bin/false"]

        self.assertFalse(self._run_transport(definition, transport), msg='/bin/false should return exit code 1')

    @staticmethod
    def _run_transport(definition, transport) -> bool:
        with definition.transport(binaries=[]):
            transport.schedule(
                command="--mocked--", definition=definition,
                is_backup=True, version=""
            )

            return transport.watch()

    # ================
    # Technical stuff
    # ================

    def setUp(self) -> None:
        super().setUp()
        self._nginx_container = DockerContainer(image='ghcr.io/linuxserver/nginx:1.20.2')\
            .with_name("nginx-app").with_volume_mapping(os.getcwd() + "/.github", "/mnt").start()

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
    def _create_example_side_docker_transport(io: IO) -> SideDockerTransport:
        return SideDockerTransport(
            spec={
                'orig_container': "nginx-app",
                'temp_container_image': 'ghcr.io/mirrorshub/docker/alpine:3.14',
                'shell': '/bin/sh'
            },
            io=io
        )

    @staticmethod
    def _create_example_docker_exec_transport(io: IO) -> DockerExecTransport:
        return DockerExecTransport(
            spec={
                'container': "nginx-app",
                'shell': '/bin/sh'
            },
            io=io
        )
