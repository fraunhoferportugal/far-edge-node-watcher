from kubernetes import client,config,utils,watch
from sseclient import SSEClient
import time
import json
import requests
import sys
import os
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
                        "imagePullPolicy": args.image_pull_policy,
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
                        "imagePullPolicy": "IfNotPresent",
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
  
  # May raise Exception
  utils.create_from_dict(k8s_client, deploy_dict)

def delete_vk(end_node_id):
  vk_node_name = os.getenv("NODE_NAME") + '-' + end_node_id
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
    print("[INFO] Deployment far-edge-" + vk_node_name + " deleted.")
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

def validate_node(node, leshan_ip, leshan_port):
  supports_swmgt = False
  for object_link in node["objectLinks"]:
      if "/9" in object_link["url"]:
          supports_swmgt = True
          break

  if not supports_swmgt:
    raise Exception("Node does not support Software Management Object")

  url = f'http://{leshan_ip}:{leshan_port}/api/clients/{node["endpoint"]}/3/0/17'
  response = requests.get(url)
  if response.json()['success'] and ("embServe Node" in response.json()['content']['value']):
    print("embServe Node connected!")
    return node["endpoint"]
  else:
    raise Exception("Device is not a embServe Node!")

def get_node_capabilities(node, leshan_ip, leshan_port):
  # Collect memory capacity
  mem = DEFAULT_MEM_CAP

  url = f'http://{leshan_ip}:{leshan_port}/api/clients/{node["endpoint"]}/3/0/21'
  response = requests.get(url)

  if response.json()['success']:
    mem = response.json()['content']['value'] + "k" 

  # Collect available sensors
  devcaps = []
  for object_link in node["objectLinks"]:
      # DevCap object
      if "/15" in object_link["url"]:
          # Check if a Sensor
          url = f'http://{leshan_ip}:{leshan_port}/api/clients/{node["endpoint"]}{object_link["url"]}/1'
          response = requests.get(url)
          
          if response.json()['success'] and (response.json()['content']['value'] != "0"):
            # Not a Sensor
            continue

          url = f'http://{leshan_ip}:{leshan_port}/api/clients/{node["endpoint"]}{object_link["url"]}/0'
          response = requests.get(url)
          
          if not response.json()['success']:
            # Something wrong
            continue

          # Defined in Appendix B
          # https://www.openmobilealliance.org/release/LWM2M_DevCapMgmt/V2_0_1-20240312-A/OMA-TS-LWM2M_DevCapMgmt-V2_0_1-20240312-A.pdf
          # #define LUMINOSITY_ID 0
          # #define PRESENCE_ID 1
          # #define TEMPERATURE_ID 2
          # #define HYGROMETRIE_ID 3
          # #define PRESSURE_ID 4

          # //Custom IDs
          # #define ACCELEROMETER_ID 133
          # #define GYROSCOPE_ID 134
          # #define MAGNETOMETER_ID 135
          # #define HUMIDITY_ID 136
          # #define MIC_ID 137

          for sensor in response.json()['content']['value'].split(";"):
            if sensor == "0":
              devcaps.append("light_sensor")
            elif sensor == "1":
              devcaps.append("presence_sensor")
            elif sensor == "2":
              devcaps.append("temperature_sensor")
            # elif sensor == "3":
            #   devcaps.append("hygrometrie_sensor")
            elif sensor == "4":
              devcaps.append("pressure_sensor")
            elif sensor == "133":
              devcaps.append("accelerometer")
            elif sensor == "134":
              devcaps.append("gyroscope")
            elif sensor == "135":
              devcaps.append("magnetometer")
            elif sensor == "136":
              devcaps.append("humidity_sensor")
            elif sensor == "137":
              devcaps.append("microphone")
            else:
              continue
  
  devcaps_string = ""
  for devcap in devcaps:
    devcaps_string += devcap + ";"

  return {
    "arch": DEFAULT_ARCH,
    "os": DEFAULT_OS,
    "cpu": DEFAULT_CPU_CAP,
    "mem": mem,
    "pods": DEFAULT_POD_CAP,
    "devcaps": devcaps_string[:-1]
  }

def clean_node(node, leshan_ip, leshan_port):
  # Node will now be fully managed by Kubernetes
  # Clean any leftover services
  if "9" in node["availableInstances"]:
    for instance in node["availableInstances"]["9"]:
      url = f'http://{leshan_ip}:{leshan_port}/api/clients/{node["endpoint"]}/9/{instance}'
      response = requests.delete(url)
      
      if not response.json()['success']:
        print(f'Failed to delete service 9/{instance}')

  # Clean any leftover routes
  if "35001" in node["availableInstances"]:
    for instance in node["availableInstances"]["35001"]:
      url = f'http://{leshan_ip}:{leshan_port}/api/clients/{node["endpoint"]}/35001/{instance}'
      response = requests.delete(url)
      
      if not response.json()['success']:
        print(f'Failed to delete route 35001/{instance}')

