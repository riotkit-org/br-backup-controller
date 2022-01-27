import os
from unittest.mock import patch
from rkd.api.inputoutput import IO, BufferedSystemIO
from rkd.api.testing import BasicTestingCase
from bahub.testing import create_example_fs_definition, run_transport
from bahub.transports.sh import Transport


class TestShellTransport(BasicTestingCase):
    """
    Functional test - requires /bin/bash
    """

    @patch('bahub.transports.sh.create_backup_maker_command')
    def test_executes_command_locally_and_it_returns_fine(self, create_backup_maker_command):
        transport = self._create_example_transport(BufferedSystemIO())
        definition = create_example_fs_definition(transport)

        # our current working directory should be reachable by the transport
        create_backup_maker_command.return_value = ["test", "-d", os.getcwd()]

        self.assertTrue(run_transport(definition, transport))

    @patch('bahub.transports.sh.create_backup_maker_command')
    def test_executes_command_locally_and_returns_failure_when_command_fails(self, create_backup_maker_command):
        transport = self._create_example_transport(BufferedSystemIO())
        definition = create_example_fs_definition(transport)

        create_backup_maker_command.return_value = ["/bin/false"]

        self.assertFalse(run_transport(definition, transport))

    @patch('bahub.transports.sh.create_backup_maker_command')
    def test_fails_when_command_does_not_exists(self, create_backup_maker_command):
        io = BufferedSystemIO()
        transport = self._create_example_transport(io)
        definition = create_example_fs_definition(transport)

        create_backup_maker_command.return_value = ["some-not-existing-command"]

        self.assertFalse(run_transport(definition, transport))
        self.assertIn("No such file or directory", io.get_value())

    @staticmethod
    def _create_example_transport(io: IO) -> Transport:
        return Transport(
            spec={'shell': '/bin/bash'},
            io=io
        )
