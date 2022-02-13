# Copyright 2021 pguimaraes
# See LICENSE file for licensing details.

import os
import json
import unittest
from mock import patch, mock_open
from mock import PropertyMock

from ops.testing import Harness
import charm as charm
import cluster as cluster
import charms.kafka_broker.v0.charmhelper as ubuntu
import charms.zookeeper.v0.zookeeper as zkRelation
import charms.kafka_broker.v0.kafka_base_class as kafka
import charms.kafka_broker.v0.java_class as java
from nrpe.client import NRPEClient

import charms.kafka_broker.v0.charmhelper as ch_ip

import charms.kafka_broker.v0.kafka_relation_base as kafka_relation_base
from charms.kafka_broker.v0.kafka_base_class import OVERRIDE_CONF

import interface_tls_certificates.ca_client as ca_client

import charms.kafka_broker.v0.kafka_security as security


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
    'service_restart'
]


class MockEvent(object):
    def __init__(self, relations):
        self._relations = relations

    @property
    def relation(self):
        return self._relations

    def defer(self):
        return


class MockRelations(object):
    def __init__(self, data):
        self._data = data

    @property
    def network(self):
        # Workaround for network.bind_address
        return self

    @property
    def bind_address(self):
        return "127.0.0.1"

    @property
    def data(self):
        return self._data

    # Assuming just one relation exists
    @property
    def relations(self):
        return [self]

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

    @patch.object(charm, "daemon_reload")
    @patch("shutil.chown")
    @patch("os.makedirs")
    @patch.object(charm, "OpsCoordinator")
    @patch.object(cluster.ZookeeperCluster,
                  'binding_addr', new_callable=PropertyMock)
    @patch.object(cluster, 'get_hostname')
    @patch.object(cluster, "setFilePermissions")
    @patch('builtins.open',
           new_callable=mock_open, read_data='')
    @patch.object(kafka_relation_base, 'CreateTruststore')
    @patch.object(charm, 'close_port')
    @patch.object(charm, 'open_port')
    @patch.object(charm.ZookeeperCharm, '_check_if_ready_to_start')
    @patch.object(charm, 'service_resume')
    @patch.object(charm, 'service_restart')
    @patch.object(charm, 'service_running')
    @patch.object(charm.ZookeeperCharm, 'get_quorum_key')
    @patch.object(charm.ZookeeperCharm, 'get_quorum_cert')
    @patch.object(charm.ZookeeperCharm, 'get_ssl_key')
    @patch.object(charm.ZookeeperCharm, 'get_ssl_cert')
    @patch.object(charm.ZookeeperCharm, '_generate_keystores')
    @patch.object(charm.ZookeeperCharm, '_cert_relation_set')
    @patch.object(kafka, "open_port")
    @patch.object(NRPEClient, "add_check")
    @patch.object(kafka.KafkaJavaCharmBasePrometheusMonitorNode,
                  'advertise_addr', new_callable=PropertyMock)
    @patch.object(kafka.KafkaJavaCharmBasePrometheusMonitorNode,
                  'scrape_request', new_callable=PropertyMock)
    @patch.object(java, "genRandomPassword")
    @patch.object(charm, "genRandomPassword")
    # Those two patches set _cert_relation_set + get_ssl* as empty
    @patch.object(ca_client.CAClient, "_get_certs_and_keys")
    @patch.object(ca_client.CAClient, "root_ca_chain", new_callable=PropertyMock)
    @patch.object(ca_client.CAClient, "ca_certificate", new_callable=PropertyMock)
    @patch.object(ca_client.CAClient, "request_server_certificate")
    @patch.object(charm, "PKCS12CreateKeystore")
    @patch.object(kafka.KafkaJavaCharmBase, "_on_install")
    @patch.object(charm.ZookeeperCharm, "create_data_and_log_dirs")
    @patch.object(kafka.KafkaJavaCharmBase, "install_packages")
    @patch.object(charm.ZookeeperCharm, "set_folders_and_permissions")
    @patch.object(kafka, "render")
    @patch.object(kafka, "render_from_string")
    @patch.object(charm, "render")
    def test_config_no_cert(self,
                            mock_render,
                            mock_kafka_render_string,
                            mock_kafka_class_render,
                            mock_folders_perms,
                            mock_on_install_pkgs,
                            mock_create_dirs,
                            mock_super_install,
                            mock_create_jks,
                            mock_request_server_cert,
                            mock_ca_certificate,
                            mock_root_ca_chain,
                            mock_get_server_certs,
                            mock_gen_random_pwd,
                            mock_java_gen_random_pwd,
                            mock_prometheus_scrape_req,
                            mock_prometheus_advertise_addr,
                            mock_nrpe_add_check,
                            mock_kafka_open_port,
                            mock_cert_relation_set,
                            mock_generate_keystores,
                            mock_get_ssl_cert,
                            mock_get_ssl_key,
                            mock_get_quorum_ssl_cert,
                            mock_get_quorum_ssl_key,
                            mock_service_running,
                            mock_svc_restart,
                            mock_svc_resume,
                            mock_check_if_ready_restart,
                            mock_open_port,
                            mock_close_port,
                            mock_create_ts,
                            mock_open,
                            mock_set_file_perms,
                            mock_get_hostname,
                            mock_cluster_binding_addr,
                            mock_ops_coordinator,
                            mock_os_makedirs,
                            mock_shutil_chown,
                            mock_systemd_daemon_reload):
        """
        Test config changed

        No certificate data: neither cert options nor relations.

        Expected: render all the config files correctly.
        """
        # Avoid triggering the RestartEvent
        mock_service_running.return_value = False
        mock_check_if_ready_restart.return_value = False
        mock_get_hostname.return_value = \
            "ansiblezookeeper0.example.com"
        # Remove the random password generation
        mock_gen_random_pwd.return_value = "aaaa"
        mock_java_gen_random_pwd.return_value = "aaaa"
        # Prepare cleanup

        def __cleanup():
            for i in ["/tmp/testcert*", "/tmp/test-ts-quorum.jks"]:
                try:
                    os.remove(i)
                except: # noqa
                    pass

        __cleanup()
        certs = {}
        crt, key = security.generateSelfSigned("/tmp", "testcert")
        mock_get_ssl_cert.return_value = crt
        mock_get_ssl_key.return_value = key
        mock_get_quorum_ssl_cert.return_value = crt
        mock_get_quorum_ssl_key.return_value = key
        for i in range(1, 3):
            certs[i] = {}
            certs[i]["crt"] = crt
            certs[i]["key"] = key
        __cleanup()  # cleaning up the intermediate certs

        # Mock-up values
        mock_cert_relation_set.return_value = True
        # Prepare test
        harness = Harness(charm.ZookeeperCharm)
        harness.update_config({
            "version": "6.1",
            "distro": "confluent",
            "user": "test",
            "group": "test",
            "quorum-keystore-path": "",
            "quorum-truststore-path": "",
            "truststore-path": "",
            "keystore-path": "",
            "sslQuorum": False,
            "generate-root-ca": False,
            "log4j-root-logger": "DEBUG, stdout, zkAppender",
            "cluster-count": 3
        })
        # Complete the cluster
        cluster_id = harness.add_relation("cluster", "zookeeper")

        harness.add_relation_unit(cluster_id, "zookeeper/1")
        harness.update_relation_data(cluster_id, "zookeeper/1", {
            "myid": 2,
            "endpoint": "ansiblezookeeper1.example.com:2888:3888"
        })
        harness.add_relation_unit(cluster_id, "zookeeper/2")
        harness.update_relation_data(cluster_id, "zookeeper/2", {
            "myid": 3,
            "endpoint": "ansiblezookeeper2.example.com:2888:3888"
        })
        harness.begin_with_initial_hooks()
        self.addCleanup(harness.cleanup)
        zk = harness.charm
        # If cluster relation events (-joined, -changed) happens before
        # certificate events, then cluster-* will be deferred.
        # Run reemit to ensure they are run.
        zk.framework.reemit()
        # keystore is set, assert generate_keystores was called
        mock_generate_keystores.assert_not_called()
        # Assert log4j properties was correctly rendered
        mock_render.assert_any_call(
            source='zookeeper_log4j.properties.j2',
            target='/etc/kafka/zookeeper-log4j.properties',
            owner='test', group='test', perms=0o640,
            context={'root_logger': 'DEBUG, stdout, zkAppender', "zk_logger_path": '/var/log/zookeeper/zookeeper-server.log' }
        )
        # Assert the service override
        mock_kafka_render_string.assert_any_call(
            source=OVERRIDE_CONF,
            target='/etc/systemd/system/confluent-zookeeper.service.d/'
                   'override.conf',
            owner='test', group='test', perms=0o644,
            context={
                'service_unit_overrides': {},
                'service_overrides': {'User': 'test', 'Group': 'test'},
                'service_environment_overrides': {
                    'KAFKA_HEAP_OPTS': '-Xmx1g',
                    'KAFKA_LOG4J_OPTS': '-Dlog4j.configuration=file:/etc/kafka/zookeeper-log4j.properties', # noqa
                    'LOG_DIR': '/var/log/kafka',
                    'KAFKA_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048',
                    'SCHEMA_REGISTRY_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048', # noqa
                    'KSQL_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048',
                    'KAFKAREST_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048',
                    'CONTROL_CENTER_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048'}} # noqa
        )
        # Assert the zk properties was correctly rendered
        mock_render.assert_any_call(
            source='zookeeper.properties.j2',
            target='/etc/zookeeper/zookeeper.properties',
            owner='test', group='test', perms=0o640,
            context={
                'zk_props': {
                    'maxClientCnxns': 0,
                    'initLimit': 5,
                    'syncLimit': 2,
                    'autopurge.snapRetainCount': 10,
                    'autopurge.purgeInterval': 1,
                    'admin.enableServer': False,
                    'dataDir': '/var/lib/zookeeper',
                    'dataLogDir': '/var/lib/kafka/zookeeper_log',
                    'ssl.clientAuth': 'none', 'clientPort': 2182,
                    'server.2': 'ansiblezookeeper1.example.com:2888:3888',
                    'server.1': 'ansiblezookeeper0.example.com:2888:3888',
                    'server.3': 'ansiblezookeeper2.example.com:2888:3888'}}
            )

    @patch.object(charm, "daemon_reload")
    @patch("shutil.chown")
    @patch("os.makedirs")
    @patch.object(charm, "OpsCoordinator")
    @patch.object(ch_ip, 'apt_install')
    @patch.object(zkRelation.ZookeeperProvidesRelation, 'hostname',
                  new_callable=PropertyMock)
    @patch.object(zkRelation.ZookeeperProvidesRelation, 'advertise_addr',
                  new_callable=PropertyMock)
    @patch.object(cluster.ZookeeperCluster,
                  'advertise_addr', new_callable=PropertyMock)
    @patch.object(zkRelation.ZookeeperProvidesRelation, 'binding_addr',
                  new_callable=PropertyMock)
    @patch.object(cluster.ZookeeperCluster,
                  'binding_addr', new_callable=PropertyMock)
    @patch.object(cluster, 'get_hostname')
    @patch.object(cluster, "setFilePermissions")
    @patch('builtins.open',
           new_callable=mock_open, read_data='')
    @patch.object(kafka_relation_base, 'CreateTruststore')
    @patch.object(charm, 'close_port')
    @patch.object(charm, 'open_port')
    @patch.object(charm.ZookeeperCharm, '_check_if_ready_to_start')
    @patch.object(charm, 'service_resume')
    @patch.object(charm, 'service_restart')
    @patch.object(charm, 'service_running')
    @patch.object(charm.ZookeeperCharm, '_generate_keystores')
    @patch.object(kafka, "open_port")
    @patch.object(NRPEClient, "add_check")
    @patch.object(kafka.KafkaJavaCharmBasePrometheusMonitorNode,
                  'advertise_addr', new_callable=PropertyMock)
    @patch.object(kafka.KafkaJavaCharmBasePrometheusMonitorNode,
                  'scrape_request', new_callable=PropertyMock)
    @patch.object(java, "genRandomPassword")
    @patch.object(charm, "genRandomPassword")
    @patch.object(charm, "PKCS12CreateKeystore")
    @patch.object(kafka.KafkaJavaCharmBase, "_on_install")
    @patch.object(charm.ZookeeperCharm, "create_data_and_log_dirs")
    @patch.object(kafka.KafkaJavaCharmBase, "install_packages")
    @patch.object(charm.ZookeeperCharm, "set_folders_and_permissions")
    @patch.object(kafka, "render")
    @patch.object(kafka, "render_from_string")
    @patch.object(charm, "render")
    def test_config_rel_crt(self,
                            mock_render,
                            mock_kafka_render_string,
                            mock_kafka_class_render,
                            mock_folders_perms,
                            mock_on_install_pkgs,
                            mock_create_dirs,
                            mock_super_install,
                            mock_create_jks,
                            mock_gen_random_pwd,
                            mock_java_gen_random_pwd,
                            mock_prometheus_scrape_req,
                            mock_prometheus_advertise_addr,
                            mock_nrpe_add_check,
                            mock_kafka_open_port,
                            mock_generate_keystores,
                            mock_service_running,
                            mock_svc_restart,
                            mock_svc_resume,
                            mock_check_if_ready_restart,
                            mock_open_port,
                            mock_close_port,
                            mock_create_ts,
                            mock_open,
                            mock_set_file_perms,
                            mock_get_hostname,
                            mock_cluster_binding_addr,
                            mock_zk_binding_addr,
                            mock_cluster_advertise_addr,
                            mock_zk_advertise_addr,
                            mock_zk_rel_hostname,
                            mock_ch_ip_apt_install,
                            mock_ops_coordinator,
                            mock_os_makedirs,
                            mock_shutil_chown,
                            mock_systemd_daemon_reload):
        """
        Test config changed given certificates relation and cluster exists.

        Expected flow of the test and outcome:
        1) The charm will issue 2x certificate requests on request_server_cert
        2) Certificates are generated and -changed event issued
        3) Cluster also formed
        4) Check if Truststore is correctly formed with cluster certs

        Single binding set: 192.168.200.200
        """
        mock_zk_binding_addr.return_value = "192.168.200.200"
        mock_zk_advertise_addr.return_value = "192.168.200.200"
        mock_cluster_binding_addr.return_value = "192.168.200.200"
        mock_cluster_advertise_addr.return_value = "192.168.200.200"
        # Avoid triggering the RestartEvent
        mock_service_running.return_value = False
        mock_check_if_ready_restart.return_value = False
        mock_get_hostname.return_value = \
            "ansiblezookeeper0.example.com"
        mock_zk_rel_hostname.return_value = \
            "ansiblezookeeper0.example.com"
        # Remove the random password generation
        mock_gen_random_pwd.return_value = "aaaa"
        mock_java_gen_random_pwd.return_value = "aaaa"
        # Prepare cleanup

        def __cleanup():
            for i in ["/tmp/testcert*", "/tmp/test-ts-quorum.jks"]:
                try:
                    os.remove(i)
                except: # noqa
                    pass

        __cleanup()
        certs = {}
        crt, key = security.generateSelfSigned("/tmp", "testcert")
        for i in range(0, 3):
            certs[i] = {}
            certs[i]["crt"] = crt
            certs[i]["key"] = key
        __cleanup()  # cleaning up the intermediate certs

        # Prepare test
        harness = Harness(charm.ZookeeperCharm)
        harness.update_config({
            "version": "6.1",
            "distro": "confluent",
            "user": "test",
            "group": "test",
            "quorum-keystore-path": "/var/ssl/private/quorum-ks.jks",
            "quorum-truststore-path": "/var/ssl/private/quorum-ts.jks",
            "truststore-path": "/var/ssl/private/ssl-ts.jks",
            "keystore-path": "/var/ssl/private/ssl-ks.jks",
            "sslQuorum": True,
            "generate-root-ca": False,
            "log4j-root-logger": "DEBUG, stdout, zkAppender",
            "cluster-count": 3
        })
        # Certificates relation
        certificate_id = harness.add_relation("certificates", "easyrsa")
        harness.add_relation_unit(certificate_id, "easyrsa/0")
        harness.update_relation_data(certificate_id, "easyrsa/0", {
            "ca": certs[0]["crt"],
            "zookeeper_0.server.cert": certs[0]["crt"],
            "zookeeper_0.server.key": certs[0]["key"],
            "zookeeper_0.processed_requests": json.dumps({"192.168.200.200": {
                "cert": 'certs[0]["crt"]',
                "key": 'certs[0]["key"]'
            }})
        })

        # Complete the cluster
        cluster_id = harness.add_relation("cluster", "zookeeper")

        harness.add_relation_unit(cluster_id, "zookeeper/1")
        harness.update_relation_data(cluster_id, "zookeeper/1", {
            "tls_cert": certs[1]["crt"], "myid": 2,
            "endpoint": "ansiblezookeeper1.example.com:2888:3888"
        })
        harness.add_relation_unit(cluster_id, "zookeeper/2")
        harness.update_relation_data(cluster_id, "zookeeper/2", {
            "tls_cert": certs[2]["crt"], "myid": 3,
            "endpoint": "ansiblezookeeper2.example.com:2888:3888"
        })
        harness.begin_with_initial_hooks()
        self.addCleanup(harness.cleanup)
        zk = harness.charm
        # If cluster relation events (-joined, -changed) happens before
        # certificate events, then cluster-* will be deferred.
        # Run reemit to ensure they are run.
        zk.framework.reemit()

        # Check certificate and key have been correctly set:
        self.assertEqual(certs[0]["crt"], zk.get_ssl_cert())
        self.assertEqual(certs[0]["key"], zk.get_ssl_key())

        # keystore is set, assert generate_keystores was called
        mock_generate_keystores.assert_called()
        # Assert log4j properties was correctly rendered
        mock_render.assert_any_call(
            source='zookeeper_log4j.properties.j2',
            target='/etc/kafka/zookeeper-log4j.properties',
            owner='test', group='test', perms=0o640,
            context={'root_logger': 'DEBUG, stdout, zkAppender', "zk_logger_path": '/var/log/zookeeper/zookeeper-server.log' }
        )
        # Assert the service override
        mock_kafka_render_string.assert_any_call(
            source=OVERRIDE_CONF,
            target='/etc/systemd/system/confluent-zookeeper.service.d/'
                   'override.conf',
            owner='test', group='test', perms=0o644,
            context={
                'service_unit_overrides': {},
                'service_overrides': {'User': 'test', 'Group': 'test'},
                'service_environment_overrides': {
                    'KAFKA_HEAP_OPTS': '-Xmx1g',
                    'KAFKA_LOG4J_OPTS': '-Dlog4j.configuration=file:/etc/kafka/zookeeper-log4j.properties', # noqa
                    'LOG_DIR': '/var/log/kafka',
                    'KAFKA_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048',
                    'SCHEMA_REGISTRY_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048', # noqa
                    'KSQL_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048',
                    'KAFKAREST_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048',
                    'CONTROL_CENTER_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048'}} # noqa
        )
        # Assert the Truststore creation
        # Assert the zk properties was correctly rendered
        mock_render.assert_any_call(
            source='zookeeper.properties.j2',
            target='/etc/zookeeper/zookeeper.properties',
            owner='test', group='test', perms=0o640,
            context={
                'zk_props': {
                    'maxClientCnxns': 0,
                    'initLimit': 5,
                    'syncLimit': 2,
                    'autopurge.snapRetainCount': 10,
                    'autopurge.purgeInterval': 1,
                    'admin.enableServer': False,
                    'dataDir': '/var/lib/zookeeper',
                    'dataLogDir': '/var/lib/kafka/zookeeper_log',
                    'secureClientPort': 2182,
                    'serverCnxnFactory': 'org.apache.zookeeper.'
                                         'server.NettyServerCnxnFactory',
                    'authProvider.x509': 'org.apache.zookeeper.server.'
                                         'auth.X509AuthenticationProvider',
                    'sslQuorum': 'true',
                    'ssl.clientAuth': 'none',
                    'ssl.keyStore.location': '/var/ssl/private/ssl-ks.jks',
                    'ssl.keyStore.password': 'aaaa',
                    'ssl.trustStore.location': '/var/ssl/private/ssl-ts.jks',
                    'ssl.trustStore.password': 'aaaa',
                    'ssl.quorum.keyStore.location':
                    '/var/ssl/private/quorum-ks.jks',
                    'ssl.quorum.keyStore.password': 'aaaa',
                    'ssl.quorum.trustStore.location':
                    '/var/ssl/private/quorum-ts.jks',
                    'ssl.quorum.trustStore.password': 'aaaa',
                    'server.1': 'ansiblezookeeper0.example.com:2888:3888',
                    'server.2': 'ansiblezookeeper1.example.com:2888:3888',
                    'server.3': 'ansiblezookeeper2.example.com:2888:3888'
                }}
            )


    @patch.object(charm, "daemon_reload")
    @patch("shutil.chown")
    @patch("os.makedirs")
    @patch.object(charm, "OpsCoordinator")
    @patch.object(cluster.ZookeeperCluster,
                  'binding_addr', new_callable=PropertyMock)
    @patch.object(cluster, 'get_hostname')
    @patch.object(cluster, "setFilePermissions")
    @patch('builtins.open',
           new_callable=mock_open, read_data='')
    @patch.object(kafka_relation_base, 'CreateTruststore')
    @patch.object(charm, 'close_port')
    @patch.object(charm, 'open_port')
    @patch.object(charm.ZookeeperCharm, '_check_if_ready_to_start')
    @patch.object(charm, 'service_resume')
    @patch.object(charm, 'service_restart')
    @patch.object(charm, 'service_running')
    @patch.object(charm.ZookeeperCharm, 'get_quorum_key')
    @patch.object(charm.ZookeeperCharm, 'get_quorum_cert')
    @patch.object(charm.ZookeeperCharm, 'get_ssl_key')
    @patch.object(charm.ZookeeperCharm, 'get_ssl_cert')
    @patch.object(charm.ZookeeperCharm, '_generate_keystores')
    @patch.object(charm.ZookeeperCharm, '_cert_relation_set')
    @patch.object(kafka, "open_port")
    @patch.object(NRPEClient, "add_check")
    @patch.object(kafka.KafkaJavaCharmBasePrometheusMonitorNode,
                  'advertise_addr', new_callable=PropertyMock)
    @patch.object(kafka.KafkaJavaCharmBasePrometheusMonitorNode,
                  'scrape_request', new_callable=PropertyMock)
    @patch.object(java, "genRandomPassword")
    @patch.object(charm, "genRandomPassword")
    # Those two patches set _cert_relation_set + get_ssl* as empty
    @patch.object(ca_client.CAClient, "_get_certs_and_keys")
    @patch.object(ca_client.CAClient, "root_ca_chain", new_callable=PropertyMock)
    @patch.object(ca_client.CAClient, "ca_certificate", new_callable=PropertyMock)
    @patch.object(ca_client.CAClient, "request_server_certificate")
    @patch.object(charm, "PKCS12CreateKeystore")
    @patch.object(kafka.KafkaJavaCharmBase, "_on_install")
    @patch.object(charm.ZookeeperCharm, "create_data_and_log_dirs")
    @patch.object(kafka.KafkaJavaCharmBase, "install_packages")
    @patch.object(charm.ZookeeperCharm, "set_folders_and_permissions")
    @patch.object(kafka, "render")
    @patch.object(kafka, "render_from_string")
    @patch.object(charm, "render")
    def test_config_changed(self,
                            mock_render,
                            mock_kafka_render_string,
                            mock_kafka_class_render,
                            mock_folders_perms,
                            mock_on_install_pkgs,
                            mock_create_dirs,
                            mock_super_install,
                            mock_create_jks,
                            mock_request_server_cert,
                            mock_ca_certificate,
                            mock_root_ca_chain,
                            mock_get_server_certs,
                            mock_gen_random_pwd,
                            mock_java_gen_random_pwd,
                            mock_prometheus_scrape_req,
                            mock_prometheus_advertise_addr,
                            mock_nrpe_add_check,
                            mock_kafka_open_port,
                            mock_cert_relation_set,
                            mock_generate_keystores,
                            mock_get_ssl_cert,
                            mock_get_ssl_key,
                            mock_get_quorum_ssl_cert,
                            mock_get_quorum_ssl_key,
                            mock_service_running,
                            mock_svc_restart,
                            mock_svc_resume,
                            mock_check_if_ready_restart,
                            mock_open_port,
                            mock_close_port,
                            mock_create_ts,
                            mock_open,
                            mock_set_file_perms,
                            mock_get_hostname,
                            mock_cluster_binding_addr,
                            mock_ops_coordinator,
                            mock_os_makedirs,
                            mock_shutil_chown,
                            mock_systemd_daemon_reload):

        # Avoid triggering the RestartEvent
        mock_service_running.return_value = False
        mock_check_if_ready_restart.return_value = False
        mock_get_hostname.return_value = \
            "ansiblezookeeper0.example.com"
        # Remove the random password generation
        mock_gen_random_pwd.return_value = "aaaa"
        mock_java_gen_random_pwd.return_value = "aaaa"
        # Prepare cleanup

        def __cleanup():
            for i in ["/tmp/testcert*", "/tmp/test-ts-quorum.jks"]:
                try:
                    os.remove(i)
                except: # noqa
                    pass

        __cleanup()
        certs = {}
        crt, key = security.generateSelfSigned("/tmp", "testcert")
        mock_get_ssl_cert.return_value = crt
        mock_get_ssl_key.return_value = key
        mock_get_quorum_ssl_cert.return_value = crt
        mock_get_quorum_ssl_key.return_value = key
        for i in range(1, 3):
            certs[i] = {}
            certs[i]["crt"] = crt
            certs[i]["key"] = key
        __cleanup()  # cleaning up the intermediate certs

        # Mock-up values
        mock_cert_relation_set.return_value = True
        # Prepare test
        harness = Harness(charm.ZookeeperCharm)
        harness.update_config({
            "version": "6.1",
            "distro": "confluent",
            "user": "test",
            "group": "test",
            "quorum-keystore-path": "/var/ssl/private/quorum-ks.jks",
            "quorum-truststore-path": "/var/ssl/private/quorum-ts.jks",
            "truststore-path": "/var/ssl/private/ssl-ts.jks",
            "keystore-path": "/var/ssl/private/ssl-ks.jks",
            "sslQuorum": True,
            "generate-root-ca": False,
            "log4j-root-logger": "DEBUG, stdout, zkAppender",
            "cluster-count": 3
        })
        # Complete the cluster
        cluster_id = harness.add_relation("cluster", "zookeeper")

        harness.add_relation_unit(cluster_id, "zookeeper/1")
        harness.update_relation_data(cluster_id, "zookeeper/1", {
            "tls_cert": certs[1]["crt"], "myid": 2,
            "endpoint": "ansiblezookeeper1.example.com:2888:3888"
        })
        harness.add_relation_unit(cluster_id, "zookeeper/2")
        harness.update_relation_data(cluster_id, "zookeeper/2", {
            "tls_cert": certs[2]["crt"], "myid": 3,
            "endpoint": "ansiblezookeeper2.example.com:2888:3888"
        })
        harness.begin_with_initial_hooks()
        self.addCleanup(harness.cleanup)
        zk = harness.charm
        # If cluster relation events (-joined, -changed) happens before
        # certificate events, then cluster-* will be deferred.
        # Run reemit to ensure they are run.
        zk.framework.reemit()
        # keystore is set, assert generate_keystores was called
        mock_generate_keystores.assert_called()
        # Assert log4j properties was correctly rendered
        mock_render.assert_any_call(
            source='zookeeper_log4j.properties.j2',
            target='/etc/kafka/zookeeper-log4j.properties',
            owner='test', group='test', perms=0o640,
            context={'root_logger': 'DEBUG, stdout, zkAppender', "zk_logger_path": '/var/log/zookeeper/zookeeper-server.log' }
        )
        # Assert the service override
        mock_kafka_render_string.assert_any_call(
            source=OVERRIDE_CONF,
            target='/etc/systemd/system/confluent-zookeeper.service.d/'
                   'override.conf',
            owner='test', group='test', perms=0o644,
            context={
                'service_unit_overrides': {},
                'service_overrides': {'User': 'test', 'Group': 'test'},
                'service_environment_overrides': {
                    'KAFKA_HEAP_OPTS': '-Xmx1g',
                    'KAFKA_LOG4J_OPTS': '-Dlog4j.configuration=file:/etc/kafka/zookeeper-log4j.properties', # noqa
                    'LOG_DIR': '/var/log/kafka',
                    'KAFKA_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048',
                    'SCHEMA_REGISTRY_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048', # noqa
                    'KSQL_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048',
                    'KAFKAREST_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048',
                    'CONTROL_CENTER_OPTS': '-Djdk.tls.ephemeralDHKeySize=2048'}} # noqa
        )
        # Assert the zk properties was correctly rendered
        mock_render.assert_any_call(
            source='zookeeper.properties.j2',
            target='/etc/zookeeper/zookeeper.properties',
            owner='test', group='test', perms=0o640,
            context={
                'zk_props': {
                    'maxClientCnxns': 0,
                    'initLimit': 5,
                    'syncLimit': 2,
                    'autopurge.snapRetainCount': 10,
                    'autopurge.purgeInterval': 1,
                    'admin.enableServer': False,
                    'dataDir': '/var/lib/zookeeper',
                    'dataLogDir': '/var/lib/kafka/zookeeper_log',
                    'secureClientPort': 2182,
                    'serverCnxnFactory': 'org.apache.zookeeper.'
                                         'server.NettyServerCnxnFactory',
                    'authProvider.x509': 'org.apache.zookeeper.server.'
                                         'auth.X509AuthenticationProvider',
                    'sslQuorum': 'true',
                    'ssl.clientAuth': 'none',
                    'ssl.keyStore.location': '/var/ssl/private/ssl-ks.jks',
                    'ssl.keyStore.password': 'aaaa',
                    'ssl.trustStore.location': '/var/ssl/private/ssl-ts.jks',
                    'ssl.trustStore.password': 'aaaa',
                    'ssl.quorum.keyStore.location':
                    '/var/ssl/private/quorum-ks.jks',

                    'ssl.quorum.keyStore.password': 'aaaa',
                    'ssl.quorum.trustStore.location':
                    '/var/ssl/private/quorum-ts.jks',

                    'ssl.quorum.trustStore.password': 'aaaa',
                    'server.2': 'ansiblezookeeper1.example.com:2888:3888',
                    'server.1': 'ansiblezookeeper0.example.com:2888:3888',
                    'server.3': 'ansiblezookeeper2.example.com:2888:3888'
                }}
            )
