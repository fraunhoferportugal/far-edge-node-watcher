from kubernetes import client,config,utils,watch
from paho.mqtt import client as mqtt_client
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
import time
import json
import sys
import os
import ssl
import argparse

import traceback

config.load_incluster_config()
k8s_client = client.ApiClient()
app_api = client.AppsV1Api(k8s_client)
core_api = client.CoreV1Api(k8s_client)

DEFAULT_CPU_CAP = "1"
DEFAULT_MEM_CAP = "256k"
DEFAULT_POD_CAP = "5"
DEFAULT_OS = "zephyr"
DEFAULT_ARCH = "arm-v7"

def create_vk(args, end_node_id, node_os, node_arch, node_cpu_cap, node_mem_cap, node_pod_cap, node_caps):
  vk_node_name = os.getenv("NODE_NAME") + '-' + end_node_id
  vk_node_name = vk_node_name.replace("_", "-")
  vk_namespace = os.getenv("NAMESPACE", "default")

  deploy_dict = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {
        "name": "far-edge-kubelet-" + vk_node_name,
        "namespace": vk_namespace,
        "labels": {
            "app": "far-edge-kubelet",
            "node": vk_node_name
        }
    },
    "spec": {
        "replicas": 1,
        "selector": {
            "matchLabels": {
                "app": "far-edge-kubelet",
                "node": vk_node_name
            }
        },
        "template": {
            "metadata": {
                "labels": {
                    "app": "far-edge-kubelet",
                    "node": vk_node_name
                }
            },
            "spec": {
                "serviceAccountName": os.getenv("SERVICE_ACCOUNT_NAME"),
                "initContainers": [
                    {
                        "name": "far-edge-kubelet-certificate-request",
                        "image": "bitnamisecure/kubectl:latest",
                        "imagePullPolicy": "IfNotPresent",
                        "command": ["/bin/bash", "-c", "/scripts/generate-cert.sh"],
                        "volumeMounts": [
                            {
                                "name": "certificate-request-script-volume",
                                "mountPath": "/scripts"
                            },
                            {
                                "name": "certificates",
                                "mountPath": "/etc/certificates"
                            }
                        ],
                        "env": [
                            {
                                "name": "NODE_NAME",
                                "value": vk_node_name
                            },
                            {
                                "name": "POD_IP",
                                "valueFrom": {
                                    "fieldRef": {"fieldPath": "status.podIP"}
                                }
                            },
                            {
                                "name": "NAMESPACE",
                                "valueFrom": {
                                    "fieldRef": {"fieldPath": "metadata.namespace"}
                                }
                            }
                        ]
                    }
                ],
                "containers": [
                    {
                        "name": "virtualkubelet",
                        "image": args.kubelet_image,
                        "imagePullPolicy": args.image_pull_policy,
                        "command": ["/far-edge-kubelet"],
                        "args": [
                            "--provider", "fhpAicos",
                            "--nodename", vk_node_name,
                            "--log-level", "info",
                            "--startup-timeout", "10s",
                            "--provider-config", "/vkubelet-mock-0-cfg.json",
                            "--klog.v", "2",
                            "--klog.logtostderr",
                            "--os", node_os
                        ],
                        "env": [
                            {"name": "NAMESPACE", "value": vk_namespace},
                            {"name": "KUBELET_PORT", "value": "10250"},
                            {"name": "APISERVER_CERT_LOCATION", "value": "/etc/certificates/cert.crt"},
                            {"name": "APISERVER_KEY_LOCATION", "value": "/etc/certificates/cert.key"},
                            {
                                "name": "VKUBELET_POD_IP",
                                "valueFrom": {"fieldRef": {"fieldPath": "status.podIP"}}
                            },
                            {"name": "PROVIDER_MODE", "value": "nextgengw"},
                            {"name": "MQTT_BROKER_URI", "value": args.mqtt_uri},
                            {"name": "MQTT_BROKER_PORT", "value": str(args.mqtt_port)},
                            {"name": "NODE_ID", "value": end_node_id},
                            {"name": "FAR_EDGE_REGISTRY", "value": args.remote_registry_url},
                            {"name": "FAR_EDGE_REGISTRY_INSECURE", "value": "true" if args.remote_registry_insecure else "false"},
                            {"name": "FAR_EDGE_REGISTRY_PLAIN_HTTP", "value": "true" if args.remote_registry_plain_http else "false"},
                            {"name": "FAR_EDGE_REGISTRY_OVERRIDE_DEFAULT", "value": "true" if args.remote_registry_override_default else "false"},
                            {"name": "FAR_EDGE_REGISTRY_OVERRIDE", "value": "true" if args.remote_registry_override else "false"},
                            {"name": "FAR_EDGE_LOCAL_REGISTRY", "value": args.local_registry_path},
                            {"name": "NODE_CPU_CAP", "value": node_cpu_cap},
                            {"name": "NODE_MEM_CAP", "value": node_mem_cap},
                            {"name": "NODE_CAPS", "value": node_caps},
                            {"name": "NODE_POD_CAP", "value": node_pod_cap},
                            {"name": "NODE_ARCH", "value": node_arch},
                            {"name": "VKUBELET_TAINT_KEY", "value": "fita.fhp.pt/type"},
                            {"name": "VKUBELET_TAINT_VALUE", "value": "far-edge"},
                            {"name": "VKUBELET_TAINT_EFFECT", "value": "NoSchedule"}
                        ],
                        "volumeMounts": [
                            {
                                "name": "certificates",
                                "mountPath": "/etc/certificates/"
                            }
                        ]
                    }
                ],
                "volumes": [
                    {"name": "certificates", "emptyDir": {}},
                    {
                        "name": "certificate-request-script-volume",
                        "configMap": {
                            "name": "far-edge-kubelet-certificate-request-script",
                            "defaultMode": 0o0555
                        }
                    }
                ],
                "nodeName": os.getenv("NODE_NAME")
            }
        }
    }
  }

  if args.remote_registry_creds_secret:
    deploy_dict["spec"]["template"]["spec"]["containers"][0]["env"].append({
        "name": "FAR_EDGE_REGISTRY_USERNAME",
        "valueFrom": {
            "secretKeyRef": {"name": args.remote_registry_creds_secret, "key": "username"}
        }
    })
    deploy_dict["spec"]["template"]["spec"]["containers"][0]["env"].append({
        "name": "FAR_EDGE_REGISTRY_PASSWORD",
        "valueFrom": {
            "secretKeyRef": {"name": args.remote_registry_creds_secret, "key": "password"}
        }
    })
  else:
    deploy_dict["spec"]["template"]["spec"]["containers"][0]["env"].append({"name": "FAR_EDGE_REGISTRY_USERNAME", "value": args.remote_registry_username})
    deploy_dict["spec"]["template"]["spec"]["containers"][0]["env"].append({"name": "FAR_EDGE_REGISTRY_PASSWORD", "value": args.remote_registry_password})

  if args.image_pull_secrets:
    deploy_dict["spec"]["template"]["spec"]["imagePullSecrets"] = [{"name": secret_name } for secret_name in args.image_pull_secrets]

  print("Will deploy this: ")
  print(deploy_dict)
  utils.create_from_dict(k8s_client, deploy_dict)

