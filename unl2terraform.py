#!/usr/bin/python3
import argparse
import attr
import hcl
import pathlib
import sys
from lxml import etree

import pdb

TERRAFORM_OPENSTACK_PLUGIN_VERSION = "1.46.0"
TERRAFORM_CONFIG = f"""terraform {{
    required_providers {{
        openstack = {{
            source = "terraform-provider-openstack/openstack"
            version = "{TERRAFORM_OPENSTACK_PLUGIN_VERSION}"
        }}
    }}
}}
"""

VARIABLES_OVERRIDE_HEADER = """#------------------------
# Generally override
#------------------------

"""

VARIABLES_REMAIN_HEADER = """#------------------------
# Generally remain
#------------------------

"""

DHCP_TEMPLATE = """groups:
- t128
users:
- default
- name: t128
  primary-group: t128
  groups: wheel
  lock_passwd: False
  plain_text_passwd: exit33
chpasswd:
  list: |
    root:exit33
  expire: False
disable_root: False
ssh_pwauth: True
"""

STATIC_ETH0_TEMPLATE = """groups:
- t128
users:
- default
- name: t128
  primary-group: t128
  groups: wheel
  lock_passwd: False
  plain_text_passwd: exit33
- name: ha_user
  sudo: ALL=(ALL) ALL
  lock_passwd: False
  plain_text_passwd: exit33
chpasswd:
  list: |
    root:exit33
  expire: False
disable_root: False
ssh_pwauth: True

write_files:
- path: /etc/sysconfig/network-scripts/ifcfg-eth0
  content: |
    DEVICE="eth0"
    USERCTL="no"
    TYPE="Ethernet"
    BOOTPROTO="none"
    ONBOOT="yes"
    IPADDR="${ip-address}"
    PREFIX="${prefix-length}"
    GATEWAY="${gateway-ip}"
    DNS1="${nameserver}"
    
runcmd:
- systemctl restart network
# Don't use DNS for sshd because the public ip lookups will time out
- sed -i 's/^#UseDNS yes$/UseDNS no/' /etc/ssh/sshd_config
- systemctl restart sshd
"""

MANAGEMENT_NAME = "solution-management"
MANAGEMENT_CIDR = "192.168.2.0/24"

DEFAULT_TEMPLATE_NAME = "default"
DEFAULT_TEMPLATE_FILE = "default.tpl"
STATIC_ETH0_TEMPLATE_FILE = "static_eth0.tpl"

NETWORKS_FILE = "networks.tf"
SUBNETS_FILE = "subnets.tf"
PROVIDER_FILE = "provider.tf"
PORTS_FILE = "ports.tf"
INSTANCES_FILE = "instances.tf"
TEMPLATES_FILE = "templates.tf"
CLOUD_INIT_FILE = "cloud-init.tf"
VARIABLES_FILE = "variables.tf"
SOLUTION_MANAGEMENT_FILE = "solution-management.tf"

def process_args():
    parser = argparse.ArgumentParser(description="Read EVE-NG .unl file and convert to terraform")
    parser.add_argument("--unl-file", help="EVE-NG format .unl file as source", required=True)
    parser.add_argument("--output-directory", help="Directory to dump output terraform to", required=True)
    return parser.parse_args()

def main(unl_filename=None, output_directory=None):
    if not output_directory.exists():
        sys.exit("Output directory does not exist")

    if not output_directory.is_dir():
        sys.exit("Specified output directory exists but is not a directory")

    with open(unl_filename) as fh:
        contents = fh.read()

    unl_xml = etree.fromstring(str.encode(contents))

    setup_variables(output_directory)
    setup_provider(output_directory)
    setup_solution_management(output_directory)
    write_template_files(output_directory)
    network_map = handle_networks(unl_xml.xpath("/lab/topology/networks/network"), output_directory)
    handle_nodes(unl_xml.xpath("/lab/topology/nodes/node"), network_map, output_directory)

def setup_variables(output_directory):
    variable_file = output_directory / VARIABLES_FILE
    variables = VARIABLES_OVERRIDE_HEADER
    variables += hcl.HclVariable.create("openstack_user").render() + "\n"
    variables += hcl.HclVariable.create("openstack_domain_name", default="128T").render() + "\n"
    variables += hcl.HclVariable.create("openstack_project_name", default="solutionTest").render() + "\n"
    variables += hcl.HclVariable.create("external_network", default="public").render() + "\n"
    variables += VARIABLES_REMAIN_HEADER
    variables += hcl.HclVariable.create("image", default="se-centos7-e1000").render() + "\n"
    variables += hcl.HclVariable.create("t128_image", default="IMPLEMENT_THIS").render() + "\n"
    variables += hcl.HclVariable.create("traffic_generator_image", default="centos_td20190517-163222").render() + "\n"
    variables += hcl.HclVariable.create("openstack_auth_url", default="https://spaceport.lab.128technology.com:5000/v3").render() + "\n"
    variables += hcl.HclVariable.create("openstack_region", default="RegionOne").render() + "\n"
    variables += hcl.HclVariable.create("vm_flavor", default="dev_medium").render()

    variable_file.write_text(variables)

