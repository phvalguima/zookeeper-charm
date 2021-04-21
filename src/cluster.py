import os
import json
import logging
from wand.contrib.linux import get_hostname

from wand.apps.relations.kafka_relation_base import KafkaRelationBase
from wand.security.ssl import setFilePermissions

logger = logging.getLogger(__name__)


class ZookeeperCluster(KafkaRelationBase):

    # This is the status management for this relation
    # While 0, we should not set this unit into ActiveStatus
    NOT_READY = 0
    READY = 1

    def __init__(self, charm, relation_name, myidfolder, min_units=3):
        super().__init__(charm, relation_name)
        self._min_units = min_units
        self.state.set_default(myid=-1)
        self.state.set_default(status=self.NOT_READY)
        self.state.set_default(zk_dict="{}")
        self.state.set_default(myidpath=str(os.path.join(myidfolder, "myid")))

    @property
    def min_units(self):
        return self._min_units

    @min_units.setter
    def min_units(self, u):
        self._min_units = u

    @property
    def relation(self):
        return self.framework.model.get_relation(self._relation_name)

    @property
    def truststore_path(self):
        return self.state.ts_path

    @property
    def truststore_pwd(self):
        return self.state.ts_pwd

    @property
    def trusted_certs(self):
        return self.state.trusted_certs

    @property
    def is_ssl_enabled(self):
        if not self.relation:
            # Cluster relation not used yet, setting TLS is irrelevant
            return False
        if len(self.relation.data[self.unit].get("tls_cert", "")) > 0:
            return True
        return False

    def set_ssl_keypair(self,
                        ssl_cert,
                        ts_path,
                        ts_pwd,
                        user, group, mode):
        self.set_TLS_auth(ssl_cert, ts_path, ts_pwd,
                          user, group, mode)

    @property
    def _get_myid(self):
        return self.state.myid

    @property
    def hostname(self):
        return get_hostname(self.binding_addr)

    @property
    def is_ready(self):
        if self.min_units == 1:
            # Cluster does not exist. Unit working as standalone
            return True
        if len(self.all_units(self.relation)) < self.min_units:
            return False
        return True

    @property
    def get_peers(self):
        return json.loads(self.state.zk_dict)

    @property
    def myid_path(self):
        return self.state.myidpath

    def on_cluster_relation_joined(self, event):
        pass

    def _get_all_tls_certs(self):
        super()._get_all_tls_cert()

    def on_cluster_relation_changed(self, event):
        self._get_all_tls_certs()

        if self._get_myid <= 0:
            myid = int(self.unit.name.split("/")[1]) + 1
            with open(self.myid_path, "w") as f:
                f.write(str(myid))
                f.close()
            setFilePermissions(self.myid_path,
                               self.state.user,
                               self.state.group,
                               mode=0o640)
            self.state.myid = myid
            event.relation.data[self.unit]["myid"] = str(myid)

        hostname = get_hostname(self.binding_addr)
        logger.debug("Cluster Relation {}, binding address: "
                     "{} and hostname found: {}".format(
                         event.relation,
                         self.binding_addr,
                         hostname))

        peerPort = self.charm.config.get("peerPort", 2888)
        leaderPort = self.charm.config.get("leaderPort", 3888)
        event.relation.data[self.unit]["endpoint"] = \
            "{}:{}:{}".format(hostname, peerPort,
                              leaderPort)

        zk_dict = {}
        for u in self.all_units(event.relation):
            if "endpoint" not in event.relation.data[u] or \
               "myid" not in event.relation.data[u]:
                continue
            zk_dict[event.relation.data[u]["myid"]] = \
                event.relation.data[u]["endpoint"]
        self.state.zk_dict = json.dumps(zk_dict)
