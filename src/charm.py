#!/usr/bin/env python3
# Copyright 2021 pguimaraes
# See LICENSE file for licensing details.

import logging
import yaml

from ops.main import main
from ops.model import BlockedStatus, ActiveStatus


from charmhelpers.core.templating import render
from charmhelpers.core.host import (
    service_running,
    service_restart,
    service_reload
)

from wand.apps.kafka import KafkaJavaCharmBase
from .cluster import ZookeeperCluster
from wand.apps.relations.zookeeper import ZookeeperProvidesRelation
from wand.security.ssl import CreateKeystoreAndTruststore

logger = logging.getLogger(__name__)


class ZookeeperCharm(KafkaJavaCharmBase):
    """Charm the service."""

    CONFLUENT_PACKAGES = [
        "confluent-common",
        "confluent-rest-utils",
        "confluent-metadata-service",
        "confluent-ce-kafka-http-server",
        "confluent-kafka-rest",
        "confluent-server-rest",
        "confluent-telemetry",
        "confluent-server"
    ]

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.cluster_relation_changed,
                               self._on_cluster_relation_changed)
        self.zk = ZookeeperProvidesRelation(self, 'zookeeper',
                                            self.config.get('clientPort',
                                                            2182))
        self.cluster = ZookeeperCluster(self, 'cluster')

    def _on_install(self, event):
        packages = []
        # TODO: IMPLEMENT IT
        # self._install_tarball()
        if self.distro == "confluent":
            packages = self.CONFLUENT_PACKAGES
        else:
            raise Exception("Not Implemented Yet")
        super().install_packages('openjdk-11-headless', packages)
        # The logic below avoid an error such as more than one entry
        # In this case, we will pick the first entry
        data_log_fs, data_log_dir = \
            [k for k, v in self.config["data-log-dir"]][0]
        data_fs, data_dir = \
            [k for k, v in self.config["data-dir"]][0]
        self.create_data_and_log_dirs(self.config["data-log-device"],
                                      self.config["data-device"],
                                      data_log_dir,
                                      data_dir,
                                      data_log_fs,
                                      data_fs,
                                      self.config.get("user",
                                                      "cp-kafka"),
                                      self.config.get("group",
                                                      "confluent"),
                                      self.config.get("fs-options", None)
                                      )
        self._render_zk_properties()

    def _on_cluster_relation_changed(self, event):
        self._on_config_changed(event)

    def _check_if_ready(self):
        if not self.cluster.is_ready:
            BlockedStatus("Waiting for cluster relation")
            return
        if not service_running(self.service):
            BlockedStatus("Service not running {}".format(self.service))
            return
        ActiveStatus("{} running".format(self.service))

    def _render_zk_properties(self):
        zk_props = self.config.get("zookeeper-properties", "") or {}
        if self.is_client_ssl_enabled():
            PKCS12CreateKeystore(
                "/var/ssl/private/zookeeper.keystore.jks",
                self.ks.ks_password,
                self.config["ssl_cert"],
                self.config["ssl_key"],
                user=self.config.get('user'),
                group=self.config.get('group'),
                mode=0o640)
            zk_props["serverCnxnFactory"] = \
                "org.apache.zookeeper.server.NettyServerCnxnFactory"
            zk_props["authProvider.x509"] = \
                "org.apache.zookeeper.server.auth.X509AuthenticationProvider"
            zk_props["sslQuorum"] = "false"  # We change this later down the line if needed
            zk_props["ssl.clientAuth"] = \
                "none" if not self.config["mtls-enabled"] else "need"
            zk_props["ssl.keyStore.location"] = \
                "/var/ssl/private/zookeeper.keystore.jks"
            zk_props["ssl.keyStore.password"] = self.ks.ks_password
            zk_props["ssl.trustStore.location"] = \
                "/var/ssl/private/zookeeper.truststore.jks"
            zk_props["ssl.trustStore.password"] = self.ks.ts_password
            # Now that mTLS is set, we announce it to the neighbours
            self.zk.set_mTLS_auth(self.config["ssl_cert"],
                                  "/var/ssl/private/zookeeper.truststore.jks",
                                  self.ks.ts_password)

        # As described on: https://zookeeper.apache.org/doc/r3.5.7/zookeeperAdmin.html#Quorum+TLS
        if self.config.get("ssl_quorum", False):
            zk_props["serverCnxnFactory"] = \
                "org.apache.zookeeper.server.NettyServerCnxnFactory"
            # TODO(pguimaraes): the sslquorum should be a StoredState with cert/key.
            # This cert/key should be mounted either via action or vault relation
            PKCS12CreateKeystore(
                "/var/ssl/private/zookeeper.quorum.keystore.jks",
                self.ks.ks_password,
                self.sslquorum.quorum_cert,
                self.sslquorum.quorum_key,
                user=self.config.get('user'),
                group=self.config.get('group'),
                mode=0o640)
            # TODO(pguimaraes): cluster.py should be the one checking the ssl_quorum_chain
            # on each of the units and creating a truststore on a predefined place.
            # The method below should advise the cluster unit to publish its own certificate
            # to the peers and save their certs on a truststore on:
            # /var/ssl/private/zookeeper.quorum.keystore.jks
            cluster.enable_ssl_quorum(self.sslquorum.quorum_cert,
                                      "/var/ssl/private/zookeeper.quorum.keystore.jks"
                                      self.ks.ts_password)
            zk_props["ssl.quorum.keyStore.location"] = \
                "/var/ssl/private/zookeeper.keystore.jks"
            zk_props["ssl.quorum.keyStore.password"] = self.ks.ks_password
            zk_props["ssl.quorum.trustStore.location"] = \
                "/var/ssl/private/zookeeper.truststore.jks"
            zk_props["ssl.quorum.trustStore.password"] = self.ks.ts_password
            zk_props["sslQuorum"] = "true"

        if not self.cluster.is_ready:
            # We leave this condition once myid is set across the units
            BlockedStatus("Waiting for cluster to bootstrap")
            return
        zk_list = self.cluster.get_peers
        for i in range(0, len(zk_list)):
            zk_props["server.{}".format(zk_list[i]["myid"])] = \
                zk_list[i]["endpoint"]
        render(source="zookeeper.properties.j2",
               target="/etc/kafka/zookeeper.properties",
               owner=self.config.get('user'),
               group=self.config.get("group"),
               perms=0o640,
               context={
                   "zk_props": zk_props
               })

    def _render_zk_log4j_properties(self):
        root_logger = self.config.get("log4j-root-logger", None) or \
            "INFO, stdout, zkAppender"
        render(source="zookeeper_log4j.properties.j2",
               target="/etc/kafka/zookeeper-log4j.properties",
               owner=self.config.get('user'),
               group=self.config.get("group"),
               perms=0o640,
               context={
                   "root_logger": root_logger
               })

    def _render_service_file(self):
        zookeeper_service_unit_overrides = yaml.safe_load(
            self.config.get('service-unit-overrides', ""))
        zookeeper_service_overrides = yaml.safe_load(
            self.config.get('service-overrides', ""))
        zookeeper_service_environment_overrides = yaml.safe_load(
            self.config.get('service-environment-overrides', ""))
        if self.is_ssl_enabled():
            zookeeper_service_environment_overrides["KAFKA_OPTS"] = \
                zookeeper_service_environment_overrides["KAFKA_OPTS"] + \
                "-Djdk.tls.ephemeralDHKeySize=2048"
        if self.is_kerberos_enabled() or self.is_digest_enabled():
            zookeeper_service_environment_overrides["KAFKA_OPTS"] = \
                zookeeper_service_environment_overrides["KAFKA_OPTS"] + \
                "-Djava.security.auth.login.config=" + \
                "/etc/kafka/zookeeper_jaas.conf"
        if self.is_jolokia_enabled():
            zookeeper_service_environment_overrides["KAFKA_OPTS"] = \
                zookeeper_service_environment_overrides["KAFKA_OPTS"] + \
                "-javaagent:/opt/jolokia/jolokia.jar=" + \
                "config=/etc/kafka/zookeeper_jolokia.properties"
        if self.is_jmxexporter_enabled():
            zookeeper_service_environment_overrides["KAFKA_OPTS"] = \
                zookeeper_service_environment_overrides["KAFKA_OPTS"] + \
                "-javaagent:/opt/prometheus/jmx_prometheus_javaagent.jar=" + \
                "{}:/opt/prometheus/zookeeper.yml" \
                .format(self.config.get("jmx-exporter-port", 8079))

        zookeeper_service_overrides["User"] = \
            "".formatself.config.get('user')
        zookeeper_service_overrides["Group"] = \
            self.config.get('group')
        if self.config.get("install_method", "").lower() == "archive":
            zookeeper_service_overrides["ExecStart"] = \
                "/usr/bin/zookeeper-server-start " + \
                "/etc/kafka/zookeeper.properties"
        target = None
        if self.distro == "confluent":
            target = "/etc/systemd/system/" + \
                     "confluent-zookeeper.service.d/override.conf"
        elif self.distro == "apache":
            raise Exception("Not Implemented Yet")
        render(source="override.conf.j2",
               target=target,
               owner=self.config.get('user'),
               group=self.config.get("group"),
               perms=0o644,
               context={
                   "zookeeper_service_unit_overrides": zookeeper_service_unit_overrides,
                   "zookeeper_service_overrides": zookeeper_service_overrides,
                   "zookeeper_service_environment_overrides": zookeeper_service_environment_overrides
               })

    def _on_config_changed(self, _):
        if self.distro == 'confluent':
            self.service == 'confluent-zookeeper'
        elif self.distro == "apache":
            self.service == "zookeeper"
        self._render_zk_properties()
        self._render_zk_log4j_properties()
        self._render_service_file()
        service_reload(self.service)
        service_restart(self.service)
        self._check_if_ready()


if __name__ == "__main__":
    main(ZookeeperCharm)