def delete_vk(end_node_id):
  vk_node_name = os.getenv("NODE_NAME") + '-' + end_node_id
  vk_node_name = vk_node_name.replace("_", "-")
  vk_namespace = os.getenv("NAMESPACE", "default")

  # Remove Virtual Kubelet pod
  try:
    resp = app_api.delete_namespaced_deployment(
      name = "far-edge-kubelet-" + vk_node_name,
      namespace = vk_namespace,
      body = {},
      grace_period_seconds = 0,
      propagation_policy = 'Foreground'
    )
    print("[INFO] Deployment far-edge-kubelet-" + vk_node_name + " deleted.")
  except Exception as e:
      print(f'Something went wrong while deleting VK: {e}')
      traceback.print_exc()
      pass

  # Remove all pods in virtual node
  # Can be in any namespace
  field_selector = 'spec.nodeName=' + vk_node_name
  ret = core_api.list_pod_for_all_namespaces(watch=False, field_selector=field_selector)
  for i in ret.items:
    try:
      resp = core_api.delete_namespaced_pod(
        name = i.metadata.name,
        namespace = i.metadata.namespace,
        body = {},
        grace_period_seconds = 0,
        propagation_policy = 'Foreground'
      )
      print("[INFO] Deleted pod " + i.metadata.name + " running in " + vk_node_name)
    except Exception as e:
        print(f'Something went wrong while pod in node: {e}')
        traceback.print_exc()
        pass

  # Delete node
  resp = core_api.delete_node(
    name = vk_node_name,
    body = {},
    grace_period_seconds = 0,
    propagation_policy = 'Foreground'
  )

  # Ensure the Kubelet is deleted. Otherwise, a new registration might fail 
  try:
    w = watch.Watch()
    for event in w.stream(func=core_api.list_namespaced_pod, namespace=vk_namespace, field_selector=f'metadata.name=far-edge-kubelet-{vk_node_name}', timeout_seconds=5):
      if event["type"] == "DELETED":
          print("[INFO] node "+ vk_node_name + " deleted.")
          w.stop()
          break
          
  except Exception as e:
      print(f'Something went wrong while waiting for kubelet deletion: {e}')
      traceback.print_exc()
      pass
  
