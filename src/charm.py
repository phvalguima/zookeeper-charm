#!/usr/bin/env python3
# Copyright 2021 pguimaraes
# See LICENSE file for licensing details.

import base64
import logging
import os
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
from wand.security.ssl import PKCS12CreateKeystore
from wand.security.ssl import genRandomPassword
from wand.security.ssl import generateSelfSigned

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
        self.ks.set_default(quorum_cert="")
        self.ks.set_default(quorum_key="")
        self.ks.set_default(ssl_cert="")
        self.ks.set_default(ssl_key="")
        os.makedirs("/var/ssl/private", exist_ok=True)
        self._generate_keystores()

    def get_ssl_cert(self):
        if len(self.ks.ssl_cert) > 0:
            return self.ks.ssl_cert
        return base64.b64decode(self.config["ssl_cert"]).decode("ascii")

    def get_ssl_key(self):
        if len(self.ks.ssl_key) > 0:
            return self.ks.ssl_key
        return base64.b64decode(self.config["ssl_key"]).decode("ascii")

    def get_quorum_cert(self):
        # TODO(pguimaraes): expand it to count
        # with certificates relation or action cert/key
        if len(self.ks.quorum_cert) > 0:
            return self.ks.quorum_cert
        return base64.b64decode(self.config["ssl-quorum-cert"]).decode("ascii")

    def get_quorum_key(self):
        # TODO(pguimaraes): expand it to count
        # with certificates relation or action cert/key
        if len(self.ks.quorum_key) > 0:
            return self.ks.quorum_key
        return base64.b64decode(self.config["ssl-quorum-key"]).decode("ascii")

    @property
    def unit_folder(self):
        # Using as a method so we can also mock it on unit tests
        return os.getenv("JUJU_CHARM_DIR")

    def _generate_keystores(self):
        if self.config["generate-root-ca"]:
            self.ks.quorum_cert, self.ks.quorum_key = \
                generateSelfSigned(self.unit_folder,
                                   certname="quorum-zookeeper-root-ca",
                                   user=self.config["user"],
                                   group=self.config["group"],
                                   mode=0o640)
            self.ks.ssl_cert, self.ks.ssl_key = \
                generateSelfSigned(self.unit_folder,
                                   certname="ssl-zookeeper-root-ca",
                                   user=self.config["user"],
                                   group=self.config["group"],
                                   mode=0o640)
        else:
            # Certs already set either as configs or certificates relation
            self.ks.quorum_cert = self.get_quorum_cert()
            self.ks.quorum_key = self.get_quorum_key()
            self.ks.ssl_cert = self.get_ssl_cert()
            self.ks.ssl_key = self.get_ssl_key()
        self.ks.ks_zookeeper_pwd = genRandomPassword()
        self.ks.ts_zookeeper_pwd = genRandomPassword()
        if len(self.ks.quorum_cert) > 0 and \
           len(self.ks.quorum_key) > 0:
            filename = genRandomPassword(6)
            PKCS12CreateKeystore(
                self.config.get("quorum-keystore-path",
                                "/var/ssl/private/" +
                                "zookeeper.quorum.keystore.jks"),
                self.ks.ks_zookeeper_pwd,
                self.get_quorum_cert(),
                self.get_quorum_key(),
                user=self.config["user"],
                group=self.config["group"],
                mode=0o640,
                openssl_chain_path="/tmp/" + filename + ".chain",
                openssl_key_path="/tmp/" + filename + ".key",
                openssl_p12_path="/tmp/" + filename + ".p12")
        if len(self.ks.ssl_cert) > 0 and \
           len(self.ks.ssl_key) > 0:
            filename = genRandomPassword(6)
            PKCS12CreateKeystore(
                self.config.get(
                    "keystore-path",
                    "/var/ssl/private/zookeeper.keystore.jks"),
                self.ks.ks_password,
                self.get_ssl_cert(),
                self.get_ssl_key(),
                user=self.config["user"],
                group=self.config["group"],
                mode=0o640,
                openssl_chain_path="/tmp/" + filename + ".chain",
                openssl_key_path="/tmp/" + filename + ".key",
                openssl_p12_path="/tmp/" + filename + ".p12")

    def _on_install(self, event):
        packages = []
        # TODO(pguimares): implement install_tarball logic
        # self._install_tarball()
        if self.distro == "confluent":
            packages = self.CONFLUENT_PACKAGES
        else:
            raise Exception("Not Implemented Yet")
        super().install_packages('openjdk-11-headless', packages)
        # The logic below avoid an error such as more than one entry
        # In this case, we will pick the first entry
        data_log_fs = list(self.config["data-log-dir"].items())[0][0]
        data_log_dir = list(self.config["data-log-dir"].items())[0][1]
        data_fs = list(self.config["data-dir"].items())[0][0]
        data_dir = list(self.config["data-dir"].items())[0][1]
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
        zk_props["dataDir"] = \
            list(yaml.safe_load(self.config["data-dir"]).items())[0][1]
        zk_props["dataLogDir"] = \
            list(yaml.safe_load(self.config["data-log-dir"]).items())[0][1]
        if len(self.ks.ssl_cert) > 0 and \
           len(self.ks.ssl_key) > 0:
            zk_props["secureClientPort"] = self.config.get("clientPort", 2182)
            zk_props["serverCnxnFactory"] = \
                "org.apache.zookeeper.server.NettyServerCnxnFactory"
            zk_props["authProvider.x509"] = \
                "org.apache.zookeeper.server.auth.X509AuthenticationProvider"
            # We change this later down the line if needed
            zk_props["sslQuorum"] = "false"
            # Used for client-server communication
            zk_props["ssl.clientAuth"] = "need"
            zk_props["ssl.keyStore.location"] = \
                self.config.get(
                    "keystore-path",
                    "/var/ssl/private/zookeeper.keystore.jks")
            zk_props["ssl.keyStore.password"] = self.ks.ks_password
            zk_props["ssl.trustStore.location"] = \
                self.config.get(
                    "truststore-path",
                    "/var/ssl/private/zookeeper.truststore.jks")
            zk_props["ssl.trustStore.password"] = self.ks.ts_password
            # Now that mTLS is set, we announce it to the neighbours
            self.zk.set_mTLS_auth(
                self.config["ssl_cert"],
                self.config.get(
                    "truststore-path",
                    "/var/ssl/private/zookeeper.truststore.jks"),
                self.ks.ts_password)
        else:
            zk_props["ssl.clientAuth"] = "none"
            zk_props["clientPort"] = self.config.get("clientPort", 2182)

        # As described on:
        # https://zookeeper.apache.org/doc/r3.5.7/ \
        # zookeeperAdmin.html#Quorum+TLS
        if self.config.get("ssl_quorum", False):
            zk_props["serverCnxnFactory"] = \
                "org.apache.zookeeper.server.NettyServerCnxnFactory"
            self.cluster.set_ssl_keypair(
                self.get_quorum_cert(),
                self.config.get(
                    "quorum-truststore-path",
                    "/var/ssl/private/zookeeper.quorum.truststore.jks"),
                self.ks.ts_zookeeper_pwd,
                user=self.config["user"],
                group=self.config["group"],
                mode=0o640)
            zk_props["ssl.quorum.keyStore.location"] = \
                self.config.get(
                    "quorum-keystore-path",
                    "/var/ssl/private/zookeeper.quorum.keystore.jks")
            zk_props["ssl.quorum.keyStore.password"] = self.ks.ks_zookeeper_pwd
            zk_props["ssl.quorum.trustStore.location"] = \
                self.config.get(
                    "quorum-truststore-path",
                    "/var/ssl/private/zookeeper.truststore.jks")
            zk_props["ssl.quorum.trustStore.password"] = \
                self.ks.ts_zookeeper_pwd
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
                   "zookeeper_service_unit_overrides": zookeeper_service_unit_overrides, # noqa
                   "zookeeper_service_overrides": zookeeper_service_overrides, # noqa
                   "zookeeper_service_environment_overrides": zookeeper_service_environment_overrides # noqa
               })

    def _on_config_changed(self, _):
        if self.distro == 'confluent':
            self.service = 'confluent-zookeeper'
        elif self.distro == "apache":
            self.service = "zookeeper"
        self._generate_keystores()
        self._render_zk_properties()
        self._render_zk_log4j_properties()
        self._render_service_file()
        service_reload(self.service)
        service_restart(self.service)
        self._check_if_ready()


if __name__ == "__main__":
    main(ZookeeperCharm)
