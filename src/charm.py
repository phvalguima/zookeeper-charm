#!/usr/bin/env python3
# Copyright 2021 pguimaraes
# See LICENSE file for licensing details.

import base64
import logging
import socket
import yaml
import json
import os
import shutil
import cryptography.hazmat.primitives.serialization as serialization

from ops.main import main
from ops.charm import InstallEvent
from ops.model import (
    BlockedStatus,
    ActiveStatus,
    MaintenanceStatus
)

from charms.operator_libs_linux.v1.systemd import (
    service_running,
    service_resume,
    service_restart,
    SystemdError
)

from charms.kafka_broker.v0.charmhelper import (
    open_port,
    close_port,
    render
)

import interface_tls_certificates.ca_client as ca_client

from charms.kafka_broker.v0.kafka_base_class import (
    KafkaJavaCharmBase,
    KafkaCharmBaseMissingConfigError,
    KafkaJavaCharmBaseNRPEMonitoring,
    KafkaJavaCharmBasePrometheusMonitorNode
)
from cluster import ZookeeperCluster
from charms.zookeeper.v0.zookeeper import (
    ZookeeperProvidesRelation
)
from charms.kafka_broker.v0.kafka_relation_base import (
    KafkaRelationBaseNotUsedError,
    KafkaRelationBaseTLSNotSetError
)
from ops_coordinator.ops_coordinator import (
    RestartCharmEvent,
    OpsCoordinator
)

from charms.kafka_broker.v0.kafka_security import (
    PKCS12CreateKeystore,
    genRandomPassword,
    generateSelfSigned
)

logger = logging.getLogger(__name__)


