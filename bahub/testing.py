"""
Helpers for testing in PyTest
"""


from bahub.model import ServerAccess, Encryption
from bahub.adapters.filesystem import Definition as FilesystemBackupDefinition


def run_transport(definition, transport) -> bool:
    """
    Runs schedule & watch for a transport

    :param definition:
    :param transport:
    :return:
    """

    with definition.transport(binaries=[]):
        transport.schedule(
            command="--mocked--", definition=definition,
            is_backup=True, version=""
        )

        return transport.watch()


def create_example_fs_definition(transport) -> FilesystemBackupDefinition:
    """
    Creates an example Filesystem adapter definition for given Transport

    :param transport:
    :return:
    """

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
