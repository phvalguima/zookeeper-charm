
ZK_PROPERTIES="""maxClientCnxns=0
initLimit=5
syncLimit=2
autopurge.snapRetainCount=10
autopurge.purgeInterval=1
admin.enableServer=False
dataDir=/var/lib/zookeeper
dataLogDir=/var/lib/kafka/zookeeper_log
ssl.clientAuth=none
clientPort=2182
server.1=ansiblezookeeper2.example.com:2888:3888
server.2=ansiblezookeeper3.example.com:2888:3888
server.3=ansiblezookeeper1.example.com:2888:3888
""" # noqa

ZK_PROPERTIES_WITH_SSL="""maxClientCnxns=0
initLimit=5
syncLimit=2
autopurge.snapRetainCount=10
autopurge.purgeInterval=1
admin.enableServer=False
dataDir=/var/lib/zookeeper
dataLogDir=/var/lib/kafka/zookeeper_log
secureClientPort=2182
serverCnxnFactory=org.apache.zookeeper.server.NettyServerCnxnFactory
authProvider.x509=org.apache.zookeeper.server.auth.X509AuthenticationProvider
sslQuorum=true
ssl.clientAuth=need
ssl.keyStore.location=/tmp/3jtieo-ks.jks
ssl.keyStore.password=confluentkeystorestorepass
ssl.trustStore.location=/tmp/3jtieo-ts.jks
ssl.trustStore.password=confluenttruststorepass
ssl.quorum.keyStore.location=/tmp/3jtieo-quorum-ks.jks
ssl.quorum.keyStore.password=confluentkeystorestorepass
ssl.quorum.trustStore.location=/tmp/3jtieo-quorum-ts.jks
ssl.quorum.trustStore.password=confluenttruststorepass
server.1=ansiblezookeeper2.example.com:2888:3888
server.2=ansiblezookeeper3.example.com:2888:3888
server.3=ansiblezookeeper1.example.com:2888:3888
""" # noqa

ZK_PROPERTIES_COMPLETE="""maxClientCnxns=0
initLimit=5
syncLimit=2
autopurge.snapRetainCount=10
autopurge.purgeInterval=1
admin.enableServer=False
authProvider.sasl=org.apache.zookeeper.server.auth.SASLAuthenticationProvider
authProvider.x509=org.apache.zookeeper.server.auth.X509AuthenticationProvider
dataDir=/var/lib/zookeeper
dataLogDir=/var/lib/kafka/zookeeper_log
kerberos.removeHostFromPrincipal=true
kerberos.removeRealmFromPrincipal=true
secureClientPort=2182
server.1=ansiblezookeeper2.example.com:2888:3888
server.2=ansiblezookeeper3.example.com:2888:3888
server.3=ansiblezookeeper1.example.com:2888:3888
serverCnxnFactory=org.apache.zookeeper.server.NettyServerCnxnFactory
ssl.clientAuth=none
ssl.keyStore.location=/var/ssl/private/zookeeper.keystore.jks
ssl.keyStore.password=confluentkeystorestorepass
ssl.quorum.keyStore.location=/var/ssl/private/zookeeper.keystore.jks
ssl.quorum.keyStore.password=confluentkeystorestorepass
ssl.quorum.trustStore.location=/var/ssl/private/zookeeper.truststore.jks
ssl.quorum.trustStore.password=confluenttruststorepass
ssl.trustStore.location=/var/ssl/private/zookeeper.truststore.jks
ssl.trustStore.password=confluenttruststorepass
sslQuorum=true""" # noqa

OVERRIDE_CONF = """[Service]
Environment=\"KAFKA_OPTS=-Djdk.tls.ephemeralDHKeySize=2048 -Djava.security.auth.login.config=/etc/kafka/zookeeper_jaas.conf\"
Environment=\"KAFKA_HEAP_OPTS=-Xmx1g\"
Environment=\"KAFKA_LOG4J_OPTS=-Dlog4j.configuration=file:/etc/kafka/zookeeper-log4j.properties\"
Environment=\"LOG_DIR=/var/log/kafka\"""" # noqa

LOG4J_PROPERTIES='''# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


log4j.rootLogger=INFO, stdout, zkAppender

log4j.appender.stdout=org.apache.log4j.ConsoleAppender
log4j.appender.stdout.layout=org.apache.log4j.PatternLayout
log4j.appender.stdout.layout.ConversionPattern=[%d] %p %m (%c)%n

log4j.appender.zkAppender=org.apache.log4j.RollingFileAppender
log4j.appender.zkAppender.File=${kafka.logs.dir}/zookeeper-server.log
log4j.appender.zkAppender.layout=org.apache.log4j.PatternLayout
log4j.appender.zkAppender.layout.ConversionPattern=[%d] %p %m (%c)%n
log4j.appender.zkAppender.Append=true
log4j.appender.zkAppender.MaxBackupIndex=10
log4j.appender.zkAppender.MaxFileSize=100MB''' # noqa

JAAS_CONF="""Server {
    com.sun.security.auth.module.Krb5LoginModule required
    useKeyTab=true
    keyTab=\"/etc/security/keytabs/zookeeper.keytab\"
    storeKey=true
    useTicketCache=false
    principal=\"HTTP/ansiblezookeeper2.example.com@FEKAFKALAB.COM\";
};""" # noqa
