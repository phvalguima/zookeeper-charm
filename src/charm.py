#!/usr/bin/env python3
# Copyright 2021 pguimaraes
# See LICENSE file for licensing details.

import logging

from ops.charm import CharmBase
from ops.main import main
from ops.framework import StoredState
from ops.model import BlockedStatus, MaintenanceStatus, ActiveStatus


from charmhelpers.core import (
    render,
    service_running,
    service_restart,
    service_reload
)

from java import KafkaJavaCharmBase
from cluster import KafkaBrokerCluster
from zookeeper import ZookeeperProvidesRelation

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
        self.framework.observe(charm.on.cluster_relation_changed, self._on_cluster_relation_changed)
        self.zk = ZookeeperProvidesRelation(self, 'zookeeper', self.config.get('clientPort', 2182))
        self.cluster = ZookeeperCluster(self, 'cluster')

    def _on_install(self, event):
        packages = []
            self._install_tarball()
        if self.distro == "confluent":
            packages = self.CONFLUENT_PACKAGES
        else:
            raise Exception("Not Implemented Yet")
        super().install_packages('openjdk-11-headless', packages)
        data_log_fs, data_log_dir = \ # The logic below avoid an error such as more than one entry
            [k for k,v in yaml.safe_load(self.config["data-log-dir"])][0]
        data_fs, data_dir = \ # The logic below avoid an error such as more than one entry
            [k for k,v in yaml.safe_load(self.config["data-dir"])][0]
        self.create_data_and_log_dirs(self.config["data-log-device"],
                                      self.config["data-device"],
                                      data_log_dir,
                                      data_dir,
                                      data_log_fs,
                                      data_fs,
                                      self.config.get("zookeeper-user","cp-kafka"),
                                      self.config.get("zookeeper-group", "confluent"),
                                      self.config.get("fs-options", None)
                                      )
        self._render_zk_properties()

    def _on_cluster_relation_changed(self, event):
        _on_config_changed()

    def _check_if_ready(self):
        if not self.cluster.is_ready:
            BlockedStatus("Waiting for cluster relation")
            return
        if not service_running(self.service):
            BlockedStatus("Service not running {}".format(self.service))
            return
        ActiveStatus("{} running".format(self.service))

    def _render_zk_properties(self):
        zk_props = yaml.safe_load(self.config.get("zookeeper-properties", "")) or {}
        if self.is_ssl_enabled():
            zk_props["serverCnxnFactory"] = "org.apache.zookeeper.server.NettyServerCnxnFactory"
            zk_props["authProvider.x509"] = "org.apache.zookeeper.server.auth.X509AuthenticationProvider"
            zk_props["sslQuorum"] = "true"
            zk_props["ssl.clientAuth"] = "none" if not self.config["mtls-enabled"] else "need"
            zk_props["ssl.keyStore.location"] = "/var/ssl/private/zookeeper.keystore.jks"
            zk_props["ssl.keyStore.password"] = ks_password
            zk_props["ssl.quorum.keyStore.location"] = "/var/ssl/private/zookeeper.keystore.jks"
            zk_props["ssl.quorum.keyStore.password"] = ks_password
            zk_props["ssl.quorum.trustStore.location"] = "/var/ssl/private/zookeeper.truststore.jks"
            zk_props["ssl.quorum.trustStore.password"] = ts_password
            zk_props["ssl.trustStore.location"] = "/var/ssl/private/zookeeper.truststore.jks"
            zk_props["ssl.trustStore.password"] = ts_password

        if not self.cluster.is_ready:
            # We leave this condition once myid is set across the units
            BlockedStatus("Waiting for cluster to bootstrap")
            return
        zk_list = self.cluster.get_peers
        for i in range(0,len(zk_list)):
            zk_props["server.{}".format(zk_list[i]["myid"])] = zk_list[i]["endpoint"]
        render(source="zookeeper.properties.j2",
               target="/etc/kafka/zookeeper.properties",
               user=self.config.get('zookeeper-user'),
               group=self.config.get("zookeeper-group"),
               perms=0o640,
               context={
                   "zk_props": zk_props
               })

    def _render_zk_log4j_properties():
        root_logger = self.config.get("log4j-root-logger",None) or "INFO, stdout, zkAppender"
        render(source="zookeeper_log4j.properties.j2",
               target="/etc/kafka/zookeeper-log4j.properties",
               user=self.config.get('zookeeper-user'),
               group=self.config.get("zookeeper-group"),
               perms=0o640,
               context={
                   "root_logger": root_logger
               })

    def _render_service_file(self):
        zookeeper_service_unit_overrides = yaml.safe_load(
            self.config.get('service-unit-overrides',""))
        zookeeper_service_overrides = yaml.safe_load(
            self.config.get('service-overrides',""))
        zookeeper_service_environment_overrides = yaml.safe_load(
            self.config.get('service-environment-overrides',""))
        if self.is_ssl_enabled():
            zookeeper_service_environment_overrides["KAFKA_OPTS"] = \
                zookeeper_service_environment_overrides["KAFKA_OPTS"] + \
                "-Djdk.tls.ephemeralDHKeySize=2048"
        if self.is_kerberos_enabled() or self.is_digest_enabled():
            zookeeper_service_environment_overrides["KAFKA_OPTS"] = \
                zookeeper_service_environment_overrides["KAFKA_OPTS"] + \
                "-Djava.security.auth.login.config=/etc/kafka/zookeeper_jaas.conf"
        if self.is_jolokia_enabled():
            zookeeper_service_environment_overrides["KAFKA_OPTS"] = \
                zookeeper_service_environment_overrides["KAFKA_OPTS"] + \
                "-javaagent:/opt/jolokia/jolokia.jar=config=/etc/kafka/zookeeper_jolokia.properties"
        if self.is_jmxexporter_enabled():
            zookeeper_service_environment_overrides["KAFKA_OPTS"] = \
                zookeeper_service_environment_overrides["KAFKA_OPTS"] + \
                "-javaagent:/opt/prometheus/jmx_prometheus_javaagent.jar="
                "{}:/opt/prometheus/zookeeper.yml".format(self.config.get("jmx-exporter-port",8079))

        zookeeper_service_overrides["User"] = "".formatself.config.get('zookeeper-user')
        zookeeper_service_overrides["Group"] = self.config.get('zookeeper-group')
        if self.config.get("install_method","").lower() == "archive":
            zookeeper_service_overrides["ExecStart"] = "/usr/bin/zookeeper-server-start /etc/kafka/zookeeper.properties"
        target = None
        if self.distro == "confluent":
            target = "/etc/systemd/system/confluent-zookeeper.service.d/override.conf"
        elif self.distro == "apache":
            raise Exception("Not Implemented Yet")
        render(source="override.conf.j2",
               target=target,
               user=self.config.get('zookeeper-user'),
               group=self.config.get("zookeeper-group"),
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
        _render_zk_properties()
        _render_zk_log4j_properties()
        _render_service_file()
        service_reload(self.service)
        service_restart(self.service)
        self._check_if_ready()


if __name__ == "__main__":
    main(ZookeeperCharm)
