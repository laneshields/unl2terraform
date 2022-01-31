#!/usr/bin/python3
import argparse
import hcl
import ipaddress
import pathlib
import pickle
import sys
import terraform
from lxml import etree

import pdb

DEFAULT_MANAGEMENT_CIDR = "192.168.2.0/24"
DNS_SERVERS = ["172.20.0.100", "172.20.0.101"]
DEFAULT_NETWORK_CIDR = "169.254.0.0/16"

T128_VERSION="128T-5.4.3-2.el7"

def process_args():
    parser = argparse.ArgumentParser(description="Read EVE-NG .unl file and convert to terraform")
    parser.add_argument("-u", "--unl-file", help="EVE-NG format .unl file as source")
    parser.add_argument("-s", "--solution-file", help="Saved file written by this tool")
    parser.add_argument("-o", "--output-directory", help="Directory to dump output terraform to")
    args = parser.parse_args()

    if not args.unl_file and not args.solution_file:
        parser.error("Either unl-file or solution-file option must be given")
    if args.unl_file and not args.output_directory:
        parser.error("An output directory must also be specified")

    if args.unl_file and args.solution_file:
        parser.error("Options --unl-file and --solution-file are mutually exclusive")

    return args

def main(args):
    if args.unl_file:
        validate_output_directory(pathlib.Path(args.output_directory))
        solution = load_unl(pathlib.Path(args.unl_file), pathlib.Path(args.output_directory))
    elif args.solution_file:
        output_directory = None
        if args.output_directory:
            output_directory = pathlib.Path(args.output_directory)
        solution = load_solution(pathlib.Path(args.solution_file), output_directory)
    else:
        sys.exit("ERROR: No solution defined")

    main_menu(solution)

def validate_output_directory(output_directory):
    if not output_directory.exists():
        sys.exit("ERROR: Output directory does not exist")

    if not output_directory.is_dir():
        sys.exit("ERROR: Specified output directory exists but is not a directory")

def load_unl(unl_file, output_directory):
    try:
        contents = unl_file.read_text()
    except IsADirectoryError:
        sys.exit("ERROR: Specified UNL file is a directory")

    unl_xml = etree.fromstring(str.encode(contents))

    solution = terraform.TerraformSolution(hcl.ProviderOpenstack.create(), output_directory)
    setup_variables(solution)
    handle_networks(unl_xml.xpath("/lab/topology/networks/network"), solution)
    handle_nodes(unl_xml.xpath("/lab/topology/nodes/node"), solution)
    return solution

def load_solution(solution_file, output_directory):
    solution = pickle.load(open(solution_file, 'rb'))
    if output_directory is not None:
        solution.output_directory = output_directory

    validate_output_directory(solution.output_directory)
    return solution

def main_menu(solution):
    while True:
        print("UNL read successuflly. Main menu:")
        print("n) Show networks and modify CIDR blocks")
        print("i) List instances")
        print("v) Validate networking")
        print("s) Save current solution object to a file")
        print("w) Write terraform files and exit")
        print("q) Quit without saving anything")
        choice = input("Please make a selection: ")

        if choice == "n":
            show_networks(solution)
        elif choice == "i":
            show_instances(solution)
        elif choice == "v":
            validate_networking(solution)
        elif choice == "s":
            save_solution(solution)
        elif choice == "w":
            break
        elif choice == "q":
            sys.exit(0)

    print(f"Writing terraform files to directory {solution.output_directory}!")
    solution.write_terraform()
    solution.write_ansible()

def save_solution(solution):
    while True:
        filename_input = input("Enter filename to save solution to: ")
        filename = pathlib.Path(filename_input)
        if filename.exists() and filename.is_file():
            while True:
                ow = input("File exists, overwrite? (y/n): ")
                if ow in ['n', 'N', 'no', 'No', 'NO']:
                    return None
                else:
                    break
        with filename.open('wb') as fh:
            pickle.dump(solution, fh)
        break
            
        
def show_networks(solution):
    subnet_selection = None
    while True:
        print("\n")
        print("The following networks and CIDR blocks were created")
        i = 1
        for subnet in solution.subnets:
            print(f"{i}) {subnet.subnet_name} - {subnet.cidr}")
            i += 1
        print("\n")
        print("Enter a number next to view and change network details")
        print("Enter 'x' to return to the previous menu")
        print("\n")
        choice = input("Enter a selection: ")

        try:
            index = int(choice) - 1
            subnet_selection = solution.subnets[index]
        except (ValueError, IndexError):
            if choice == "x":
                break
            else:
                print("Please enter a valid selection")
        else:
            display_network(solution, subnet_selection, index)
            subnet_selection = None

