import attr
import hcl
import pathlib

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

PASS_READER_SCRIPT = """#!/usr/bin/env bash

# To use an OpenStack cloud you need to authenticate against the Identity
# service named keystone, which returns a **Token** and **Service Catalog**.
# The catalog contains the endpoints for all services the user/tenant has
# access to - such as Compute, Image Service, Identity, Object Storage, Block
# Storage, and Networking (code-named nova, glance, keystone, swift,
# cinder, and neutron).
#
# For more information on Openstack configuration, see:
# https://docs.openstack.org/python-openstackclient/latest/configuration/index.html
#
# Instead of explicitly setting Openstack environment variables with this
# script, most Openstack preferences are set in overridable terraform
# variables. Source this file to enter your Openstack password, which will
# be stored in an environment variable, which is somewhat better than
# storing it in a file
#
# To download your project's full openrc.sh file to set these variables
# - go to: Project >> Compute >> Access & Security
# - select the "API Access" tab
# - choose "Download OpenStack RC File v3"
# - source the downloaded file

# With Keystone you pass the keystone password.
echo "Please enter your OpenStack Password where Project and User names are set as terraform variables: "
read -sr OS_PASSWORD_INPUT
export OS_PASSWORD=$OS_PASSWORD_INPUT
"""

ANSIBLE_CFG = """# config file for Ansible provisioning

[defaults]
# Point to the inventory directory containing the hosts
inventory = ./inventory

# log output
log_path = ./ansible.log

# The common roles directory will be adjacent to solutions/
roles_path = ../../../roles/

# By default, do everything as root
remote_user = root

# Override ssh options
host_key_checking = False

timeout=60
"""

TERRAFORM_PY_START = '''#!/usr/bin/env python3.6
###############################################################################
# Copyright (c) 2018 128 Technology, Inc.
# All rights reserved.
###############################################################################
"""
Dynamic ansible inventory that discovers the necessary Terraform output data.
Assumes the file is run from the network_setup/ directory.
"""

import argparse
import os.path
import sys

#temporary until t128_solutions_tools is a package
sys.path.insert(0, os.path.join(os.path.abspath(os.path.dirname(__file__)), '../../../../utils/lib'))
import t128_solutions_tools


def main():
    args = parse_args()
    dynamic_terraform = TerraformInventory()
    if args.list:
        result = dynamic_terraform.get_inventory_list()
        print(result)


def parse_args():
    parser = argparse.ArgumentParser(description='Dynamic host inventory')
    parser.add_argument('--list', action='store_true', default=False)
    return parser.parse_args()


class TerraformInventory:
    TERRAFORM_FILE = '../terraform_setup/terraform.tfstate'

    def __init__(self):
        TBM_FILE = 'files/testbed.json'
        TERRAFORM_FILE = '../terraform_setup/terraform.tfstate'
        if os.path.exists(TBM_FILE):
            self._dut_names = ['bard-jumper', 'traffic-generator']
        else:
'''

TERRAFORM_PY_MIDDLE1='''        self._output = t128_solutions_tools.get_output(TBM_FILE, TERRAFORM_FILE)

    def get_inventory_list(self):
        json_template = t128_solutions_tools.create_template(
            """
            {{
'''
TERRAFORM_PY_MIDDLE2='''                "_meta": {{
                    "hostvars": {{
'''

TERRAFORM_PY_MIDDLE3='''                    }}
                }}
            }}
            """)

        return json_template(
'''
TERRAFORM_PY_END='''

if __name__ == '__main__':
    main()
'''

NETWORK_SETUP_YML = """---
- name: SSH known host cleanup
  hosts: jumper, traffic-generator
  tags: connectivity
  gather_facts: no
  serial: 1
  tasks:
    - name: Remove previous known host
      local_action: known_hosts state=absent name={{ ansible_host }}

- name: SSH known host cleanup
  hosts: all
  tags: publicly-routable
  gather_facts: no
  serial: 1
  tasks:
    - name: Remove previous known host
      local_action: known_hosts state=absent name={{ ansible_host }} path=~/.ssh/ansible_known_hosts

- name: Jumper provisioning
  hosts: jumper
  gather_facts: no
  roles:
    - centos-bootstrap
    - jumper
    - firewall
    - allow-egress-traffic

- name: FRR provisioning
  hosts: frr
  gather_facts: no
  roles:
    - frr-router
    - gateway

- name: bootstrap everything else
  hosts: publicly-routable
  gather_facts: no
  roles:
    - centos-bootstrap

- name: Finish jumper
  hosts: jumper
  gather_facts: no
  roles:
    - network-namespaces
    - namespace-dhcp-server

- name: Traffic Generator
  hosts: traffic-generator
  gather_facts: no
  roles:
    - centos-bootstrap
    - network-namespaces
"""

