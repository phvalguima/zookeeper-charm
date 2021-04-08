import os
import yaml
import json
from ops.framework import Object, StoredState
from charmhelpers.core.hookenv import is_leader

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
        self.framework.observe(charm.on.cluster_relation_changed, self)
        self.framework.observe(charm.on.cluster_relation_joined, self)
        self.state.set_default(myid=-1)
        self.state.set_default(status = self.NOT_READY)
        self.state.set_default(zk_dict = "{}")

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
        return os.path.join(self._charm.config["data-dir"],"myid")

    def _set_myid(self):
        if self.state.myid > 0:
            # Already defined, return the saved value
            return
        myidpath = os.path.join(self._charm.config["data-dir"],"myid")
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

    def _find_next_available_id(self):
        idlist = []
        for u in self._relation.units:
            idlist.append(int(self._relations[u]["myid"]))
        return max(idlist) + 1

    def on_cluster_relation_changed(self, event):
        #### MYID allocation logic
        # The charm leader is the one in charge of distributing myid
        # Once -changed hook is sent to the leader unit, it checks if:
        # 1) Does the leader unit itself has a myid set?
        # 1.1) If not, it means either this is a brand new cluster or old leader is lost
        #      and if old leader is lost, then this new unit leader treats itself as common
        #      unit and search the next myid for itself.
        # 1.2) If yes, then carry on
        # 2) Does the remote unit sending -changed hook has the myid set on relation data?
        # 2.1) If not, find the next myid available and allocate to that unit via relation
        if self._get_myid <= 0:
            # First time running the -changed hook.
            if is_leader():
                # We also need to account to the fact this unit may be
                # running -changed hook for the 1st time but on an
                # existing cluster
                live_cluster = False
                for u in self._relation.units:
                    if int(self._relations[u]["myid"]) == 1:
                        live_cluster = True
                        break
                # Then, although we are the leader, we should not pick the myid=1
                # What we need to do is discover the next myid for this unit and
                # then run start managing the myid allocation
                if live_cluster:
                    self.state.myid = self._find_next_available_id()
                else:
                    self.state.myid = 1
                with open(self.myid_path,"w") as f:
                    f.write(self.state.myid)
                    f.close()
            # Not leader, and do not have myid set as of yet
            elif not self._relation.data[event.unit].get("myid", None):
                # Nothing to do until we know what is our status
                self.state.status = self.NOT_READY
                return
            # There is a myid for this unit now, we should save the endpoint data
            else:
                self._relation.data[self._unit]["endpoint"] = "{}:{}:{}".format(
                    get_hostname(
                        self.model.get_binding(self._relation_name).network.binding_address),
                    self._charm.config.get("peerPort",2888),
                    self._charm.config.get("leaderPort",3888))

        # Now that MYID logic has been resolved for the leader
        # and if we are a non-leader unit, we did not block, we can follow on with the cluster logic
        # Find all the endpoints for get_peers list
        zk_dict = {}
        for u in self._relation.units:
            if not self._relation.data[u]["endpoint"]:
                continue
            if len(self._relation.data[u]["endpoint"]) == 0 or not self._relation.data[u]["myid"]:
                continue
            zk_dict[self._relation.data[u]["myid"]] = self._relation.data[u]["endpoint"]
        self.state.zk_dict = json.dumps(zk_dict)