def display_network(solution, subnet, subnet_index):
    port_selection = None
    while True:
        print("\n")
        print(f"Network {subnet.subnet_name} uses CIDR {subnet.cidr}")
        print(f"Ports in {subnet.subnet_name}:")
        i = 1
        for port in subnet.ports:
            gateway = False
            if port.name == subnet.gateway_port_name:
                gateway = True
            print(f"{'*' if gateway else ' '}{i}) {port.name} - instance: {port.instance}, address: {port.address}")
            i += 1
        print("\n")
        print("Enter the number for a port to update the address")
        print("Enter 'c' to change the network address")
        print("Enter 'g' to select a gateway port for the network")
        print("Enter 'x' to return to the previous menu")
        print("\n")
        choice = input("Enter a selection: ")

        try:
            index = int(choice) - 1
            port_selection = subnet.ports[index]
        except (ValueError, IndexError):
            if choice == "c":
                updated_subnet = update_network_address(solution, subnet)
                if updated_subnet is not None:
                    solution.subnets[subnet_index] = updated_subnet
            elif choice == "g":
                updated_subnet = select_gateway(subnet, subnet.ports)
                if updated_subnet is not None:
                    solution.subnets[subnet_index] = updated_subnet
            elif choice == "x":
                break
            else:
                print("Please enter a valid selection")
        else:
            update_port_address(solution, port_selection)
            port_selection = None

def select_gateway(subnet, subnet_ports):
    while True:
        choice = input("Please enter the number of the port that should be used as the gateway for the subnet: ")
        try:
            index = int(choice) - 1
            gateway_port_name = subnet_ports[index].name
        except (ValueError, IndexError):
            if choice == "x":
                break
            else:
                print("Please enter a valid selection")
        else:
            subnet.gateway_port_name = gateway_port_name
            return subnet

def update_network_address(solution, subnet):
    while True:
        new_cidr = input("Please enter a new CIDR for the network: ")
        try:
            network = ipaddress.ip_network(new_cidr, strict=False)
        except Exception:
            if new_cidr == 'x':
                break
            print("Please enter a valid address")
        else:
            subnet.update_cidr(str(network))
            if subnet.subnet_name == solution.management_network_name:
                subnet.available_hosts = subnet.available_hosts[4:]
            return subnet

def update_port_address(solution, port):
    while True:
        new_address = input(f"Please enter a new address for port {port.name}: ")
        try:
            new_ip = ipaddress.ip_address(new_address)
        except Exception:
            if new_address == 'x':
                break
            print("Please enter a valid address")
        else:
            subnet = solution.get_subnet_by_name(port.subnet_name)
            if new_ip in ipaddress.ip_network(subnet.cidr):
                port.update_address(new_address)
                return port
            else:
                print(f"Address {new_address} is not in network {subnet.cidr}, please enter a valid address")

def show_instances(solution):
    while True:
        print("\n")
        print("The solution consists of the following instances: ")
        i = 1
        for instance in solution.instances:
            floater = instance.floating_ip
            print(f"{'*' if floater else ' '}{i}) {instance.name}")
            i += 1
        print("\n")
        print("Enter the number for an instance to see and change interface information")
        print("Enter 'f' to toggle creation of a floating IP for an instance")
        print("Enter 'x' to return to the previous menu")
        print("\n")
        choice = input("Enter a selection: ")
        try:
            index = int(choice) - 1
            selected_instance = solution.instances[index]
        except (ValueError, IndexError):
            if choice == "x":
                break
            elif choice == "f":
                set_floating_ip(solution)
            else:
                print("Please enter a valid selection")
        else:
            display_instance(solution, selected_instance)

def set_floating_ip(solution):
    while True:
        choice = input("Please enter the number of the instance that should have a floating IP: ")
        try:
            index = int(choice) - 1
            instance = solution.instances[index]
        except (ValueError, IndexError):
            if choice == "x":
                break
        else:
            instance_port0, _ = solution.get_port_by_name(instance.port_names[0])
            if instance_port0.subnet_name == solution.management_network_name:
                instance.floating_ip=True
                solution.instances[index] = instance
            else:
                print(f"Floating IP requires an instance's eth0 to be in network {solution.management_network_name}")
            break