def setup_provider(output_directory):
    provider_file = output_directory / PROVIDER_FILE
    text = TERRAFORM_CONFIG + "\n"
    text += hcl.ProviderOpenstack.create().render()
    provider_file.write_text(text)

def setup_solution_management(output_directory):
    solution_management_file = output_directory / SOLUTION_MANAGEMENT_FILE
    text = ""
    text += hcl.DataOpenstackNetworkingNetworkV2.create("external-network", "var.external_network").render() + "\n"
    text += hcl.ResourceOpenstackNetworkingRouterV2.create(MANAGEMENT_NAME, "external-network").render() + "\n"
    text += hcl.ResourceOpenstackNetworkingNetworkV2.create(MANAGEMENT_NAME).render() + "\n"
    text += hcl.ResourceOpenstackNetworkingSubnetV2.create(
        MANAGEMENT_NAME,
        cidr=MANAGEMENT_CIDR,
        enable_dhcp=True,
        no_gateway=False,
        dns_nameservers=["172.20.0.100", "172.20.0.101"]
    ).render()
    text += hcl.ResourceOpenstackNetworkingRouterInterfaceV2.create(
        MANAGEMENT_NAME,
        MANAGEMENT_NAME,
        MANAGEMENT_NAME
    ).render()

    solution_management_file.write_text(text)

def write_template_files(output_directory):
    default_file = output_directory / DEFAULT_TEMPLATE_FILE
    default_file.write_text(DHCP_TEMPLATE)

    static_file = output_directory / STATIC_ETH0_TEMPLATE_FILE
    static_file.write_text(STATIC_ETH0_TEMPLATE)

def handle_networks(networks, output_directory):
    nws = ""
    sns = ""
    network_map = {}
    for network in networks:
        network_name = network.get("name")
        network_id = network.get("id")
        network_type = network.get("type")
        # We will map the pnet0 type to the soution-management construct in our standard terraform setup
        # The solution managemen network is constructed by default so we just need to map the id
        if network_type == "pnet0":
            network_name = MANAGEMENT_NAME
        else:
            nws += hcl.ResourceOpenstackNetworkingNetworkV2.create(network_name).render() + "\n"
            sns += hcl.ResourceOpenstackNetworkingSubnetV2.create(network_name).render() + "\n"

        network_map[network_id] = network_name
    (output_directory / NETWORKS_FILE).write_text(nws)
    (output_directory / SUBNETS_FILE).write_text(sns)

    return network_map

def handle_nodes(nodes, network_map, output_directory):
    ports = ""
    instances = ""

    templates = hcl.DataTemplateFile.create(
        DEFAULT_TEMPLATE_NAME,
        DEFAULT_TEMPLATE_FILE,
    ).render() + "\n"

    cloud_init = hcl.DataTemplateCloudinitConfig.create(
        DEFAULT_TEMPLATE_NAME,
        DEFAULT_TEMPLATE_NAME,
    ).render() + "\n"

    default_template = False
    for node in nodes:
        node_name = node.get("name")
        node_template = node.get("template")
        ifnames = []
        interfaces = node.xpath("interface")
        nw0 = None
        for interface in interfaces:
            if_id = interface.get("id")
            network_id = interface.get("network_id")
            if if_id == "0":
                nw0 = network_map[network_id]
            port_name = f"{node_name}_{if_id}"
            ports += hcl.ResourceOpenstackNetworkingPortV2.create(
              port_name,
              network_map[network_id]
            ).render() + "\n"
            ifnames.append(port_name)
        if nw0 == MANAGEMENT_NAME:
            default_template = True
        else:
            templates += hcl.DataTemplateFile.create(
                node_name,
                STATIC_ETH0_TEMPLATE_FILE,
                vars={
                    "ip-address": "IMPLEMENT_THIS",
                    "prefix-length": "IMPLEMENT_THIS",
                    "gateway-ip": "IMPLEMENT_THIS",
                    "nameserver": "IMPLEMENT_THIS",
                }
            ).render() + "\n"

            cloud_init += hcl.DataTemplateCloudinitConfig.create(
                node_name,
                node_name,
            ).render() + "\n"

        instances += hcl.ResourceOpenstackComputeInstanceV2.create(
            node_name,
            ifnames,
            image_name="var.t128_image" if node_template == "128T" else "var.image",
            user_data=DEFAULT_TEMPLATE_NAME if default_template else node_name
        ).render() + "\n"


    (output_directory / PORTS_FILE).write_text(ports)
    (output_directory / INSTANCES_FILE).write_text(instances)
    (output_directory / TEMPLATES_FILE).write_text(templates)
    (output_directory / CLOUD_INIT_FILE).write_text(cloud_init)

if __name__ == "__main__":
    #pdb.set_trace()
    args = process_args()
    main(
        unl_filename=args.unl_file,
        output_directory=pathlib.Path(args.output_directory)
    )
