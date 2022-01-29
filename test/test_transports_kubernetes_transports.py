import hashlib
import os
import subprocess
import time
from unittest.mock import patch
from rkd.api.inputoutput import IO, BufferedSystemIO
from rkd.api.testing import BasicTestingCase
from bahub.transports.kubernetes_podexec import Transport as PodExecTransport
from bahub.transports.kubernetes_sidepod import Transport as SidePodTransport
from bahub.testing import create_example_fs_definition, run_transport


def _should_keep_cluster() -> bool:
    """
    For debugging: Allows to not clean up the cluster if in environment there is KEEP_CLUSTER=yes
    """
    return os.getenv("KEEP_CLUSTER") in ["yes", "true"]


class TestKubernetesTransport(BasicTestingCase):
    @patch('bahub.transports.kubernetes_podexec.create_backup_maker_command')
    def test_backup_side_pod_operates_on_same_volumes_as_original_application(self, create_backup_maker_command):
        """
        Given we have a Kubernetes cluster
        With service deployed from test/env/kubernetes/nginx/*.yaml, called later ORIGINAL POD

        And we spawn a TEMPORARY POD with image alpine:3.14
        Then we expect that TEMPORARY POD will have mounted same volumes as ORIGINAL POD

        The experiment will be done by reading a file in TEMPORARY POD,
        that file was created on a shared volume by ORIGINAL POD
        """

        io = BufferedSystemIO()
        io.set_log_level('debug')
        transport = SidePodTransport(
            spec={
                'selector': "app=nginx",  # see: test/env/kubernetes/nginx
                'namespace': 'default',
                'shell': '/bin/sh',
                'image': 'ghcr.io/mirrorshub/docker/alpine:3.14',
                'podSuffix': f"-backup-{hashlib.sha224(self._testMethodName.encode('utf-8')).hexdigest()[0:9]}"
            },
            io=io
        )
        definition = create_example_fs_definition(transport)

        # it will be executed inside a temporary container with Alpine Linux image
        # while it is created by setupClass() in original POD with NGINX
        create_backup_maker_command.return_value = ["cat", "/var/www/msg.html"]

        self.assertTrue(run_transport(definition, transport))
        self.assertIn("I have never read Marx Capital, but I have the marks of capital all over me.", io.get_value())

    @patch('bahub.transports.kubernetes_podexec.create_backup_maker_command')
    def test_exec_inside_application_pod_finds_mounted_file(self, create_backup_maker_command):
        """
        We do a `kubectl exec` into a running POD and execute a command, grab result
        """

        io = BufferedSystemIO()
        io.set_log_level('debug')
        transport = PodExecTransport(
            spec={
                'selector': "app=nginx",  # see: test/env/kubernetes/nginx
                'namespace': 'default',
            },
            io=io
        )
        definition = create_example_fs_definition(transport)

        create_backup_maker_command.return_value = ["cat", "/var/www/msg.html"]
        self.assertTrue(run_transport(definition, transport))
        self.assertIn("I have never read Marx Capital, but I have the marks of capital all over me.", io.get_value())

    @classmethod
    def setUpClass(cls) -> None:
        super(TestKubernetesTransport, cls).setUpClass()
        cls._clean_up_cluster()

        print('[TEST] Creating a Kubernetes cluster')
        try:
            subprocess.check_output(["kind", "create", "cluster"], stderr=subprocess.STDOUT)

        except subprocess.CalledProcessError as err:
            if "already exist for a cluster with the name" not in err.output.decode('utf-8'):
                raise

        subprocess.check_call(["kubectl", "apply", "-f", os.getcwd() + "/test/env/kubernetes/nginx/"])

        # create an example file as soon as the POD will be ready
        print('[TEST] Injecting test data into original POD, it may take a while')
        for i in range(0, 900):
            try:
                subprocess.check_output(['kubectl', 'exec',
                                         'deployment/nginx', '--',
                                         '/bin/sh', '-c',
                                         'mkdir -p /var/www; echo "I have never read Marx Capital, '
                                         'but I have the marks of capital all over me." > /var/www/msg.html'],
                                        stderr=subprocess.STDOUT)
            except:  # retry
                time.sleep(1)
                continue
            break

    @classmethod
    def tearDownClass(cls) -> None:
        cls._clean_up_cluster()

    @staticmethod
    def _clean_up_cluster():
        if _should_keep_cluster():
            return

        print('[TEST] Deleting a Kubernetes cluster (if any)')
        try:
            subprocess.check_output(["kind", "delete", "cluster"], stderr=subprocess.STDOUT)
        except:
            pass
