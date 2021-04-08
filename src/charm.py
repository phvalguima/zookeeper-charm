#!/usr/bin/env python3
# Copyright 2021 pguimaraes
# See LICENSE file for licensing details.

import logging

from ops.charm import CharmBase
from ops.main import main
from ops.framework import StoredState


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
        self.zk = ZookeeperProvidesRelation(self, 'zookeeper', self.config.get('clientPort', 2182))


    def _on_install(self, _):
        packages = []
            self._install_tarball()
        if self.distro == "confluent":
            packages = self.CONFLUENT_PACKAGES
        else:
            raise Exception("Not Implemented Yet")
        super().install_packages('openjdk-11-headless', packages)
        self._on_config_changed()

    def _on_config_changed(self, _):
        pass


if __name__ == "__main__":
    main(ZookeeperCharm)
