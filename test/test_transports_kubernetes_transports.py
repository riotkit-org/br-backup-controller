import hashlib
import os
import subprocess
import time
from unittest.mock import patch

from kubernetes import config
from kubernetes.client import CoreV1Api
from rkd.api.inputoutput import IO, BufferedSystemIO
from rkd.api.testing import BasicTestingCase

from bahub.transports.kubernetes import find_pod_name, create_pod, wait_for_pod_to_be_ready
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

    @patch('bahub.transports.kubernetes_podexec.create_backup_maker_command')
    def test_inside_reports_failure_when_command_returns_error_exit_code(self, create_backup_maker_command):
        """
        Test SidePod and PodExec transports against invalid command - watch() should return False
        """

        io = BufferedSystemIO()
        io.set_log_level('debug')

        transports = [
            PodExecTransport(
                spec={
                    'selector': "app=nginx",  # see: test/env/kubernetes/nginx
                    'namespace': 'default',
                },
                io=io
            ),
            SidePodTransport(
                spec={
                    'selector': "app=nginx",  # see: test/env/kubernetes/nginx
                    'namespace': 'default',
                    'shell': '/bin/sh',
                    'image': 'ghcr.io/mirrorshub/docker/alpine:3.14',
                    'podSuffix': f"-backup-{hashlib.sha224(self._testMethodName.encode('utf-8')).hexdigest()[0:9]}"
                },
                io=io
            )
        ]

        for transport in transports:
            definition = create_example_fs_definition(transport)

            create_backup_maker_command.return_value = ["/bin/false"]
            self.assertFalse(run_transport(definition, transport),
                             msg=f"{transport} failed assertion, as command is expected to fail as /bin/false was used"
                                 f" which returns a exit code '1'")

    def test_find_pod_name_raises_exception_when_pod_does_not_exist(self):
        config.load_kube_config()

        with self.assertRaises(Exception) as raised:
            find_pod_name(api=CoreV1Api(),
                          selector="my-non-existing-selector=value",
                          namespace="kube-system",
                          io=BufferedSystemIO())

        self.assertIn("No pods found matching selector", str(raised.exception))
        self.assertIn("my-non-existing-selector=value", str(raised.exception))
        self.assertIn("kube-system", str(raised.exception))

    def test_find_pod_name_finds_pod(self):
        subprocess.check_call(["kubectl", "apply", "-f", os.getcwd() + "/test/env/kubernetes/nginx/"])
        time.sleep(5)

        config.load_kube_config()
        name = find_pod_name(api=CoreV1Api(),
                             selector="app=nginx",   # labels taken from deployment.yaml that was just applied
                             namespace="default",
                             io=BufferedSystemIO())

        self.assertIn("nginx", name)

    def test_created_pod_will_timeout_and_will_be_deleted(self):
        """
        Covers: _create_backup_pod_definition(), create_pod() and wait_for_pod_to_be_ready()
        :return:
        """

        # at first: clean up
        subprocess.call(["kubectl", "delete", "pod", "test-creation-and-scaling"])

        config.load_kube_config()

        transport = SidePodTransport({'selector': '...'}, io=BufferedSystemIO())
        transport._image = "ghcr.io/mirrorshub/docker/alpine:3.14"

        create_pod(
            api=CoreV1Api(),
            pod_name="test-creation-and-scaling",
            namespace="default",
            specification=transport._create_backup_pod_definition(
                original_pod_name="something",
                backup_pod_name="something-backup",
                timeout=4,
                volumes=None,
                volume_mounts=None
            ),
            io=BufferedSystemIO()
        )
        wait_for_pod_to_be_ready(api=CoreV1Api(),
                                 pod_name="test-creation-and-scaling",
                                 namespace="default",
                                 io=BufferedSystemIO(),
                                 timeout=120)

        self.assertIn(
            "Running",
            subprocess.check_output("kubectl get pods -n default | grep test-creation-and-scaling", shell=True)
            .decode('utf-8')
        )

        time.sleep(5)
        self.assertIn(
            "Completed",
            subprocess.check_output("kubectl get pods -n default | grep test-creation-and-scaling", shell=True)
            .decode('utf-8')
        )

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
