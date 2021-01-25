"""
Core Tasks
==========

Provides shell commands such as:
- preparing backups
- sending backups
- listing backups
- receiving backups

"""
from rkd.api.syntax import TaskDeclaration
from .prepare import BackupPreparationTask
from .uploader import UploaderTask
from .restore import RestoreTask
from .cryptsetup import CryptographyKeysSetupTask, ListCryptoKeys


def imports():
    return [
        TaskDeclaration(UploaderTask()),
        TaskDeclaration(RestoreTask()),
        TaskDeclaration(BackupPreparationTask()),
        TaskDeclaration(CryptographyKeysSetupTask()),
        TaskDeclaration(ListCryptoKeys())
    ]