def get_nodes(leshan_ip, leshan_port):
  url = f'http://{leshan_ip}:{leshan_port}/api/clients'
  response = requests.get(url)
  return response.json()

def main():
    # Create a new argument parser
  parser = argparse.ArgumentParser()

  # add options to the parser
  parser.add_argument('--leshan_uri', help='Leshan Server URI', required=True)
  parser.add_argument('--leshan_port', help='Leshan Server Port', required=True)

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

  # leshan_ip = sys.argv[1]
  # leshan_port = sys.argv[2]
  # remote_registry = sys.argv[3]
  # local_registry = sys.argv[4]
  # leshan_service_uri = sys.argv[5]
  print(f'leshan_uri={args.leshan_uri}')
  print(f'leshan_port={args.leshan_port}')
  print(f'kubelet_image={args.kubelet_image}')
  print(f'local_registry_path={args.local_registry_path}')
  print(f'remote_registry_url={args.remote_registry_url}')
  print(f'remote_registry_username={args.remote_registry_username}')
  print(f'remote_registry_password={args.remote_registry_password}')
  print(f'remote_registry_insecure={args.remote_registry_insecure}')
  print(f'remote_registry_plain_http={args.remote_registry_plain_http}')
  print(f'remote_registry_override_default={args.remote_registry_override_default}')
  print(f'remote_registry_override={args.remote_registry_override}')

  node_ids = []

  # Clean any leftover deployments 
  clean_vk()

  # Check for any devices already registered since we might have restarted or started later than Leshan
  try:
    for node in get_nodes(args.leshan_uri, args.leshan_port):
        try:
          # Validate that this is a embServe node
          node_id = validate_node(node, args.leshan_uri, args.leshan_port)
          print(f'Node {node_id} was connected, adding virtual kubelet')

          # Get the node capabilities
          node_capabilities = get_node_capabilities(node, args.leshan_uri, args.leshan_port)
          print(f'Node capabilities: {node_capabilities}')
          
          # Clean any leftover services
          clean_node(node, args.leshan_uri, args.leshan_port)
          print(f'Node cleaned')
          
          create_vk(args, node_id, node_capabilities["os"], node_capabilities["arch"], node_capabilities["cpu"], node_capabilities["mem"], node_capabilities["pods"], node_capabilities["devcaps"])

          # Add node to the list
          node_ids.append(node_id)

        except Exception as e:
          print(f'Something went wrong while creating VK: {e}')
          traceback.print_exc()
          pass

  except Exception as e:
    print(f'Something went wrong while getting nodes: {e}')
    traceback.print_exc()
    pass

  # Wait for messages
  messages = SSEClient(f'http://{args.leshan_uri}:{args.leshan_port}/api/event')
  for msg in messages:
    if msg.event == "REGISTRATION":
      try:
        # Validate that this is a embServe node
        node_id = validate_node(json.loads(msg.data), args.leshan_uri, args.leshan_port)

        if node_id in node_ids:
          print(f'Node {node_id} already connected, ignoring...')

        else:
          print(f'Node {node_id} connected')

          # Get the node capabilities
          node_capabilities = get_node_capabilities(json.loads(msg.data), args.leshan_uri, args.leshan_port)

          # Clean any leftover services
          clean_node(json.loads(msg.data), args.leshan_uri, args.leshan_port)
          print(f'Node cleaned')

          # Deploy the VK
          create_vk(args, node_id, node_capabilities["os"], node_capabilities["arch"], node_capabilities["cpu"], node_capabilities["mem"], node_capabilities["pods"], node_capabilities["devcaps"])

          # Add node to the list
          node_ids.append(node_id)

      except Exception as e:
        print(f'Something went wrong while creating VK: {e}')
        traceback.print_exc()
        pass
    
    if msg.event == "DEREGISTRATION":
      node = json.loads(msg.data)
      node_id = node["endpoint"]

      if node_id in node_ids:
        print(f'Node {node_id} disconnected')
        
        # Remove the VK
        try:
          delete_vk(node_id)
        except Exception as e:
          print(f'Something went wrong while deleting VK: {e}')
          traceback.print_exc()

        # Remove node from the list
        node_ids.remove(node_id)

if __name__ == "__main__":
  main()