class ZookeeperCharm(KafkaJavaCharmBase):
    """Charm the service."""
    on = RestartCharmEvent()

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
        self.certificates = ca_client.CAClient(
            self,
            'certificates')
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
        self.framework.observe(self.certificates.on.ca_available,
                               self.on_certificates_relation_joined)
        self.framework.observe(self.certificates.on.tls_server_config_ready,
                               self.on_certificates_relation_changed)
        self.framework.observe(self.on.update_status,
                               self.on_update_status)
        self.framework.observe(self.on.upload_keytab_action,
                               self.on_upload_keytab_action)
        self.framework.observe(self.on.restart_event,
                               self.on_restart_event)
        self.zk = ZookeeperProvidesRelation(self, 'zookeeper',
                                            port=self.config.get('clientPort',
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
        self.ks.set_default(config_state="{}")
        self.ks.set_default(need_restart=False)
        self.ks.set_default(port=0)
        self.ks.set_default(endpoints=[])
        # LMA integrations
        self.prometheus = \
            KafkaJavaCharmBasePrometheusMonitorNode(
                self, 'prometheus-manual',
                port=self.config.get("jmx-exporter-port", 9404),
                internal_endpoint=self.config.get(
                    "jmx_exporter_use_internal", False),
                labels=self.config.get("jmx_exporter_labels", None))
        self.nrpe = KafkaJavaCharmBaseNRPEMonitoring(
            self,
            svcs=[self._get_service_name()],
            endpoints=[],
            nrpe_relation_name='nrpe-external-master')
        # Now, we need to always handle the locks
        # This method is always called, therefore should be used to
        # always manage the locks.
        self.coordinator = OpsCoordinator()
        self.coordinator.resume()

    def __del__(self):
        self.coordinator.release()

    def is_jmxexporter_enabled(self):
        if self.prometheus.relations:
            return True
        return False

    def on_update_status(self, event):
        super().on_update_status(event)

    @property
    def ctx(self):
        return json.loads(self.ks.config_state)

    @ctx.setter
    def ctx(self, c):
        self.ks.ctx = json.dumps(c)

    def on_restart_event(self, event):
        logger.debug("EVENT DEBUG: on_restart_event called")
        if not self.ks.need_restart:
            # There is a chance of several restart events being stacked.
            # This check ensures a single restart happens if several
            # restart events have been requested.
            # In this case, a restart already happened and no other restart
            # has been emitted, therefore, avoid restarting.

            # That is possible because event.restart() acquires the lock,
            # (either at that hook or on a future hook) and then, returns
            # True + release the lock at the end.
            # Only then, we set need_restart to False (no pending lock
            # requests for this unit anymore).
            # We can drop any other restart events that were stacked and
            # waiting for processing.
            logger.debug("EVENT DEBUG: restart event abandoned,"
                         " need_restart is unset")
            return
        try:
            if event.restart(self.coordinator):
                if self.check_ports_are_open(
                        endpoints=self.ks.endpoints,
                        retrials=3):
                    # Restart was successful, update need_restart and inform
                    # the clients via listener relation
                    self.model.unit.status = \
                        ActiveStatus("service running")
                    # Restart was successful, if the charm is keeping track
                    # of a context, that is the place it should be updated
                    self.ks.config_state = event.ctx
                    # Toggle need_restart as we just did it.
                    self.ks.need_restart = False
                    logger.debug("EVENT DEBUG: restart event.restart() successful")
                    # Inform the clients on listener relation:
                    # self.coordinator.run_action()
                else:
                    logger.warning("Failure at restart, operator should check")
                    self.model.unit.status = \
                        BlockedStatus("Restart Failed, check service")
            else:
                # defer the RestartEvent as it is still waiting for the
                # lock to be released.
                logger.debug("EVENT DEBUG: restart event.restart() failed, defer")
                event.defer()
        # Not using SystemdError as it is not exposed
        except Exception as e:
        # except SystemdError:
            logger.warning("Restart failed, blocking unit: {}".format(e))
            self.model.unit.status = \
                BlockedStatus("Restart Failed, check service")
            # Ignore the next restarts
            self.ks.need_restart = False

    def on_upload_keytab_action(self, event):
        try:
            self._upload_keytab_base64(
                event.params["keytab"], filename="zookeeper.keytab")
        except Exception as e:
            # Capture any exceptions and return them via action
            event.fail("Failed with: {}".format(str(e)))
            return
        self._on_config_changed(event)
        event.set_results({"keytab": "Uploaded!"})

    def on_certificates_relation_joined(self, event):
        # Relation just joined, request certs for each of the relations
        # That will happen once. The certificates will be generated, then
        # it will trigger a -changed Event on certificates, which will
        # call the config-changed logic once again.
        # That way, the certificates will be added to the truststores
        # and shared across the other relations.

        # In case several relations shares the same set of IPs (spaces),
        # the last relation will get to set the certificate values.
        # Therefore, the order of the list below is relevant.
        for r in [self.cluster, self.zk]:
            self._cert_relation_set(None, r)

        self._on_config_changed(event)

    def on_certificates_relation_changed(self, event):
        """Certificates changed

        That can mean the requested certs have been issued. Therefore,
        config_changed logic is called once again to regenerate configs
        with new cert/key AND share those across the relations as needed
        """
        self._on_config_changed(event)

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
        return self._get_ssl_cert(self.zk.binding_addr)

    def get_ssl_key(self):
        return self._get_ssl_key(self.zk.binding_addr)

    def get_quorum_cert(self):
        return self._get_ssl_cert(self.cluster.binding_addr, "ssl-quorum-cert", "ssl-quorum-key")

    def get_quorum_key(self):
        return self._get_ssl_key(self.cluster.binding_addr, "ssl-quorum-cert", "ssl-quorum-key")

    def get_ssl_keystore(self):
        path = self.config.get("keystore-path", "")
        return path

    def get_ssl_truststore(self):
        path = self.config.get("truststore-path", "")
        return path

    def get_quorum_keystore(self):
        path = self.config.get("quorum-keystore-path", "")
        return path

    def get_quorum_truststore(self):
        path = self.config.get("quorum-truststore-path", "")
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

    @property
    def snap(self):
        """ Redefining snap name from kafka to zookeeper.
        """
        return "zookeeper"

    def _on_install(self, event):
        super()._on_install(event)
        self.model.unit.status = MaintenanceStatus("Starting installation")
        logger.info("Starting installation")
        packages = []
        # TODO(pguimares): implement install_tarball logic
        if self.config.get("install_method") == "archive":
            self._install_tarball()
        elif self.distro == "confluent" or self.distro == "apache":
            if self.distro == "confluent":
                packages = self.CONFLUENT_PACKAGES
            else:
                raise Exception("Not Implemented Yet")
        elif self.distro == "apache_snap":
            self.JMX_EXPORTER_JAR_FOLDER = \
                "/snap/zookeeper/current/jar/"

        if self.distro == "apache_snap":
            os.makedirs(
                "/var/snap/zookeeper/common/logs/",
                0o755, exist_ok=True)
            shutil.chown("/var/snap/zookeeper/common/logs/",
                         user=self.config["user"],
                         group=self.config["group"])
        else:
            os.makedirs(
                "/var/log/zookeeper/",
                0o755, exist_ok=True)
            shutil.chown("/var/log/zookeeper/",
                         user=self.config["user"],
                         group=self.config["group"])

        super().install_packages(
            'openjdk-11-headless',
            packages,
            snap_connect=["proc-folder"]) # if snap is used, run connect
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
        if len(self.prometheus.relations) > 0:
            self.prometheus.on_prometheus_relation_changed(event)

    def _check_if_ready_to_start(self, ctx):
        if not self.cluster.is_ready:
            self.model.unit.status = \
                BlockedStatus("Waiting for other cluster units")
            return False
        # ctx can be a string or dict, then check and convert accordingly
        c = json.dumps(ctx) if isinstance(ctx, dict) else ctx
        if c == self.ks.config_state:
            logger.debug("Current state: {}, saved state: {}".format(
                c, self.ks.config_state
            ))
            return False
        return True

    def _render_zk_properties(self):
        """
        Render zookeeper.properties

        There are several tasks involved in rendering this file:
        1) Preparing storage folders
        2) Checking if certificate information has been passed correctly
        2.1) Share the cert information with ZK relation
        3) Setup Kerberos
        4) Cluster tasks
        4.1) Set certificate info
        """
        logger.info("Start to render zookeeper.properties")
        zk_props = \
            yaml.safe_load(self.config.get("zookeeper-properties", "")) or {}
        zk_props["dataDir"] = \
            list(yaml.safe_load(self.config["data-dir"]).items())[0][1]
        zk_props["dataLogDir"] = \
            list(yaml.safe_load(self.config["data-log-dir"]).items())[0][1]
        if len(self.get_ssl_keystore()) > 0:
            if (len(self.get_ssl_cert()) > 0 and len(self.get_ssl_key()) > 0):
                zk_props["secureClientPort"] = \
                    self.config.get("clientPort", 2182)
                zk_props["serverCnxnFactory"] = \
                    "org.apache.zookeeper.server.NettyServerCnxnFactory"
                zk_props["authProvider.x509"] = \
                    "org.apache.zookeeper.server.auth." + \
                    "X509AuthenticationProvider"
                # We change this later down the line if needed
                zk_props["sslQuorum"] = "true" \
                    if self.config.get("sslQuorum", False) else "false"
                # Used for client-server communication
                zk_props["ssl.clientAuth"] = "need" \
                    if self.config.get("sslClientAuth", False) else "none"
                if self.config["sslClientAuth"]:
                    zk_props["authProvider.x509"] = \
                        "org.apache.zookeeper.server.auth." + \
                        "X509AuthenticationProvider"
                zk_props["ssl.keyStore.location"] = \
                    self.config.get(
                        "keystore-path",
                        "/var/ssl/private/zookeeper.keystore.jks")
                zk_props["ssl.keyStore.password"] = self.ks.ks_password
                # If truststore-path is unset, then it means the charm
                # should use Java's standard truststore instead to connect to
                if len(self.config.get("truststore-path", "")) > 0:
                    zk_props["ssl.trustStore.location"] = \
                        self.config["truststore-path"]
                    zk_props["ssl.trustStore.password"] = self.ks.ts_password
                else:
                    logger.debug("Truststore not set for zookeeper relation, "
                                 "Java truststore will be used instead")
                # Now that mTLS is set, we announce it to the neighbours
                try:
                    logger.debug("Passing on the cert to "
                                 "zookeeper relation object")
                    self.zk.set_mTLS_auth(
                        self.get_ssl_cert(),
                        self.config.get(
                            "truststore-path",
                            "/var/ssl/private/zookeeper.truststore.jks"),
                        self.ks.ts_password,
                        user=self.config["user"],
                        group=self.config["group"],
                        mode=0o640)
                except KafkaRelationBaseNotUsedError as e:
                    # Relation not been used any other application, move on
                    logger.info(str(e))
                except KafkaRelationBaseTLSNotSetError as e:
                    self.model.unit.status = BlockedStatus(str(e))

        else:
            zk_props["ssl.clientAuth"] = "none"
            zk_props["clientPort"] = self.config.get("clientPort", 2182)

        # KERBEROS
        if self.is_sasl_kerberos_enabled():
            zk_props["authProvider.sasl"] = \
                "org.apache.zookeeper.server.auth.SASLAuthenticationProvider"
            zk_props["kerberos.removeHostFromPrincipal"] = "true"
            zk_props["kerberos.removeRealmFromPrincipal"] = "true"

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
        # Check if cluster has enough units deployed
        if self.config.get("cluster-count", 3) - 1 < \
           len(self.cluster.relation.units):
            all_u = len(self.cluster.relations.units) + 1
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
        if self.config.get("sslQuorum", False) and \
           self.cluster.relations:
            try:
                logger.debug("ssl_quorum and cluster set, "
                             "write ssl_quorum configs")
                self.cluster.set_ssl_keypair(
                    self.get_quorum_cert(),
                    self.get_quorum_truststore(),
                    self.ks.ts_zookeeper_pwd,
                    user=self.config["user"],
                    group=self.config["group"],
                    mode=0o640)
                zk_props["serverCnxnFactory"] = \
                    "org.apache.zookeeper.server.NettyServerCnxnFactory"
                zk_props["ssl.quorum.keyStore.location"] = \
                    self.get_quorum_keystore()
                zk_props["ssl.quorum.keyStore.password"] = \
                    self.ks.ks_zookeeper_pwd
                zk_props["ssl.quorum.trustStore.location"] = \
                    self.get_quorum_truststore()
                zk_props["ssl.quorum.trustStore.password"] = \
                    self.ks.ts_zookeeper_pwd
            except KafkaRelationBaseTLSNotSetError:
                # This can only happen if certificate relation is not ready.
                # Otherwise, all units should eventually have the certs set.
                # In this case, set_ssl_keypair is run right away and if it
                # throws an exception, then the entire SSL configs will be
                # skipped for now.
                pass

        if self.cluster.relations:
            logger.info("Cluster relation stablished")
            zk_dict = self.cluster.get_peers
            for k, v in zk_dict.items():
                zk_props["server.{}".format(k)] = v
        logger.info("Run options for zookeeper.properties")
        logger.debug("Options are: {}".format(",".join(zk_props)))
        target = self.config["filepath-zookeeper-properties"]
        render(source="zookeeper.properties.j2",
               target=target,
               owner=self.config.get('user'),
               group=self.config.get("group"),
               perms=0o640,
               context={
                   "zk_props": zk_props
               })
        return zk_props

    def _render_zk_log4j_properties(self):
        """
        Render log4j.properties file.

        This method only needs one config: log4j-root-logger, which
        defines the logging level in general.
        """

        root_logger = self.config.get("log4j-root-logger", None) or \
            "INFO, stdout, zkAppender"
        self.model.unit.status = MaintenanceStatus("Rendering log4j...")
        logger.debug("Rendering log4j")
        target = self.config["filepath-zookeeper-log4j-properties"]
        if self.distro == "apache_snap":
            zk_logger_path = "/var/snap/zookeeper/common/logs/zookeeper-server.log"
        else:
            zk_logger_path = "/var/log/zookeeper/zookeeper-server.log"

        render(source="zookeeper_log4j.properties.j2",
               target=target,
               owner=self.config.get('user'),
               group=self.config.get("group"),
               perms=0o640,
               context={
                   "root_logger": root_logger,
                   "zk_logger_path": zk_logger_path
               })
        return root_logger

    def _get_service_name(self):
        """Override parent service name"""

        if self.distro == 'confluent':
            self.service = 'confluent-zookeeper'
        elif self.distro == "apache":
            self.service = "zookeeper"
        elif self.distro == "apache_snap":
            self.service = "snap.zookeeper.zookeeper"
        return self.service

    def _on_config_changed(self, event):
        """
        Config change process
        1) Check if Kerberos is enabled and all settings are present
        1.1) Inform units of Kerberos
        2) Generate Keystores
        3) Render zookeeper.properties
        3.1) Render log4j config
        4) Render service ovverride file
        5) Restart Strategy
        6) Manage ports
        """
        logger.debug("config-changed called for event {}".format(event))
        # 1) Configure Kerberos
        try:
            if self.is_sasl_kerberos_enabled() and not self.keytab:
                self.model.unit.status = \
                    BlockedStatus("Kerberos set, waiting for keytab "
                                  "upload action")
                # We can drop this event given that an action will happen
                # or a config change
                return
        except KafkaCharmBaseMissingConfigError as e:
            # This error is raised if some but not all the configs needed for
            # Kerberos were enabled
            self.model.unit.status = \
                BlockedStatus("Kerberos config missing: {}".format(str(e)))
            return
        # Kerberos if needed correctly configured and certs are set:
        jaas_opts = super()._on_config_changed(event)
        # 1.1) Inform units of zookeeper unit that Kerberos is enabled
        if self.is_sasl_kerberos_enabled():
            self.zk.enable_sasl_kerberos()
        else:
            self.zk.disable_sasl_kerberos()

        # 2) Generate keystore files
        self.model.unit.status = \
            MaintenanceStatus("generate certs and keys if needed")
        logger.debug("Running _generate_keystores()")
        # For now, if get_ssl_keystore returns empty, then SSL will be
        # disabled across the application, including between cluster peers
        if len(self.get_ssl_keystore()) > 0:
            self._generate_keystores()
        self.model.unit.status = \
            MaintenanceStatus("Render zookeeper.properties")

        # 3) Render zookeeper.properties
        logger.debug("Running render_zk_properties()")
        zk_opts = self._render_zk_properties()
        self.model.unit.status = MaintenanceStatus("Render log4j properties")
        # 3.1) Generate log4j files
        logger.debug("Running log4j properties renderer")
        log4j_opts = self._render_zk_log4j_properties()
        self.model.unit.status = \
            MaintenanceStatus("Render service override conf file")
        logger.debug("Render override.conf")

        # 4) Render the override.conf
        jmx_file_name = \
            "/opt/prometheus/prometheus.yaml" if self.distro != "apache_snap" \
            else "/var/snap/zookeeper/common/prometheus.yaml"
        extra_envvars = None
        if self.distro == "apache_snap":
            extra_envvars = {
                "ZOO_LOG_DIR": "/var/snap/zookeeper/common/logs",
                "CLASSPATH": "/snap/zookeeper/current/zookeeper-server/*:/snap/zookeeper/current/bin/zookeeper-server/target/lib/*" # noqa
            }
        svc_opts = self.render_service_override_file(
            target="/etc/systemd/system/"
                   "{}.service.d/override.conf".format(self.service),
            jmx_file_name=jmx_file_name,
            extra_envvars=extra_envvars)

        # Generate the context
        self.model.unit.status = \
            MaintenanceStatus("Building context...")
        ctx = {
            "jaas_opts": jaas_opts,
            "zk_opts": zk_opts,
            "log4j_opts": log4j_opts,
            "svc_opts": svc_opts,
            "keytab_opts": self.keytab_b64
        }
        logger.debug("Context: {}, saved state is: {}".format(
            ctx, self.ks.config_state
        ))

        # 5) Restart Strategy
        # 5.1) Check if called via InstallEvent
        # Check if the unit has never been restarted (running InstallEvent).
        # In these cases, there is no reason to
        # request for the a restart to the cluster, instead simply restart.
        # For the "failed" case, check if service-restart-failed is set
        # if so, restart it.
        if isinstance(event, InstallEvent):
            for svc in self.services:
                service_resume(svc)
                service_restart(svc)
            self.model.unit.status = \
                ActiveStatus("Service is running")
            return

        # Now, restart service
        self.model.unit.status = \
            MaintenanceStatus("Building context...")
        logger.debug("Context: {}, saved state is: {}".format(
            ctx, self.ctx))

        if self._check_if_ready_to_start(ctx):
            self.on.restart_event.emit(ctx, services=self.services)
            self.ks.need_restart = True
            self.model.unit.status = \
                BlockedStatus("Waiting for restart event")
            return
        elif service_running(self.service):
            self.model.unit.status = \
                ActiveStatus("Service is running")
        else:
            self.model.unit.status = \
                BlockedStatus("Service not running that "
                              "should be: {}".format(self.services))

        # 6) Open ports
        if self.ks.port != self.config.get("clientPort", 3888):
            if self.ks.port > 0:
                close_port(self.ks.port)
            open_port(self.config.get("clientPort", 3888))
            self.ks.port = self.config.get("clientPort", 3888)


if __name__ == "__main__":
    main(ZookeeperCharm)