def display_instance(solution, instance):
    while True:
        print("\n")
        print(f"Displaying ports for instance {instance.name}:")
        i = 1
        instance_port_names = instance.port_names
        for port_index, port_name in enumerate(instance_port_names):
            port, _ = solution.get_port_by_name(port_name)
            print(f"{i}) {port.name} - instance: {port.instance}, address: {port.address}")
            i += 1
        print("\n")
        print("Select the number for a port to change the address")
        print("Enter 'x' to return to the previous menu")
        print("\n")
        choice = input("Enter a selection: ")
        try:
            index = int(choice) - 1
            selected_port_name = instance_port_names[index]
        except (ValueError, IndexError):
            if choice == "x":
                break
            else:
                print("Please enter a valid selection")
        else:
            port, index = solution.get_port_by_name(selected_port_name)
            subnet = solution.get_subnet_by_name(port.subnet_name)
            updated_port = update_port_address(solution, port)
            subnet.update_port(index, updated_port)

def validate_networking(solution):
    for subnet in solution.subnets:
        network_obj = ipaddress.ip_network(subnet.cidr)
        subnet_addresses = []
        for index, port in enumerate(subnet.ports):
            if not ipaddress.ip_address(port.address) in network_obj:
                print(f"Port {port.name} address {port.address} is not in subnet {subnet.subnet_name}, please enter a new address")
                updated_port = update_port_address(solution, port)
                subnet.update_port(index, updated_port)
 
            if port.address not in subnet_addresses:
                subnet_addresses.append(port.address)
            else:
                print(f"Subnet {subnet.subnet_name} has multiple ports using address {port.address} please fix before writing solution")

    for instance in solution.instances:
        port0, _ = solution.get_port_by_name(instance.port_names[0])
        subnet = solution.get_subnet_by_name(port0.subnet_name)
        if subnet.subnet_name != solution.management_network_name and subnet.gateway_port_name is None:
            print(f"Subnet {subnet.subnet_name} needs a gateway selected due to cloud-init for instance {instance.name}")
        
def setup_variables(solution):
    solution.variables.append(hcl.HclVariable.create("openstack_user"))
    solution.variables.append(hcl.HclVariable.create("openstack_domain_name", default="128T"))
    solution.variables.append(hcl.HclVariable.create(
        "openstack_project_name",
        default="solutionTest"
    ))
    solution.variables.append(hcl.HclVariable.create("external_network", default="public"))
    solution.variables.append(hcl.HclVariable.create("image", default="se-centos7-e1000"))
    solution.variables.append(hcl.HclVariable.create("t128_image", default=T128_VERSION))
    solution.variables.append(hcl.HclVariable.create(
        "traffic_generator_image",
        default="centos_td20190517-163222"
    ))
    solution.variables.append(hcl.HclVariable.create(
        "openstack_auth_url",
        default="https://spaceport.lab.128technology.com:5000/v3"
    ))
    solution.variables.append(hcl.HclVariable.create("openstack_region", default="RegionOne"))
    solution.variables.append(hcl.HclVariable.create("vm_flavor", default="dev_medium"))


def setup_solution_management(solution, management_network_name, management_network_id):
    mn = ipaddress.ip_network(DEFAULT_MANAGEMENT_CIDR, strict=False)

    solution.setup_solution_management(
        management_network_id,
        management_network_name,
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
            nw = ipaddress.ip_network(DEFAULT_NETWORK_CIDR, strict=False)
            solution.networks.append(hcl.ResourceOpenstackNetworkingNetworkV2.create(
                name=network_name,
                network_id=network_id,
            ))
            solution.subnets.append(hcl.ResourceOpenstackNetworkingSubnetV2.create(
                name=network_name,
                network_id=network_id,
                cidr=str(nw),
            ))


def handle_nodes(nodes, solution):

    for node in nodes:
        default_template = False
        node_name = node.get("name")
        node_template = node.get("template")
        ifnames = []
        interfaces = node.xpath("interface")
        nw0 = None
        for interface in interfaces:
            if_id = interface.get("id")
            network_id = interface.get("network_id")
            port_name = f"{node_name}_{if_id}"
            subnet = solution.get_subnet_by_id(network_id)
            first_address = str(subnet.available_addresses()[0])
            if if_id == "0":
                nw0 = subnet
            available_addresses = str(subnet.available_addresses())

            port = hcl.ResourceOpenstackNetworkingPortV2.create(
              name=port_name,
              subnet_name=subnet.subnet_name,
              address=first_address,
              instance=node_name,
            )
            subnet.ports.append(port)
            ifnames.append(port_name)
        if nw0.subnet_name == solution.management_network_name:
            default_template = True

        solution.instances.append(hcl.ResourceOpenstackComputeInstanceV2.create(
            node_name,
            ifnames,
            image_name="var.t128_image" if node_template == "128T" else "var.image",
            user_data=terraform.TerraformSolution.DEFAULT_TEMPLATE_NAME if default_template else node_name
        ))


if __name__ == "__main__":
    args = process_args()
    main(args)
