#!/usr/bin/python3
import argparse
import attr
import hcl
import ipaddress
import pathlib
import sys
import terraform
from lxml import etree

MANAGEMENT_NAME = "solution-management"
MANAGEMENT_CIDR = "192.168.2.0/24"
DNS_SERVERS = ["172.20.0.100", "172.20.0.101"]

DEFAULT_TEMPLATE_NAME = "default"
T128_VERAION="128T-5.4.3-2.el7"

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

    solution = terraform.TerraformSolution(hcl.ProviderOpenstack.create(), output_directory)
    setup_variables(solution)
    handle_networks(unl_xml.xpath("/lab/topology/networks/network"), solution)
    handle_nodes(unl_xml.xpath("/lab/topology/nodes/node"), solution)
    solution.write_terraform()

def setup_variables(solution):
    solution.add_variable(hcl.HclVariable.create("openstack_user"))
    solution.add_variable(hcl.HclVariable.create("openstack_domain_name", default="128T"))
    solution.add_variable(hcl.HclVariable.create(
        "openstack_project_name",
        default="solutionTest"
    ))
    solution.add_variable(hcl.HclVariable.create("external_network", default="public"))
    solution.add_variable(hcl.HclVariable.create("image", default="se-centos7-e1000"))
    solution.add_variable(hcl.HclVariable.create("t128_image", default=T128_VERSION))
    solution.add_variable(hcl.HclVariable.create(
        "traffic_generator_image",
        default="centos_td20190517-163222"
    ))
    solution.add_variable(hcl.HclVariable.create(
        "openstack_auth_url",
        default="https://spaceport.lab.128technology.com:5000/v3"
    ))
    solution.add_variable(hcl.HclVariable.create("openstack_region", default="RegionOne"))
    solution.add_variable(hcl.HclVariable.create("vm_flavor", default="dev_medium"))


def setup_solution_management(solution, management_network_name, management_network_id):
    while True:
        print(f"Found a network named {management_network_name} which appears to map to a solution management network in Terraform.")
        management_cidr = input(f"What subnet should be used for the solution management network? (192.168.2.0/24) ") or "192.168.2.0/24"
        try:
            mn = ipaddress.ip_network(management_cidr, strict=False)
        except Exception:
            print("Please enter a valid network address")
            continue
        else:
            break

    solution.setup_solution_management(
        management_network_id,
        MANAGEMENT_NAME,
        str(mn),
        DNS_SERVERS,
    )

def handle_networks(networks, solution):
    for network in networks:
        network_name = network.get("name")
        network_id = network.get("id")
        network_type = network.get("type")
        # We will map the pnet0 type to the soution-management construct in our standard terraform setup
        if network_type == "pnet0":
            setup_solution_management(solution, network_name, network_id)
        else:
            while True:
               nw_addr = input(f"Found a network named {network_name}, what subnet should be associated with this? (169.254.0.0/16) ") or "169.254.0.0/16"
               try:
                   nw = ipaddress.ip_network(nw_addr, strict=False)
               except Exception:
                   print("Please enter a valid network address")
                   continue
               else:
                   break
            solution.add_network(hcl.ResourceOpenstackNetworkingNetworkV2.create(
                name=network_name,
                network_id=network_id,
            ))
            solution.add_subnet(hcl.ResourceOpenstackNetworkingSubnetV2.create(
                name=network_name,
                network_id=network_id,
                cidr=str(nw),
            ))


def handle_nodes(nodes, solution):

    solution.add_template(hcl.DataTemplateFile.create(
        DEFAULT_TEMPLATE_NAME,
        terraform.TerraformSolution.DEFAULT_TEMPLATE_FILE,
    ))

    solution.add_cloud_init(hcl.DataTemplateCloudinitConfig.create(
        DEFAULT_TEMPLATE_NAME,
        DEFAULT_TEMPLATE_NAME,
    ))

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
            port_name = f"{node_name}_{if_id}"
            network = solution.lookup_subnet_by_id(network_id)
            if if_id == "0":
                nw0 = network
            first_address = str(network.available_hosts[0])
            while True:
               address = input(f"Interface {port_name} is in network {network.subnet_name} ({network.cidr}), what address should be allocated to it? ({first_address}) ") or str(first_address)
               try:
                   ipaddress.ip_address(address)
               except ValueError:
                   print("Please enter a valid IP address")
                   continue
               else:
                   addr = ipaddress.ip_address(address)
                   if addr in network.available_hosts:
                       network.available_hosts.remove(addr)
                       break
                   else:
                       print(f"Address {str(address)} in subnet {network.subnet_name} is already allocated")
            solution.add_port(hcl.ResourceOpenstackNetworkingPortV2.create(
              name=port_name,
              subnet_name=network.subnet_name,
              address=address,
              instance=node_name,
            ))
            ifnames.append(port_name)
        if nw0.subnet_name == MANAGEMENT_NAME:
            default_template = True
        else:
            if nw0.gateway is None:
                print(f"Network {nw0.subnet_name} does not have a gateway specified. Ports in network:\n")
                port_list = solution.get_ports_in_subnet(nw0.subnet_name)
                i = 1
                for port in port_list:
                    print(f"{i}) {port.name}: {port.address}\n")
                while True:
                    selection = input(f"Please select a port to use as the gateway in cloud-init templates (1{len(port_list) - 1}): ")
                    try:
                        gateway = port_list[selection - 1]
                    except Exception:
                        print("Please enter a valid selection\n")
                    else:
                        break
            solution.add_template(hcl.DataTemplateFile.create(
                node_name,
                terraform.TerraformSolution.STATIC_ETH0_TEMPLATE_FILE,
                vars={
                    "ip-address": f"openstack_networking_port_v2.{node_name}_0.all_fixed_ips[0]",
                    "prefix-length": f"element(split("/",openstack_networking_subnet_v2.{nw0.cidr}.cidr),1)",
                    "gateway-ip": f"openstack_networking_port_v2.{gateway.address}.all_fixed_ips[0]",
                    "nameserver": "172.20.0.100",
                }
            ))

            solution.add_cloud_init(hcl.DataTemplateCloudinitConfig.create(
                node_name,
                node_name,
            ))

        solution.add_instance(hcl.ResourceOpenstackComputeInstanceV2.create(
            node_name,
            ifnames,
            image_name="var.t128_image" if node_template == "128T" else "var.image",
            user_data=DEFAULT_TEMPLATE_NAME if default_template else node_name
        ))


if __name__ == "__main__":
    args = process_args()
    main(
        unl_filename=args.unl_file,
        output_directory=pathlib.Path(args.output_directory)
    )
