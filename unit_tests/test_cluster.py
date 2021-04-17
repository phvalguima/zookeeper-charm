import os
import unittest
from mock import patch
from mock import PropertyMock

from ops.testing import Harness
import charm as charm
import cluster as cluster

import wand.security.ssl as security
from wand.security.ssl import genRandomPassword


class MockRelation(object):
    def __init__(self, data):
        self._data = data

    @property
    def data(self):
        return self._data

    @property
    def relations(self):
        return [self]

    @property
    def units(self):
        return list(self._data.keys())


class TestCluster(unittest.TestCase):
    maxDiff = None

    def _patch(self, obj, method):
        _m = patch.object(obj, method)
        mock = _m.start()
        self.addCleanup(_m.stop)
        return mock

    def setUp(self):
        super(TestCluster, self).setUp()

    @patch.object(cluster.ZookeeperCluster, "relations",
                  new_callable=PropertyMock)
    @patch.object(security, "setFilePermissions")
    @patch.object(cluster.ZookeeperCluster, "unit",
                  new_callable=PropertyMock)
    @patch.object(cluster.ZookeeperCluster, "relation",
                  new_callable=PropertyMock)
    def test_get_all_tls_certs(self,
                               mock_relation,
                               mock_unit,
                               mock_perms,
                               mock_relations):
        def __cleanup():
            for i in ["/tmp/testcert*", "/tmp/test-ts-quorum.jks"]:
                try:
                    os.remove(i)
                except: # noqa
                    pass

        __cleanup()
        certs = {}
        for i in range(1, 4):
            crt, key = security.generateSelfSigned("/tmp", "testcert")
            certs[i] = {}
            certs[i]["crt"] = crt
            certs[i]["key"] = key
        __cleanup()  # cleaning up the intermediate certs
        harness = Harness(charm.ZookeeperCharm)
        self.addCleanup(harness.cleanup)
        harness.begin()
        zk = harness.charm
        data = {
            "u1": {"tls_cert": certs[1]["crt"], "myid": 1,
                   "endpoint": "ansiblezookeeper2.example.com:2888:3888"},
            "u2": {"tls_cert": certs[2]["crt"], "myid": 2,
                   "endpoint": "ansiblezookeeper3.example.com:2888:3888"},
            "u3": {"tls_cert": certs[3]["crt"], "myid": 3,
                   "endpoint": "ansiblezookeeper1.example.com:2888:3888"}
        }
        mock_relation.return_value = MockRelation(data)
        mock_relations.return_value = mock_relation.return_value.relations
        mock_unit.return_value = "u1"
        tspwd = genRandomPassword()
        zk.cluster.set_ssl_keypair(certs[1]["crt"], "/tmp/test-ts-quorum.jks",
                                   tspwd, "ubuntu", "ubuntu", 0o640)
        self.assertEqual(len(tspwd), 48)
        self.assertEqual(
            True,
            security._check_file_exists("/tmp/test-ts-quorum.jks"))
        __cleanup()
