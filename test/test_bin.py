from rkd.api.testing import BasicTestingCase
from bahub.bin import RequiredBinary, RequiredBinaryFromGithubRelease, RequiredBinaryFromGithubReleasePackedInArchive


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