def clean_vk():
  vk_name_prefix = 'far-edge-kubelet-' + os.getenv("NODE_NAME") + '-'
  vk_namespace = os.getenv("NAMESPACE", "default")

  api_response = core_api.list_namespaced_pod(watch=False, namespace=vk_namespace)

  for pod in api_response.items:
    if pod.metadata.name.startswith(vk_name_prefix):
      # There are leftover deployments
      node_id = pod.metadata.name.replace(vk_name_prefix, '')
      try:
        delete_vk(node_id)
      except Exception as e:
        print(f'Something went wrong while deleting VK: {e}')
        traceback.print_exc()
        pass

def clean_node(client, node_id, node_data):
  for pkg in node_data["sdfObject"]["LWM2M_Software_Management"]:
    # Delete package
    client.publish(f"{node_id}/LWM2M_Software_Management/{pkg["label"]}", payload='{"operation":"DELETE"}')

def on_connect(client, userdata, flags, rc):
  # This will be called once the client connects
  print(f"Connected with result code {rc}")
  # Subscribe here!
  client.subscribe("announce", qos=2)
  client.subscribe("unregister", qos=2)

def on_message(client, userdata, msg):
  print(f"Message received [{msg.topic}]: {msg.payload}")
  if (msg.topic == "announce"):
    node_cpu_cap = DEFAULT_CPU_CAP
    node_mem_cap = DEFAULT_MEM_CAP
    node_pod_cap = DEFAULT_POD_CAP
    node_os = DEFAULT_OS
    node_arch = DEFAULT_ARCH
    #node_extra_labels_list = dict()
    node_caps = ""

    msg_json_dict = json.loads(msg.payload.decode("utf-8"))
    end_node_id = list(msg_json_dict.keys())[0]

    if end_node_id in userdata["node_ids"]:
        print(f'Node {end_node_id} already connected, ignoring...')
        return

    print(f'Node {end_node_id} connected')

    # Clean any leftover packages
    clean_node(client, end_node_id, msg_json_dict[end_node_id])

    resource_list = list(msg_json_dict[end_node_id]["sdfObject"])
    for resource in resource_list:
      if resource == "Device":
        #TODO: Use this as the indication of memory for the node?
        try:
          node_mem_cap = msg_json_dict[end_node_id]["sdfObject"]["Device"][0]["sdfProperty"]["Memory_Total"] + 'k'
        except KeyError as e:
          print(f"Error getting key from new node. {str(e)}")
        #try:
        #  node_extra_labels_list["Battery_Level"] = msg_json_dict[end_node_id]["sdfObject"]["Device"][0]["sdfProperty"]["Battery_Level"]
        #except KeyError as e:
        #  print(f"Error getting key from new node. {str(e)}")

      if resource == "DevCapMgmt":
        try:
          dev_cap_mgmt = msg_json_dict[end_node_id]["sdfObject"]["DevCapMgmt"][0]["sdfProperty"]["Group"]
          if dev_cap_mgmt == "0":
            node_caps = msg_json_dict[end_node_id]["sdfObject"]["DevCapMgmt"][0]["sdfProperty"]["Property"]
        except KeyError as e:
          print(f"Error getting key from new node. {str(e)}")
            
      #    #TODO: I'm putting here everything as extra resources. Maybe we should discriminate between what is a capacity and a label
      #    #TODO: I'm locking the capacity to quantity 1. We should check the quantity for each capacity and create it accordingly 
      #    node_extra_labels_list[resource] = "true"
    
    try:
      create_vk(userdata['args'], end_node_id, node_os, node_arch, node_cpu_cap, node_mem_cap, node_pod_cap, node_caps)

      userdata["node_ids"].append(end_node_id)
    except Exception as e:
      print(f'Something went wrong while creating VK: {e}')
      pass

  elif (msg.topic == "unregister"):
    end_node_id = (msg.payload).decode("utf-8")

    if end_node_id in userdata["node_ids"]:
      print(f'Node {end_node_id} disconnected')

      try:
        delete_vk(end_node_id)
      except Exception as e:
        print(f'Something went wrong while deleting VK: {e}')
        traceback.print_exc()

      # Remove node from the list
      userdata["node_ids"].remove(end_node_id)

  else:
    print("Unknown topic.") 