DEPLOY_128T_YML = """---
- name: Install 128T software
  hosts: 128T-nodes
  gather_facts: no
  roles:
    - 128T-engineering-certified
    - 128T-manually-provisioned
    - 128T-manually-installed

- name: Add Configuration
  hosts: 128T-conductors
  gather_facts: no
  roles:
    - 128T-manually-configured
"""

@attr.s
class TerraformSolution:

    DEFAULT_TEMPLATE_NAME = "default"
    TERRAFORM_DIRECTORY = "terraform_setup"
    ANSIBLE_DIRECTORY = "network_setup"
    NETWORKS_FILE = "networks.tf"
    SUBNETS_FILE = "subnets.tf"
    PROVIDER_FILE = "provider.tf"
    PORTS_FILE = "ports.tf"
    INSTANCES_FILE = "instances.tf"
    TEMPLATES_FILE = "templates.tf"
    CLOUD_INIT_FILE = "cloud-init.tf"
    VARIABLES_FILE = "variables.tf"
    SOLUTION_MANAGEMENT_FILE = "solution-management.tf"
    FLOATING_IPS_FILE = "floating-ips.tf"
    OUTPUTS_FILE = "outputs.tf"
    DEFAULT_TEMPLATE_FILE = "default.tpl"
    STATIC_ETH0_TEMPLATE_FILE = "static_eth0.tpl"
    PASS_READER_FILE = "pass-openrc.sh"

    provider = attr.ib()
    output_directory = attr.ib()
    variables = attr.ib(default=[])
    networks = attr.ib(default=[])
    subnets = attr.ib(default=[])
    ports = attr.ib(default=[])
    instances = attr.ib(default=[])
    templates = attr.ib(default=[])
    cloud_inits = attr.ib(default=[])

    def setup_solution_management(
        self,
        management_network_id,
        management_name,
        management_cidr,
        dns_servers
    ):
        self.management_network_name = management_name
        self.external_network = hcl.DataOpenstackNetworkingNetworkV2.create(
            "external-network",
            "var.external_network",
            management_network_id,
        )

        self.solution_management_router = hcl.ResourceOpenstackNetworkingRouterV2.create(
            management_name,
            "external-network",
        )

        self.networks.append(hcl.ResourceOpenstackNetworkingNetworkV2.create(
            management_name,
            management_network_id,
        ))

        management_subnet = hcl.ResourceOpenstackNetworkingSubnetV2.create(
            management_name,
            management_network_id,
            cidr=management_cidr,
            enable_dhcp=True,
            no_gateway=False,
            dns_nameservers=dns_servers
        )
        # The first four addresses of this network are allocated to OpenStack
        management_subnet.available_hosts = management_subnet.available_hosts[4:]
        self.subnets.append(management_subnet)

        self.solution_management_router_interface = hcl.ResourceOpenstackNetworkingRouterInterfaceV2.create(
            management_name,
            management_name,
            management_name
        )

    def get_subnet_by_id(self, network_id):
        for subnet in self.subnets:
            if subnet.network_id == network_id:
                return subnet
        return self.solution_management_subnet

    def get_subnet_by_name(self, subnet_name):
        for subnet in self.subnets:
            if subnet.subnet_name == subnet_name:
                return subnet
        return self.solution_management_subnet

    def get_ports_in_subnet(self, subnet_name):
        port_list = []
        for port in self.ports:
            if port.subnet_name == subnet_name:
                port_list.append(port)
        return port_list

    def get_port_by_name(self, port_name):
        for port in self.ports:
            if port.name == port_name:
                return port

    def write_terraform(self):
        terraform_directory = pathlib.Path(self.output_directory) / self.TERRAFORM_DIRECTORY
        terraform_directory.mkdir(exist_ok=True)
        (terraform_directory / self.PASS_READER_FILE).write_text(PASS_READER_SCRIPT)
        (terraform_directory / self.DEFAULT_TEMPLATE_FILE).write_text(DHCP_TEMPLATE)
        (terraform_directory / self.STATIC_ETH0_TEMPLATE_FILE).write_text(STATIC_ETH0_TEMPLATE)

        provider_text = TERRAFORM_CONFIG + "\n"
        provider_text += self.provider.render()
        (terraform_directory / self.PROVIDER_FILE).write_text(provider_text)

        var_text = ""
        for variable in self.variables:
            var_text += variable.render() + "\n"

        (terraform_directory / self.VARIABLES_FILE).write_text(var_text)

        solution_management_text = self.external_network.render() + "\n"
        solution_management_text += self.solution_management_router.render() + "\n"
        solution_management_text += self.solution_management_router_interface.render()
        (terraform_directory / self.SOLUTION_MANAGEMENT_FILE).write_text(solution_management_text)

        network_text = ""
        for network in self.networks:
            network_text += network.render() + "\n"

        (terraform_directory / self.NETWORKS_FILE).write_text(network_text)

        subnet_text = ""
        for subnet in self.subnets:
            subnet_text += subnet.render() + "\n"

        (terraform_directory / self.SUBNETS_FILE).write_text(subnet_text)

        port_text = ""
        for port in self.ports:
            port_text += port.render() + "\n"

        (terraform_directory / self.PORTS_FILE).write_text(port_text)

        template_text = hcl.DataTemplateFile.create(
            self.DEFAULT_TEMPLATE_NAME,
            self.DEFAULT_TEMPLATE_FILE,
        ).render() + "\n"

        cloud_init_text = hcl.DataTemplateCloudinitConfig.create(
            self.DEFAULT_TEMPLATE_NAME,
            self.DEFAULT_TEMPLATE_NAME,
        ).render() + "\n"

        instance_text = ""
        floating_ips_text = ""
        outputs_text = ""

        nw0 = None
        for instance in self.instances:
            port0 = self.get_port_by_name(instance.port_names[0])
            if port0.subnet_name != self.management_network_name:
                gateway_port = self.get_subnet_by_name(port0.subnet_name).gateway_port_name
                template_text += hcl.DataTemplateFile.create(
                    instance.name,
                    self.STATIC_ETH0_TEMPLATE_FILE,
                    vars={
                        "ip-address": f"openstack_networking_port_v2.{instance.name}_0.all_fixed_ips[0]",
                        "prefix-length": f'element(split("/",openstack_networking_subnet_v2.{port0.subnet_name}.cidr),1)',
                        "gateway-ip": f"openstack_networking_port_v2.{gateway_port}.all_fixed_ips[0]",
                        "nameserver": "172.20.0.100",
                    }
                ).render() + "\n"

                cloud_init_text += hcl.DataTemplateCloudinitConfig.create(
                    instance.name,
                    instance.name,
                ).render() + "\n"
                 
            instance_text += instance.render() + "\n"
            if instance.floating_ip:
                floating_ips_text += hcl.ResourceOpenstackNetworkingFloatingipV2.create(instance.name).render() + "\n"
                floating_ips_text += hcl.ResourceOpenstackComputeFloatingipAssociateV2.create(
                    instance.name,
                    instance.name,
                    instance.name,
                ).render() + "\n"

                outputs_text += hcl.HclOutputFloatingip.create(
                    instance.name,
                    instance.name,
                ).render() + "\n"

        (terraform_directory / self.TEMPLATES_FILE).write_text(template_text)
        (terraform_directory / self.CLOUD_INIT_FILE).write_text(cloud_init_text)
        (terraform_directory / self.INSTANCES_FILE).write_text(instance_text)
        (terraform_directory / self.FLOATING_IPS_FILE).write_text(floating_ips_text)
        (terraform_directory / self.OUTPUTS_FILE).write_text(outputs_text)

    def write_ansible(self):
        ansible_directory = pathlib.Path(self.output_directory) / self.ANSIBLE_DIRECTORY
        ansible_directory.mkdir(exist_ok=True)
        (ansible_directory / "ansible.cfg").write_text(ANSIBLE_CFG)

        (ansible_directory / "network-setup.yml").write_text(NETWORK_SETUP_YML)
        (ansible_directory / "deploy-128t.yml").write_text(DEPLOY_128T_YML)

        (ansible_directory / "files").mkdir(exist_ok=True)
        inventory_directory = ansible_directory / "inventory"
        inventory_directory.mkdir(exist_ok=True)
        group_vars_directory = inventory_directory / "group_vars"
        group_vars_directory.mkdir(exist_ok=True)
        host_vars_directory = inventory_directory / "host_vars"
        host_vars_directory.mkdir(exist_ok=True)

        (group_vars_directory / "all.yml").write_text(
            "ansible_ssh_pass: exit33\n" + \
            "global_nameserver: 172.20.0.100\n"
        )

        (group_vars_directory / "publicly-routable.yml").write_text(
            "ansible_ssh_common_args: \"-o UserKnownHostsFile=~/dev/null -o ProxyJump=\\\"root@{{ hostvars['jumper']['ansible_host'] }}\\\"\"\n"
        )

        (group_vars_directory / "128T-routers.yml").write_text(
            "t128_node_role: combo\n" + \
            "\n" + \
            "t128_router_name: 128t-router\n"
            "t128_node_name: 128t-node\n"
            "\n" + \
            "t128_conductor_ips:\n"
            "- IMPLEMENT_THIS\n"
        )

        (group_vars_directory / "128T-nodes.yml").write_text(
            "ansible_ssh_user: t128\n" + \
            "ansible_become: yes\n" + \
            "ansible_become_password: exit33\n" + \
            "t128_management_ip: '127.0.0.1'\n" + \
            "t128_needs_reboot: true\n" + \
            "preloaded_image: 1\n"
        )

        (group_vars_directory / "128T-conductors.yml").write_text(
            "t128_node_role: conductor\n" + \
            "t128_import_config_file: conductor\n" + \
            "t128_router_name: conductor\n"
        )

        hosts_text = ""
        floating_ips = []
        for instance in self.instances:
            if instance.floating_ip:
                floating_ips.append(f"{instance.name}")
            host_vars_text = ""
            i = 0
            for interface in instance.port_names:
                port = self.get_port_by_name(interface)
                if i==0:
                    if not instance.floating_ip:
                        host_vars_text += f"ansible_host: {port.address}\n\n"
                    host_vars_text = "interfaces:\n"
                subnet = self.get_subnet_by_name(port.subnet_name)
                if not subnet.subnet_name == self.management_network_name:
                    host_vars_text += f"- ifname: eth{i} #{port.subnet_name}\n"
                    host_vars_text += f"  inet4: {port.address}\n"
                    host_vars_text += f"  prefix: {subnet.cidr.split('/')[1]}\n"
                    if subnet.gateway_port_name is not None:
                        gateway_port = self.get_port_by_name(subnet.gateway_port_name)
                        host_vars_text += f"  gateway: {gateway_port.address}\n"
                i += 1
            (host_vars_directory / f"{instance.name}.yml").write_text(host_vars_text)

            hosts_text += f"{instance.name}\n"

        hosts_text += "\n[128T-conductors]\n\n[128T-routers]\n\n[128T-nodes:children]\n128T-routers\n128T-conductors\n\n[publicly-routable:children]\n128T-nodes\n"
        (inventory_directory / "hosts").write_text(hosts_text)

        if floating_ips:
            terraform_py_text = TERRAFORM_PY_START
            terraform_py_text += f"            self._dut_names = {floating_ips}\n"
            terraform_py_text += TERRAFORM_PY_MIDDLE1
            terraform_py_text += f'                "__terraform_dependent": {floating_ips},\n'
            terraform_py_text += TERRAFORM_PY_MIDDLE2
            for instance in floating_ips[:-1]:
                terraform_py_text += f'                        "{instance}" : {{{{\n'
                terraform_py_text += f'                            "ansible_host" : {{{instance.replace("-", "_")}}}\n'
                terraform_py_text += "                        }},\n"
            terraform_py_text += f'                        "{floating_ips[-1]}" : {{{{\n'
            terraform_py_text += f'                            "ansible_host" : {{{floating_ips[-1].replace("-", "_")}}}\n'
            terraform_py_text += "                        }}\n"
            terraform_py_text += TERRAFORM_PY_MIDDLE3

            for index, instance in enumerate(floating_ips[:1]):
                terraform_py_text += f"            {instance.replace('-', '_')}=self._output[self._dut_names[{index}]],\n"

            terraform_py_text += f"            {floating_ips[-1].replace('-', '_')}=self._output[self._dut_names[{len(floating_ips) - 1}]])\n"

            terraform_py_text += TERRAFORM_PY_END

            terraform_py_file = inventory_directory / "terraform.py"
            terraform_py_file.write_text(terraform_py_text)
            terraform_py_file.chmod(33277)
