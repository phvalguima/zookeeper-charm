# Copyright 2021 pguimaraes
# See LICENSE file for licensing details.

import os
import unittest
from mock import patch
from mock import PropertyMock

from ops.testing import Harness
import charm as charm
import cluster as cluster
import charmhelpers.core.host as host
import charmhelpers.fetch.ubuntu as ubuntu

from unit_tests.config_files import ZK_PROPERTIES
from unit_tests.config_files import ZK_PROPERTIES_WITH_SSL

from wand.contrib.linux import getCurrentUserAndGroup
import wand.apps.relations.zookeeper as zkRelation
import wand.apps.kafka as kafka

TO_PATCH_LINUX = [
    'userAdd',
    'groupAdd'
]

TO_PATCH_FETCH = [
    'apt_install',
    'apt_update',
    'add_source'
]

TO_PATCH_HOST = [
    'service_running',
    'service_restart',
    'service_reload'
]


class MockRelations(object):
    def __init__(self, data):
        self._data = data

    @property
    def data(self):
        return self._data

    # Assuming just one relation exists
    @property
    def relations(self):
        return {"relation": self._data}

    @property
    def units(self):
        return list(self._data.keys())


# Use _update_config within Harness:
# Although it is intended for internal use, it is ideal to
# load config options without firing a hook config-changed
class TestCharm(unittest.TestCase):
    maxDiff = None  # print the entire diff on assert commands

    def _patch(self, obj, method):
        _m = patch.object(obj, method)
        mock = _m.start()
        self.addCleanup(_m.stop)
        return mock

    def _simulate_render(self, ctx=None, templ_file=""):
        import jinja2
        env = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'))
        templ = env.get_template(templ_file)
        doc = templ.render(ctx)
        return doc

    def setUp(self):
        super(TestCharm, self).setUp()
        for p in TO_PATCH_LINUX:
            self._patch(kafka, p)
        for p in TO_PATCH_FETCH:
            self._patch(ubuntu, p)
        for p in TO_PATCH_HOST:
            self._patch(charm, p)

    @patch.object(charm.ZookeeperCharm,
                  'is_client_ssl_enabled')
    @patch.object(charm.ZookeeperCluster, "get_peers",
                  new_callable=PropertyMock)
    @patch.object(charm.ZookeeperCluster, "is_ready",
                  new_callable=PropertyMock)
    @patch.object(charm, "render")
    def test_confluent_simple_render_zk_props(self, mock_render,
                                              mock_is_ready,
                                              mock_get_peers,
                                              mock_is_client_ssl):

        mock_render.return_value = ""
        mock_is_ready.return_value = True
        mock_is_client_ssl.return_value = False
        mock_get_peers.return_value = [
            {"myid": 1, "endpoint": "ansiblezookeeper2.example.com:2888:3888"},
            {"myid": 2, "endpoint": "ansiblezookeeper3.example.com:2888:3888"},
            {"myid": 3, "endpoint": "ansiblezookeeper1.example.com:2888:3888"},
        ]
        harness = Harness(charm.ZookeeperCharm)
        self.addCleanup(harness.cleanup)
        harness.begin()
        zk = harness.charm
        zk._render_zk_properties()
        self.assertEqual(ZK_PROPERTIES,
                         self._simulate_render(
                             ctx=mock_render.call_args.kwargs["context"],
                             templ_file='zookeeper.properties.j2'))

    @patch.object(kafka.KafkaJavaCharmBase, "create_data_and_log_dirs")
    @patch.object(zkRelation.ZookeeperProvidesRelation, "set_TLS_auth")
    @patch.object(cluster.ZookeeperCluster, "set_ssl_keypair")
    @patch.object(charm.ZookeeperCharm, "unit_folder",
                  new_callable=PropertyMock)
    @patch.object(charm.ZookeeperCharm, '_check_if_ready')
    @patch.object(host, 'service_restart')
    @patch.object(host, 'service_reload')
    @patch.object(host, 'service_running')
    @patch.object(charm.ZookeeperCharm, 'render_service_override_file')
    @patch.object(charm.ZookeeperCharm, '_render_zk_log4j_properties')
    @patch.object(charm.ZookeeperCharm, 'is_client_ssl_enabled')
    @patch.object(charm.ZookeeperCluster, "get_peers",
                  new_callable=PropertyMock)
    @patch.object(charm.ZookeeperCluster, "is_ready",
                  new_callable=PropertyMock)
    @patch.object(charm, "render")
    def test_confluent_ssl_render_zk_props(self,
                                           mock_render,
                                           mock_is_ready,
                                           mock_get_peers,
                                           mock_is_client_ssl,
                                           mock_log_4j,
                                           mock_svc_file,
                                           mock_svc_running,
                                           mock_svc_reload,
                                           mock_svc_restart,
                                           mock_check_if_ready,
                                           mock_unit_folder,
                                           mock_cluster_ssl_keypair,
                                           mock_tls_auth,
                                           mock_create_log_dir):
        def __cleanup():
            for i in ["/tmp/ks-charm.p12", "/tmp/ks-charm*",
                      "/tmp/test-quorum-*", "/tmp/3jtieo-ks.jks",
                      "/tmp/3jtieo-ts.jks", "/tmp/3jtieo-quorum-ks.jks",
                      "/tmp/3jtieo-quorum-ts.jks"]:
                try:
                    os.remove(i)
                except: # noqa
                    pass
        __cleanup()
        mock_svc_running.return_value = True
        mock_render.return_value = ""
        mock_unit_folder.return_value = "/tmp"
        mock_is_ready.return_value = True
        mock_is_client_ssl.return_value = False
        mock_get_peers.return_value = [
            {"myid": 1,
             "endpoint": "ansiblezookeeper2.example.com:2888:3888"},
            {"myid": 2,
             "endpoint": "ansiblezookeeper3.example.com:2888:3888"},
            {"myid": 3,
             "endpoint": "ansiblezookeeper1.example.com:2888:3888"},
        ]
        harness = Harness(charm.ZookeeperCharm)
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.update_config(
            key_values={"user": getCurrentUserAndGroup()[0],
                        "group": getCurrentUserAndGroup()[1],
                        "quorum-keystore-path": "/tmp/3jtieo-quorum-ks.jks",
                        "quorum-truststore-path": "/tmp/3jtieo-quorum-ts.jks",
                        "keystore-path": "/tmp/3jtieo-ks.jks",
                        "truststore-path": "/tmp/3jtieo-ts.jks",
                        "generate-root-ca": True,
                        "regenerate-keystore-truststore": True,
                        "ssl_quorum": True})
        # Replace the random variables for expected ones
        # since it is not possible to check them
        ctx = mock_render.call_args.kwargs["context"]
        ctx["zk_props"]["ssl.quorum.trustStore.password"] = \
            "confluenttruststorepass"
        ctx["zk_props"]["ssl.quorum.keyStore.password"] = \
            "confluentkeystorestorepass"
        ctx["zk_props"]["ssl.trustStore.password"] = \
            "confluenttruststorepass"
        ctx["zk_props"]["ssl.keyStore.password"] = \
            "confluentkeystorestorepass"
        zk_props = self._simulate_render(
                       ctx=ctx,
                       templ_file='zookeeper.properties.j2')
        self.assertEqual(ZK_PROPERTIES_WITH_SSL, zk_props)
        __cleanup()