def main():
  # Create a new argument parser
  parser = argparse.ArgumentParser()

  # add options to the parser
  parser.add_argument('--mqtt_uri', help='MQTT Broker URI', required=True)
  parser.add_argument('--mqtt_port', help='MQTT Broker Port', required=True)
  parser.add_argument('--mqtt_client_id', help='MQTT Broker Client ID', required=True)
  parser.add_argument('--mqtt_server_tls', default=False, help='Whether to use tls with broker certificate', action='store_true', required=False)
  parser.add_argument('--mqtt_mutual_tls', default=False, help='Whether to use tls with broker and client certificates', action='store_true', required=False)

  parser.add_argument('--kubelet_image', help='Image name for the Far Edge Kubelet', required=True)
  parser.add_argument('--image_pull_secret', help="Name of the registry credentials used to pull the far-edge kubelet image", default=[], action='append', dest="image_pull_secrets")
  parser.add_argument('--image_pull_policy', help='Image pull policy', default="IfNotPresent")
  parser.add_argument('--local_registry_path', help='Path to store fetched Far Edge images', required=True)

  parser.add_argument('--remote_registry_url', help='URL for the remote registry to fetch Far Edge images', required=True)
  parser.add_argument('--remote_registry_username', default="", help='Username for the remote registry', required=False)
  parser.add_argument('--remote_registry_password', default="", help='Password for the remote registry', required=False)
  parser.add_argument('--remote_registry_creds_secret', default=None, help='Name of a secret with "user" and "password" fields to be used by the far-edge-kubelet')
  parser.add_argument('--remote_registry_insecure', default=False, help='Skip TLS verification for remote registry', action='store_true', required=False)
  parser.add_argument('--remote_registry_plain_http', default=False, help='Set plain HTTP for remote registry. Skips TLS verification', action='store_true', required=False)
  parser.add_argument('--remote_registry_override_default', default=False, help='Override the default registry', action='store_true', required=False)
  parser.add_argument('--remote_registry_override', default=False, help='Override the default registry specified in the manifest', action='store_true', required=False)


  # parse the command line arguments
  args = parser.parse_args()
  if args.mqtt_server_tls or args.mqtt_mutual_tls:
      port = 8883
  else:
      port = args.mqtt_port

  print(f'mqtt_uri={args.mqtt_uri}')
  print(f'mqtt_port={port}')
  print(f'mqtt_client_id={args.mqtt_client_id}')
  print(f'mqtt_server_tls={args.mqtt_server_tls}')
  print(f'mqtt_mutual_tls={args.mqtt_mutual_tls}')
  print(f'kubelet_image={args.kubelet_image}')
  print(f'local_registry_path={args.local_registry_path}')
  print(f'remote_registry_url={args.remote_registry_url}')
  print(f'remote_registry_username={args.remote_registry_username}')
  print(f'remote_registry_password={args.remote_registry_password}')
  print(f'remote_registry_insecure={args.remote_registry_insecure}')
  print(f'remote_registry_plain_http={args.remote_registry_plain_http}')
  print(f'remote_registry_override_default={args.remote_registry_override_default}')
  print(f'remote_registry_override={args.remote_registry_override}')


  client = mqtt_client.Client(args.mqtt_client_id)
  client.on_connect = on_connect
  client.on_message = on_message
  client.user_data_set({
    'args': args,
    'node_ids': []
  })

  # Clean any leftover deployments 
  clean_vk()

  not_connected = True
  i = 0
  if args.mqtt_mutual_tls:
      print("Mutual TLS setup")
      client.tls_set(ca_certs="/etc/ssl/fita/ca.crt", keyfile="/etc/ssl/mqtt-client/tls.key", certfile="/etc/ssl/mqtt-client/tls.crt")
  elif args.mqtt_server_tls:
      print("TLS setup")
      client.tls_set(ca_certs="/etc/ssl/fita/ca.crt")

  while not_connected:
    try:
      if args.mqtt_server_tls or args.mqtt_mutual_tls:
        print("attempting tls connection")
        client.connect(args.mqtt_uri, 8883)
        not_connected = False
        print("Successfully connected with tls encryption")
      else:
        print("attempting normal connection")
        client.connect(args.mqtt_uri, int(args.mqtt_port))
        not_connected = False
        print("Successfully connected")
    
    except ConnectionRefusedError:
      print("MQTT broker not ready. Retrying in 5 seconds. Retry number " + str(i))
      i = i+1
    
    except Exception as e: # client.connect raises a different exception when uri name can't be resolved causing the node-watcher to crash
      print(f"TLS/connection error ({type(e).__name__}): {e}")
      print("MQTT broker: Name does not resolve. Incorrect broker Name or MQTT broker not ready. Retrying in 5 seconds...")
      i = i+1
    
    finally:
      if i == 10:
        print("Unable to connect. Return")
        return
      time.sleep(5)

  print("Started MQTT loop")
  client.loop_forever()  # Start networking daemon

if __name__ == "__main__":
  main()
