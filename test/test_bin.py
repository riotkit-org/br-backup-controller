from typing import Union

from rkd.api.inputoutput import BufferedSystemIO
from rkd.api.testing import BasicTestingCase
from bahub.bin import RequiredBinary, RequiredBinaryFromGithubRelease, RequiredBinaryFromGithubReleasePackedInArchive, \
    download_required_tools
from bahub.fs import FilesystemInterface


class TestRequiredBinary(BasicTestingCase):
    def test_get_full_name_with_version(self):
        self.assertEqual("vunknown-kubectl",
                         RequiredBinary("https://example.org/releases/kubectl").get_full_name_with_version())

    def test_is_archive(self):
        self.assertTrue(RequiredBinary("https://example.org/releases/kubectl.tar.gz").is_archive())

        # other types than tar.gz are not supported
        self.assertFalse(RequiredBinary("https://example.org/releases/kubectl.zip").is_archive())
        self.assertFalse(RequiredBinary("https://example.org/releases/kubectl").is_archive())

    def test_get_filename(self):
        self.assertEqual("kubectl", RequiredBinary("https://example.org/releases/kubectl").get_filename())


class TestRequiredBinaryFromGithubRelease(BasicTestingCase):
    def test_get_url(self):
        binary = RequiredBinaryFromGithubRelease("riotkit-org/tracexit", "1.0.0", "tracexit")

        self.assertEqual("https://github.com/riotkit-org/tracexit/releases/download/1.0.0/tracexit", binary.get_url())


class TestRequiredBinaryFromGithubReleasePackedInArchive(BasicTestingCase):
    def test_functional(self):
        binary = RequiredBinaryFromGithubReleasePackedInArchive(
            project_name="riotkit-org/tracexit",
            version="1.0.0",
            binary_name="tracexit",
            archive_name="tracexit-1.0.0-amd64.tar.gz"
        )

        self.assertTrue(binary.is_archive())
        self.assertEqual("tracexit", binary.get_filename())
        self.assertEqual(
            "https://github.com/riotkit-org/tracexit/releases/download/1.0.0/tracexit-1.0.0-amd64.tar.gz",
            binary.get_url()
        )


class FSMock(object):
    callstack: list

    def __init__(self):
        self.callstack = []

    def __getattr__(self, item):
        return lambda *args, **kwargs: self.callstack.append([item, args, kwargs])


class TestDownloadRequiredTools(BasicTestingCase):
    def test_downloads_and_unpacks_archive(self):
        """
        When tool does not exist, then it should be downloaded and unpacked (when it is an archive)

        :return:
        """

        io = BufferedSystemIO()
        io.set_log_level("debug")

        fs: Union[FilesystemInterface, FSMock] = FSMock()
        fs.file_exists = lambda path: False
        fs.find_temporary_dir_path = lambda: "/tmp/test"

        download_required_tools(
            fs=fs,
            io=io,
            bin_path="/opt/bin",
            versions_path="/opt/bin/.versions",
            binaries=[
                RequiredBinaryFromGithubReleasePackedInArchive(
                    project_name="riotkit-org/tracexit",
                    version="1.0.0",
                    binary_name="tracexit",
                    archive_name="tracexit-1.0.0-amd64.tar.gz"
                )
            ]
        )

        # directory structure is created
        self.assertIn(['force_mkdir', ('/opt',), {}], fs.callstack)
        self.assertIn(['force_mkdir', ('/opt/bin',), {}], fs.callstack)
        self.assertIn(['force_mkdir', ('/opt/bin/.versions',), {}], fs.callstack)

        # binary is downloaded into temporary directory
        self.assertIn(
            ['download', ('https://github.com/riotkit-org/tracexit/releases/download/1.0.0/tracexit-1.0.0-amd64.tar.gz',
                          '/tmp/test/archive.tar.gz'), {}],
            fs.callstack
        )

        # archive is unpacked
        self.assertIn(
            ['unpack', ('/tmp/test/archive.tar.gz', '/tmp/test'), {}],
            fs.callstack
        )

        # unpacked binary file is moved to .versions directory
        self.assertIn(
            ['move', ('/tmp/test/tracexit', '/opt/bin/.versions/v1.0.0-tracexit'), {}],
            fs.callstack
        )

        # file is made executable, so it can be executed later
        self.assertIn(
            ['make_executable', ('/opt/bin/.versions/v1.0.0-tracexit',), {}],
            fs.callstack
        )

    def test_file_is_not_downloaded_twice(self):
        io = BufferedSystemIO()
        io.set_log_level("debug")

        fs: Union[FilesystemInterface, FSMock] = FSMock()
        fs.file_exists = lambda path: True  # file ALREADY EXISTS

        download_required_tools(
            fs=fs,
            io=io,
            bin_path="/opt/bin",
            versions_path="/opt/bin/.versions",
            binaries=[
                RequiredBinaryFromGithubReleasePackedInArchive(
                    project_name="riotkit-org/tracexit",
                    version="1.0.0",
                    binary_name="tracexit",
                    archive_name="tracexit-1.0.0-amd64.tar.gz"
                )
            ]
        )

        self.assertNotIn("download", str(fs.callstack))

    def test_file_is_downloaded_and_not_unpacked_if_not_an_archive(self):
        io = BufferedSystemIO()
        io.set_log_level("debug")

        fs: Union[FilesystemInterface, FSMock] = FSMock()
        fs.file_exists = lambda path: False
        fs.find_temporary_dir_path = lambda: "/tmp/test"

        download_required_tools(
            fs=fs,
            io=io,
            bin_path="/opt/bin",
            versions_path="/opt/bin/.versions",
            binaries=[
                RequiredBinary("https://bakunin.org/binary-name")
            ]
        )

        self.assertIn(
            ['make_executable', ('/opt/bin/.versions/vunknown-binary-name',), {}],
            fs.callstack
        )

        # should be downloaded
        self.assertIn("download", str(fs.callstack))

        # but should not be unpacked, as not an archive
        self.assertNotIn("unpack", str(fs.callstack))
