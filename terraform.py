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
class TerraformSolution:

    NETWORKS_FILE = "networks.tf"
    SUBNETS_FILE = "subnets.tf"
    PROVIDER_FILE = "provider.tf"
    PORTS_FILE = "ports.tf"
    INSTANCES_FILE = "instances.tf"
    TEMPLATES_FILE = "templates.tf"
    CLOUD_INIT_FILE = "cloud-init.tf"
    VARIABLES_FILE = "variables.tf"
    SOLUTION_MANAGEMENT_FILE = "solution-management.tf"
    DEFAULT_TEMPLATE_FILE = "default.tpl"
    STATIC_ETH0_TEMPLATE_FILE = "static_eth0.tpl"
    PASS_READER_FILE = "pass-openrc.sh"

    variables = []
    networks = []
    subnets = []
    ports = []
    instances = []
    templates = []
    cloud_inits = []

    def __init__(self, provider, output_directory):
        self.provider = provider
        self.output_directory = pathlib.Path(output_directory)

    def add_variable(self, variable):
        self.variables.append(variable)

    def add_network(self, network):
        self.networks.append(network)

    def add_subnet(self, subnet):
        self.subnets.append(subnet)

    def add_port(self, port):
        self.ports.append(port)

    def add_instance(self, instance):
        self.instances.append(instance)

    def add_template(self, template):
        self.templates.append(template)

    def add_cloud_init(self, cloud_init):
        self.cloud_inits.append(cloud_init)

    def setup_solution_management(
        self,
        management_network_id,
        management_name,
        management_cidr,
        dns_servers
    ):
        self.external_network = hcl.DataOpenstackNetworkingNetworkV2.create(
            "external-network",
            "var.external_network",
            management_network_id,
        )
        self.solution_management_router = hcl.ResourceOpenstackNetworkingRouterV2.create(
            management_name,
            "external-network",
        )
        self.solution_management_network = hcl.ResourceOpenstackNetworkingNetworkV2.create(
            management_name,
            management_network_id,
        )
        self.solution_management_subnet = hcl.ResourceOpenstackNetworkingSubnetV2.create(
            management_name,
            management_network_id,
            cidr=management_cidr,
            enable_dhcp=True,
            no_gateway=False,
            dns_nameservers=dns_servers
        )
        self.solution_management_router_interface = hcl.ResourceOpenstackNetworkingRouterInterfaceV2.create(
            management_name,
            management_name,
            management_name
        )

    def lookup_subnet_by_id(self, network_id):
        for subnet in self.subnets:
            if subnet.network_id == network_id:
                return subnet
        return self.solution_management_subnet

    def get_ports_in_subnet(self, subnet_name):
        port_list = []
        for port in self.ports:
            if port.subnet_name == subnet_name:
                port_list.append(port)
        return port_list

    def write_terraform(self):
        (self.output_directory / self.PASS_READER_FILE).write_text(PASS_READER_SCRIPT)
        (self.output_directory / self.DEFAULT_TEMPLATE_FILE).write_text(DHCP_TEMPLATE)
        (self.output_directory / self.STATIC_ETH0_TEMPLATE_FILE).write_text(STATIC_ETH0_TEMPLATE)

        provider_text = TERRAFORM_CONFIG + "\n"
        provider_text += self.provider.render()
        (self.output_directory / self.PROVIDER_FILE).write_text(provider_text)

        var_text = ""
        for variable in self.variables:
            var_text += variable.render() + "\n"

        (self.output_directory / self.VARIABLES_FILE).write_text(var_text)

        solution_management_text = self.external_network.render() + "\n"
        solution_management_text += self.solution_management_router.render() + "\n"
        solution_management_text += self.solution_management_network.render() + "\n"
        solution_management_text += self.solution_management_subnet.render() + "\n"
        solution_management_text += self.solution_management_router_interface.render()
        (self.output_directory / self.SOLUTION_MANAGEMENT_FILE).write_text(solution_management_text)

        network_text = ""
        for network in self.networks:
            network_text += network.render() + "\n"

        (self.output_directory / self.NETWORKS_FILE).write_text(network_text)

        subnet_text = ""
        for subnet in self.subnets:
            subnet_text += subnet.render() + "\n"

        (self.output_directory / self.SUBNETS_FILE).write_text(subnet_text)

        template_text = ""
        for template in self.templates:
            template_text += template.render() + "\n"

        (self.output_directory / self.TEMPLATES_FILE).write_text(template_text)

        cloud_init_text = ""
        for cloud_init in self.cloud_inits:
            cloud_init_text += cloud_init.render() + "\n"

        (self.output_directory / self.CLOUD_INIT_FILE).write_text(cloud_init_text)

        port_text = ""
        for port in self.ports:
            port_text += port.render() + "\n"

        (self.output_directory / self.PORTS_FILE).write_text(port_text)

        instance_text = ""
        for instance in self.instances:
            instance_text += instance.render() + "\n"

        (self.output_directory / self.INSTANCES_FILE).write_text(instance_text)
