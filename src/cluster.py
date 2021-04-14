import os
import json
from ops.framework import Object, StoredState
from charmhelpers.contrib.network.ip import get_hostname

from wand.security.ssl import CreateTruststore


class ZookeeperCluster(Object):

    # This is the status management for this relation
    # While 0, we should not set this unit into ActiveStatus
    NOT_READY = 0
    READY = 1
    state = StoredState()

    def __init__(self, charm, relation_name):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._unit = charm.unit
        self._relation_name = relation_name
        self.state.set_default(myid=-1)
        self.state.set_default(status=self.NOT_READY)
        self.state.set_default(zk_dict="{}")
        self.state.set_default(truststore_path="")
        self.state.set_default(truststore_pwd="")
        self.state.set_default(truststore_user="")
        self.state.set_default(truststore_group="")
        self.state.set_default(truststore_mode="")
        self.state.set_default(trusted_certs="")

    @property
    def relation(self):
        return self.framework.model.get_relation(self._relation_name)

    @property
    def unit(self):
        return self._unit

    @property
    def truststore_path(self):
        return self.state.truststore_path

    @property
    def truststore_pwd(self):
        return self.state.truststore_pwd

    @property
    def trusted_certs(self):
        return self.state.trusted_certs

    @property
    def is_ssl_enabled(self):
        if len(self.relation.data[self.unit].get("tls_cert", "")) > 0:
            return True
        return False

    def set_ssl_keypair(self,
                        ssl_cert,
                        ts_path,
                        ts_pwd,
                        user, group, mode):
        self.relation.data[self.unit]["tls_cert"] = ssl_cert
        self.state.truststore_path = ts_path
        self.state.truststore_pwd = ts_pwd
        self.state.truststore_user = user
        self.state.truststore_group = group
        self.state.truststore_mode = mode
        self._get_all_tls_certs()

    def _get_all_tls_certs(self):
        if not self.is_ssl_enabled:
            return
        self.state.trusted_certs = \
            self.relation.data[self.unit]["tls_cert"] + \
            "::" + "::".join([self.relation.data[u].get("tls_cert", "")
                              for u in self.relation.units])
        CreateTruststore(self.state.truststore_path,
                         self.state.truststore_pwd,
                         self.state.trusted_certs.split("::"),
                         ts_regenerate=True,
                         user=self.state.truststore_user,
                         group=self.state.truststore_group,
                         mode=self.state.truststore_mode)

    @property
    def _get_myid(self):
        return self.state.myid

    @property
    def is_ready(self):
        if self.state.status == self.NOT_READY:
            return False
        return True

    @property
    def get_peers(self):
        return json.loads(self.state.zk_dict)

    @property
    def myid_path(self):
        return os.path.join(self._charm.config["data-dir"], "myid")

    def _set_myid(self):
        if self.state.myid > 0:
            # Already defined, return the saved value
            return
        myidpath = os.path.join(self._charm.config["data-dir"], "myid")
        myid = None
        with open(myidpath, "r") as f:
            myid = f.read()
            f.close()
        self.state.myid = int(myid)

    @property
    def _relations(self):
        return self.framework.model.relations[self._relation_name]

    def on_cluster_relation_joined(self, event):
        pass

    def on_cluster_relation_changed(self, event):
        self._get_all_tls_certs()

        if self._get_myid <= 0:
            myid = int(self.unit.name.split("/")[1]) + 1
            with open(self.myid_path, "w") as f:
                f.write(myid)
                f.close()
            self.state.myid = myid
            self.relation.data[self.unit]["myid"] = myid

        hostname = get_hostname(
            self.model.get_binding(
                self._relation_name).network.binding_address)

        peerPort = self._charm.config.get("peerPort", 2888)
        leaderPort = self._charm.config.get("leaderPort", 3888)
        self.relation.data[self.unit]["endpoint"] = \
            "{}:{}:{}".format(hostname, peerPort,
                              leaderPort)

        zk_dict = {}
        for u in self.relation.units:
            if not self.relation.data[u]["endpoint"] or \
               not self.relation.data[u]["myid"]:
                continue
            zk_dict[self.relation.data[u]["myid"]] = \
                self.relation.data[u]["endpoint"]
        self.state.zk_dict = json.dumps(zk_dict)
