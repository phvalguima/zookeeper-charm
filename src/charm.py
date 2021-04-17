#!/usr/bin/env python3
# Copyright 2021 pguimaraes
# See LICENSE file for licensing details.

import base64
import logging
import os
import yaml

from ops.main import main
from ops.model import (
    BlockedStatus,
    ActiveStatus,
    MaintenanceStatus
)

from charmhelpers.core.templating import render
from charmhelpers.core.host import (
    service_resume,
    service_running,
    service_restart,
    service_reload
)

from wand.apps.kafka import KafkaJavaCharmBase
from cluster import ZookeeperCluster
from wand.apps.relations.zookeeper import (
    ZookeeperProvidesRelation
)
from wand.apps.relations.kafka_relation_base import (
    KafkaRelationBaseNotUsedError,
    KafkaRelationBaseTLSNotSetError
)

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
        self.framework.observe(self.on.cluster_relation_joined,
                               self._on_cluster_relation_joined)
        self.framework.observe(self.on.cluster_relation_changed,
                               self._on_cluster_relation_changed)
        self.framework.observe(self.on.zookeeper_relation_joined,
                               self.on_zookeeper_relation_joined)
        self.framework.observe(self.on.zookeeper_relation_changed,
                               self.on_zookeeper_relation_changed)
        self.framework.observe(self.on.update_status,
                               self.on_update_status)
        self.zk = ZookeeperProvidesRelation(self, 'zookeeper',
                                            self.config.get('clientPort',
                                                            2182))
        myidfolder = \
            list(yaml.safe_load(
                     self.config.get("data-dir", "")).items())[0][1]
        self.cluster = ZookeeperCluster(self, 'cluster',
                                        myidfolder or "/var/ssl/private",
                                        self.config.get("cluster-count", 3))
        self.ks.set_default(quorum_cert="")
        self.ks.set_default(quorum_key="")
        self.ks.set_default(ssl_cert="")
        self.ks.set_default(ssl_key="")
        self.ks.set_default(ts_zookeeper_pwd=genRandomPassword())
        self.ks.set_default(ks_zookeeper_pwd=genRandomPassword())
        # This folder needs to be set as root
        os.makedirs("/var/ssl/private", exist_ok=True)

    def on_update_status(self, event):
        if not service_running(self.service):
            self.model.unit.status = \
                BlockedStatus("{} not running".format(self.service))
        self.model.unit.status = \
            ActiveStatus("{} is running".format(self.service))

    def on_zookeeper_relation_joined(self, event):
        self.zk.user = self.config.get("user", "")
        self.zk.group = self.config.get("group", "")
        self.zk.mode = 0o640
        try:
            self.zk.on_zookeeper_relation_joined(event)
        except KafkaRelationBaseNotUsedError as e:
            # Relation not been used any other application, move on
            logger.info(str(e))
        except KafkaRelationBaseTLSNotSetError as e:
            # Same reason as cluster-relation
            event.defer()
            self.model.unit.status = BlockedStatus(str(e))
        self._on_config_changed(event)

    def on_zookeeper_relation_changed(self, event):
        self.zk.user = self.config.get("user", "")
        self.zk.group = self.config.get("group", "")
        self.zk.mode = 0o640
        try:
            self.zk.on_zookeeper_relation_changed(event)
        except KafkaRelationBaseNotUsedError as e:
            # Relation not been used any other application, move on
            logger.info(str(e))
        except KafkaRelationBaseTLSNotSetError as e:
            # Same reason as cluster-relation
            event.defer()
            self.model.unit.status = BlockedStatus(str(e))
        self._on_config_changed(event)

    def get_ssl_cert(self):
        if self.config["generate-root-ca"]:
            return self.ks.ssl_cert
        return base64.b64decode(self.config["ssl_cert"]).decode("ascii")

    def get_ssl_key(self):
        if self.config["generate-root-ca"]:
            return self.ks.ssl_key
        return base64.b64decode(self.config["ssl_key"]).decode("ascii")

    def get_quorum_cert(self):
        if self.config["generate-root-ca"]:
            return self.ks.quorum_cert
        return base64.b64decode(self.config["ssl-quorum-cert"]).decode("ascii")

    def get_quorum_key(self):
        if self.config["generate-root-ca"]:
            return self.ks.quorum_key
        return base64.b64decode(self.config["ssl-quorum-key"]).decode("ascii")

    def get_ssl_keystore(self):
        path = self.config.get("keystore-path",
                               "/var/ssl/private/kafka_ssl_ks.jks")
        return path

    def get_ssl_truststore(self):
        path = self.config.get("truststore-path",
                               "/var/ssl/private/kafka_ssl_ks.jks")
        return path

    def get_quorum_keystore(self):
        path = self.config.get("quorum-keystore-path",
                               "/var/ssl/private/kafka_quorum_ks.jks")
        return path

    def get_quorum_truststore(self):
        path = self.config.get("quorum-truststore-path",
                               "/var/ssl/private,kafka_quorum_ts.jks")
        return path

    def _generate_keystores(self):
        if self.config["generate-root-ca"] and \
            (len(self.ks.quorum_cert) > 0 and
             len(self.ks.quorum_key) > 0 and
             len(self.ks.ssl_cert) > 0 and
             len(self.ks.ssl_key) > 0):
            logger.info("Certificate already auto-generated and set")
            return
        if self.config["generate-root-ca"]:
            logger.info("Certificate needs to be auto generated")
            self.ks.quorum_cert, self.ks.quorum_key = \
                generateSelfSigned(self.unit_folder,
                                   certname="quorum-zookeeper-root-ca",
                                   user=self.config["user"],
                                   group=self.config["group"],
                                   mode=0o600)
            self.ks.ssl_cert, self.ks.ssl_key = \
                generateSelfSigned(self.unit_folder,
                                   certname="ssl-zookeeper-root-ca",
                                   user=self.config["user"],
                                   group=self.config["group"],
                                   mode=0o600)
            logger.info("Certificates and keys generated")
        else:
            # Check if the certificates remain the same
            if self.ks.quorum_cert == self.get_quorum_cert() and \
                    self.ks.quorum_key == self.get_quorum_key() and \
                    self.ks.ssl_cert == self.get_ssl_cert() and \
                    self.ks.quorum_key == self.get_quorum_key():
                # Yes, they do, leave this method as there is nothing to do.
                logger.info("Certificates and keys remain the same")
                return
            # Certs already set either as configs or certificates relation
            self.ks.quorum_cert = self.get_quorum_cert()
            self.ks.quorum_key = self.get_quorum_key()
            self.ks.ssl_cert = self.get_ssl_cert()
            self.ks.ssl_key = self.get_ssl_key()
        if len(self.ks.quorum_cert) > 0 and \
           len(self.ks.quorum_key) > 0:
            self.ks.ks_zookeeper_pwd = genRandomPassword()
            filename = genRandomPassword(6)
            logger.info("Create PKCS12 cert/key for quorum")
            PKCS12CreateKeystore(
                self.get_quorum_keystore(),
                self.ks.ks_zookeeper_pwd,
                self.get_quorum_cert(),
                self.get_quorum_key(),
                user=self.config["user"],
                group=self.config["group"],
                mode=0o640,
                openssl_chain_path="/tmp/" + filename + ".chain",
                openssl_key_path="/tmp/" + filename + ".key",
                openssl_p12_path="/tmp/" + filename + ".p12",
                ks_regenerate=self.config.get(
                                  "regenerate-keystore-truststore", False))
        if len(self.ks.ssl_cert) > 0 and \
           len(self.ks.ssl_key) > 0:
            logger.info("Create PKCS12 cert/key for zookeeper relation")
            self.ks.ks_password = genRandomPassword()
            filename = genRandomPassword(6)
            PKCS12CreateKeystore(
                self.get_ssl_keystore(),
                self.ks.ks_password,
                self.get_ssl_cert(),
                self.get_ssl_key(),
                user=self.config["user"],
                group=self.config["group"],
                mode=0o640,
                openssl_chain_path="/tmp/" + filename + ".chain",
                openssl_key_path="/tmp/" + filename + ".key",
                openssl_p12_path="/tmp/" + filename + ".p12",
                ks_regenerate=self.config.get(
                                  "regenerate-keystore-truststore", False))

    def _on_install(self, event):
        super()._on_install(event)
        self.model.unit.status = MaintenanceStatus("Starting installation")
        logger.info("Starting installation")
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
        data_log_fs = \
            list(yaml.safe_load(
                     self.config.get("data-log-dir", "")).items())[0][0]
        data_log_dir = \
            list(yaml.safe_load(
                     self.config.get("data-log-dir", "")).items())[0][1]
        data_fs = \
            list(yaml.safe_load(
                     self.config.get("data-dir", "")).items())[0][0]
        data_dir = \
            list(yaml.safe_load(
                     self.config.get("data-dir", "")).items())[0][1]
        logger.info("Starting the creation of folders as specified")
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
                                      self.config.get("fs-options", None))
        self._on_config_changed(event)

    def _on_cluster_relation_joined(self, event):
        self.cluster.user = self.config.get("user", "")
        self.cluster.group = self.config.get("group", "")
        self.cluster.mode = 0o640
        try:
            self.cluster.on_cluster_relation_joined(event)
        except KafkaRelationBaseTLSNotSetError as e:
            # Config-changed hook may happen before any cluster relation
            # exists. In this case, the ssl setup logic will be skipped and
            # retried once cluster_relation hooks are called and other charms
            # already set their certificate.
            logger.info("TLS cert detected but has not been set,"
                        " defer cluster joined event")
            # Defer this event to be run later. Generally this is
            # followed by return, but in this case, we want config-changed
            # logic to be rerun with the self.cluster.relation existing.
            event.defer()
            self.model.unit.status = BlockedStatus(str(e))
        self._on_config_changed(event)

    def _on_cluster_relation_changed(self, event):
        self.cluster.user = self.config.get("user", "")
        self.cluster.group = self.config.get("group", "")
        self.cluster.mode = 0o640
        try:
            self.cluster.on_cluster_relation_changed(event)
        except KafkaRelationBaseTLSNotSetError as e:
            # Config-changed hook may happen before any cluster relation
            # exists. In this case, the ssl setup logic will be skipped and
            # retried once cluster_relation hooks are called and other charms
            # already set their certificate.
            logger.info("TLS cert detected but has not been set,"
                        " defer cluster change event")
            # Defer this event to be run later. Generally this is
            # followed by return, but in this case, we want config-changed
            # logic to be rerun with the self.cluster.relation existing.
            event.defer()
            self.model.unit.status = BlockedStatus(str(e))
        self._on_config_changed(event)

    def _check_if_ready_to_start(self):
        if not self.cluster.is_ready:
            self.model.unit.status = \
                BlockedStatus("Waiting for other cluster units")
            return False
        self.model.unit.status = \
            ActiveStatus("{} running".format(self.service))
        return True

    def _render_zk_properties(self):
        logger.info("Start to render zookeeper.properties")
        zk_props = \
            yaml.safe_load(self.config.get("zookeeper-properties", "")) or {}
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
            try:
                logger.debug("Passing on the cert to "
                             "zookeeper relation object")
                self.zk.set_mTLS_auth(
                    self.config["ssl_cert"],
                    self.config.get(
                        "truststore-path",
                        "/var/ssl/private/zookeeper.truststore.jks"),
                    self.ks.ts_password)
            except KafkaRelationBaseNotUsedError as e:
                # Relation not been used any other application, move on
                logger.info(str(e))
            except KafkaRelationBaseTLSNotSetError as e:
                self.model.unit.status = BlockedStatus(str(e))

        else:
            zk_props["ssl.clientAuth"] = "none"
            zk_props["clientPort"] = self.config.get("clientPort", 2182)

        # CLUSTER TASKS:
        # First, ensure cluster-count is set:
        logger.info("Start writing the zookeeper.properties cluster configs")
        self.cluster.min_units = self.config.get("cluster-count", 3)
        # Check if cluster is needed, and in this case, exists
        if self.config.get("cluster-count", 3) > 1 and \
           not self.cluster.relations:
            logger.debug("Cluster-count > 1 but cluster.relation "
                         "object does not exist")
            self.model.unit.status = \
                BlockedStatus("Cluster detected, waiting for {} units to"
                              " come up". format(
                                  self.config.get("cluster-count")))
            return
        if self.config.get("cluster-count", 3) > \
           len(self.cluster.all_units(self.cluster.relations)):
            all_u = len(self.cluster.all_units(self.cluster.relations))
            logger.debug("Cluster.relation obj exists but "
                         "all_units return {}".format(all_u))
            self.model.unit.status = \
                BlockedStatus("Cluster detected, waiting for {} units to"
                              " come up". format(
                                  self.config.get("cluster-count")))
            return
        # As described on:
        # https://zookeeper.apache.org/doc/r3.5.7/ \
        # zookeeperAdmin.html#Quorum+TLS
        if self.config.get("ssl_quorum", False) and \
           self.cluster.relations:
            logger.debug("ssl_quorum and cluster set, "
                         "write ssl_quorum configs")
            zk_props["serverCnxnFactory"] = \
                "org.apache.zookeeper.server.NettyServerCnxnFactory"
            self.cluster.set_ssl_keypair(
                self.get_quorum_cert(),
                self.get_quorum_truststore(),
                self.ks.ts_zookeeper_pwd,
                user=self.config["user"],
                group=self.config["group"],
                mode=0o640)
            zk_props["ssl.quorum.keyStore.location"] = \
                self.get_quorum_keystore()
            zk_props["ssl.quorum.keyStore.password"] = self.ks.ks_zookeeper_pwd
            zk_props["ssl.quorum.trustStore.location"] = \
                self.get_quorum_truststore()
            zk_props["ssl.quorum.trustStore.password"] = \
                self.ks.ts_zookeeper_pwd
            zk_props["sslQuorum"] = "true"

        if self.cluster.relations:
            logger.info("Cluster relation stablished")
            zk_dict = self.cluster.get_peers
            for k, v in zk_dict.items():
                zk_props["server.{}".format(k)] = v
        logger.info("Run options for zookeeper.properties")
        logger.debug("Options are: {}".format(",".join(zk_props)))
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
        self.model.unit.status = MaintenanceStatus("Rendering log4j...")
        logger.debug("Rendering log4j")
        render(source="zookeeper_log4j.properties.j2",
               target="/etc/kafka/zookeeper-log4j.properties",
               owner=self.config.get('user'),
               group=self.config.get("group"),
               perms=0o640,
               context={
                   "root_logger": root_logger
               })

    def _get_service_name(self):
        if self.distro == 'confluent':
            self.service = 'confluent-zookeeper'
        elif self.distro == "apache":
            self.service = "zookeeper"
        return self.service

    def _on_config_changed(self, event):
        self.model.unit.status = \
            MaintenanceStatus("generate certs and keys if needed")
        logger.debug("Running _generate_keystores()")
        self._generate_keystores()
        self.model.unit.status = \
            MaintenanceStatus("Render zookeeper.properties")
        logger.debug("Running render_zk_properties()")
        self._render_zk_properties()
        self.model.unit.status = MaintenanceStatus("Render log4j properties")
        logger.debug("Running log4j properties renderer")
        self._render_zk_log4j_properties()
        self.model.unit.status = \
            MaintenanceStatus("Render service override conf file")
        logger.debug("Render override.conf")
        self.render_service_override_file(
            target="/etc/systemd/system/"
                   "{}.service.d/override.conf".format(self.service))
        if self._check_if_ready_to_start():
            logger.info("Service ready or start, restarting it...")
            # Unmask and enable service
            service_resume(self.service)
            # Reload and restart
            service_reload(self.service)
            service_restart(self.service)
            logger.debug("finished restarting")
        if not service_running(self.service):
            logger.warning("Service not running that "
                           "should be: {}".format(self.service))
            BlockedStatus("Service not running {}".format(self.service))


if __name__ == "__main__":
    main(ZookeeperCharm)
