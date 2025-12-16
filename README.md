# Far-Edge Node Watcher

**Far-edge Node Watcher** is responsible for monitoring the installation and removal of Far-edge devices. When a new Far-edge device is connected, NextGenGW publishes the details of this device in the "announce" topic. When a Far-edge device is disconnected, NextGenGW publishes such an event in the "unregister" topic. The Far-edge Node Watcher subscribes to these topics and creates or deletes the digital representations of Far-edge devices in the Kubernetes cluster by creating or deleting the Far-edge Kubelet associated with them.

## FITA Framework

The [Far-Edge Node Watcher](https://github.com/fraunhoferportugal/far-edge-node-watcher) is one of the core components of [FITA](https://github.com/fraunhoferportugal/fita).

For full documentation, updates, and project context, please visit the main [FITA](https://github.com/fraunhoferportugal/fita) repository.
