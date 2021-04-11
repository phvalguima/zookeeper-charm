# Copyright 2021 pguimaraes
# See LICENSE file for licensing details.

import unittest
from mock import patch
from mock import PropertyMock

from ops.testing import Harness
import src.charm as charm
import src.cluster as cluster
import charmhelpers.core.host as host
import charmhelpers.fetch.ubuntu as ubuntu
import charmhelpers.core.templating as template

from unit_tests.config_files import ZK_PROPERTIES

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

# Use _update_config within Harness:
# Although it is intended for internal use, it is ideal to
# load config options without firing a hook config-changed
class TestCharm(unittest.TestCase):
    maxDiff = None # print the entire diff on assert commands

    def _patch(self, obj, method):
        _m = patch.object(obj, method)
        mock = _m.start()
        self.addCleanup(_m.stop)
        return mock

    def _simulate_render(self, ctx=None, templ_file=""):
        import jinja2
        env=jinja2.Environment(loader=jinja2.FileSystemLoader('templates'))
        templ = env.get_template(templ_file)
        doc = templ.render(ctx)
        return doc

    def setUp(self):
        super(TestCharm, self).setUp()
        for p in TO_PATCH_FETCH:
            self._patch(ubuntu, p)
        for p in TO_PATCH_HOST:
            self._patch(host, p)

    @patch.object(charm.ZookeeperCharm, 'is_client_ssl_enabled')
    @patch.object(charm.ZookeeperCluster, "get_peers", new_callable=PropertyMock)
    @patch.object(charm.ZookeeperCluster, "is_ready", new_callable=PropertyMock)
    @patch.object(charm, "render")
    def test_confluent_render_zk_props(self, mock_render,
                                       mock_is_ready,
                                       mock_get_peers,
                                       mock_is_client_ssl):

        mock_render.return_value = ""
        mock_is_ready.return_value = True
        mock_is_client_ssl.return_value = False
        mock_get_peers.return_value = [
            { "myid": 1, "endpoint": "ansiblezookeeper2.example.com:2888:3888" },
            { "myid": 2, "endpoint": "ansiblezookeeper3.example.com:2888:3888" },
            { "myid": 3, "endpoint": "ansiblezookeeper1.example.com:2888:3888" },
        ]
        harness = Harness(charm.ZookeeperCharm)
        self.addCleanup(harness.cleanup)
        harness.begin()
#        harness.set_leader(True)
#        cluster1 = \
#            harness.add_relation('cluster', 'zookeeper')
#        harness.add_relation_unit(cluster1, 'zookeeper/0')
#        harness.update_relation_data(cluster1, 'zookeeper/0', {"myid":1, "endpoint": "ansiblezookeeper2.example.com:2888:3888"})
#        cluster2 = \
#            harness.add_relation('cluster', 'zookeeper')
#        harness.add_relation_unit(cluster2, 'zookeeper/1')
#        harness.update_relation_data(cluster2, 'zookeeper/1', {"myid":2, "endpoint": "ansiblezookeeper3.example.com:2888:3888"})
        zk = harness.charm
        zk._render_zk_properties()
        self.assertEqual(ZK_PROPERTIES,
                         self._simulate_render(
                             ctx=mock_render.call_args.kwargs["context"],
                             templ_file='zookeeper.properties.j2'))

    def test_confluent_render_service(self):
        harness = Harness(charm.ZookeeperCharm)


#    def test_cluster_relation(self):
#        harness = Harness(charm.ZookeeperCharm)
#        self.addCleanup(harness.cleanup)
#        harness.begin()
#        harness.set_leader(True)
#        cluster1 = \
#            harness.add_relation('cluster', 'zookeeper')
#        harness.add_relation_unit(cluster1, 'zookeeper/0')
#        harness.update_relation_data(cluster1, 'zookeeper/0', {"myid":1, "endpoint": "ansiblezookeeper2.example.com:2888:3888"})
#        cluster2 = \
#            harness.add_relation('cluster', 'zookeeper')
#        harness.add_relation_unit(cluster2, 'zookeeper/1')
#        harness.update_relation_data(cluster2, 'zookeeper/1', {"myid":2, "endpoint": "ansiblezookeeper3.example.com:2888:3888"})
#        cluster3 = \
#            harness.add_relation('cluster', 'zookeeper')
#        harness.add_relation_unit(cluster3, 'zookeeper/2')
#        harness.update_relation_data(cluster3, 'zookeeper/2', {"myid":3, "endpoint": "ansiblezookeeper1.example.com:2888:3888"})
#        zk = harness.charm
