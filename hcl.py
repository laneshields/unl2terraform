import abc
import attr
import ipaddress
import re

BLOCK_TYPE_DATA = "data"
BLOCK_TYPE_OUTPUT = "output"
BLOCK_TYPE_PROVIDER = "provider"
BLOCK_TYPE_RESOURCE = "resource"
BLOCK_TYPE_VARIABLE = "variable"

#When we match this for the value of an attribute we don't quote the whole string
NO_QUOTES_ATTR_RE = re.compile("(^file.*$|^var\..*$|^openstack_.*$|^data\..*$|^element\(.*$)")

def _list_to_string(ll):
    text = ""
    for item in ll[:-1]:
        text += f"\"{item}\", "
    text += f"\"{ll[-1]}\""
    return text
        
@attr.s
class HclMetaArgument(abc.ABC):
    name = attr.ib()
    arguments = attr.ib(factory=dict)
    def render(self):
        text = f"    {self.name} = " + "{\n"
        for argument, value in self.arguments.items():
            if isinstance(value, bool):
                value = str(value).lower()
            if NO_QUOTES_ATTR_RE.match(value):
                text += f"        {argument} = {value}" + "\n"
            else:
                text += f"        {argument} = \"{value}\"" + "\n"
        text += "    }\n"
        return text


@attr.s
class HclAttribute(abc.ABC):
    type = attr.ib()
    arguments = attr.ib(factory=dict)
    def render(self):
        text = f"    {self.type} " + "{\n"
        for argument, value in self.arguments.items():
            if not value:
                continue
            if isinstance(value, bool):
                value = str(value).lower()
            if NO_QUOTES_ATTR_RE.match(value):
                text += f"        {argument} = {value}\n"
            else:
                text += f"        {argument} = \"{value}\"" + "\n"
        text += "    }\n"
        return text


@attr.s
class HclObject(abc.ABC):
    block_type = attr.ib()
    block_label = attr.ib()
    block_name = attr.ib()
    arguments = attr.ib(factory=dict)
    meta_arguments = attr.ib(factory=list)
    attributes = attr.ib(factory=list)
    def render(self):
        if self.block_label:
            text = f'{self.block_type} "{self.block_label}" "{self.block_name}"' + " {\n"
        else:
            text = f'{self.block_type} "{self.block_name}"' + " {\n"
        if self.arguments is not None:
            for argument, value in self.arguments.items():
                if value is None:
                    continue
                if isinstance(value, bool):
                    value = str(value).lower()
                if isinstance(value, list):
                    text += f"    {argument} = [{_list_to_string(value)}]" + "\n"
                else:
                    if NO_QUOTES_ATTR_RE.match(value):
                        text += f"    {argument} = {value}" + "\n"
                    else:
                        text += f"    {argument} = \"{value}\"" + "\n"
        if self.meta_arguments is not None:
            for meta_argument in self.meta_arguments:
                text += "\n"
                text += meta_argument.render()
        if self.attributes is not None:
            for attribute in self.attributes:
                text += "\n"
                text += attribute.render()
        text += "}\n"
        return text


@attr.s
class HclVariable(HclObject):
    @classmethod
    def create(cls, name, default=""):
        return cls(
            block_type=BLOCK_TYPE_VARIABLE,
            block_label=None,
            block_name=name,
            arguments={
                "default": default,
            }
    )

@attr.s
class HclOutputFloatingip(HclObject):
    @classmethod
    def create(cls, name, flip_name):
        return cls(
            block_type=BLOCK_TYPE_OUTPUT,
            block_label=None,
            block_name=name,
            arguments={
                "value": f"${{openstack_networking_floatingip_v2.{flip_name}.address}}",
            }
        )

@attr.s
class ProviderOpenstack(HclObject):
    @classmethod
    def create(cls):
        return cls(
            block_type=BLOCK_TYPE_PROVIDER,
            block_label=None,
            block_name="openstack",
            arguments={
                "auth_url": "var.openstack_auth_url",
                "domain_name": "var.openstack_domain_name",
                "region": "var.openstack_region",
                "tenant_name": "var.openstack_project_name",
                "user_name": "var.openstack_user",
            }
        )


@attr.s
class ResourceOpenstackNetworkingRouterV2(HclObject):
    @classmethod
    def create(cls, name, external_network_name):
        return cls(
            block_type=BLOCK_TYPE_RESOURCE,
            block_label="openstack_networking_router_v2",
            block_name=name,
            arguments={
                "name": name,
                "external_network_id": f"data.openstack_networking_network_v2.{external_network_name}.id"
            },
        )


@attr.s
class ResourceOpenstackNetworkingRouterInterfaceV2(HclObject):
    @classmethod
    def create(cls, name, router_name, subnet_name):
        return cls(
            block_type=BLOCK_TYPE_RESOURCE,
            block_label="openstack_networking_router_interface_v2",
            block_name=name,
            arguments={
                "router_id": f"openstack_networking_router_v2.{router_name}.id",
                "subnet_id": f"openstack_networking_subnet_v2.{subnet_name}.id",
            }
        )


@attr.s
class ResourceOpenstackNetworkingNetworkV2(HclObject):
    network_id = attr.ib(default=None)
    class ValueSpecs(HclMetaArgument):

        @classmethod
        def create(cls, port_security_enabled=False):
            return cls(
                name="value_specs",
                arguments={"port_security_enabled": port_security_enabled},
            )

    @classmethod
    def create(cls, name, network_id, admin_state_up=True, port_security_enabled=False):
        return cls(
            block_type=BLOCK_TYPE_RESOURCE,
            block_label="openstack_networking_network_v2",
            block_name=name,
            arguments={
                "name": name,
                "admin_state_up": admin_state_up,
            },
            meta_arguments=[ResourceOpenstackNetworkingNetworkV2.ValueSpecs.create(
                port_security_enabled=port_security_enabled
            )],
            network_id=network_id,
        )


@attr.s
class DataOpenstackNetworkingNetworkV2(HclObject):
    network_name = attr.ib(default=None)
    network_id = attr.ib(default=None)
    @classmethod
    def create(cls, name, network_name, network_id):
        return cls(
            block_type=BLOCK_TYPE_DATA,
            block_label="openstack_networking_network_v2",
            block_name=name,
            arguments={
                "name": network_name,
            },
            network_name=network_name,
            network_id=network_id,
        )


@attr.s
class ResourceOpenstackNetworkingSubnetV2(HclObject):
    subnet_name = attr.ib(default=None)
    network_id = attr.ib(default=None)
    cidr = attr.ib(default=None)
    ports = attr.ib(default=[])
    gateway_port_name = attr.ib(default=None)
    enable_dhcp = attr.ib(default=False)

    @classmethod
    def create(
        cls,
        name,
        network_id,
        cidr="169.254.0.0/16",
        ip_version="4",
        enable_dhcp=False,
        no_gateway=True,
        dns_nameservers=None,
    ):
        return cls(
            block_type=BLOCK_TYPE_RESOURCE,
            block_label="openstack_networking_subnet_v2",
            block_name=name,
            arguments={
                "name": name,
                "network_id": f"openstack_networking_network_v2.{name}.id",
                "cidr": cidr,
                "ip_version": ip_version,
                "enable_dhcp": enable_dhcp,
                "no_gateway": no_gateway,
                "dns_nameservers": dns_nameservers,
            },
            subnet_name=name,
            network_id=network_id,
            cidr=cidr,
            enable_dhcp=enable_dhcp,
            # Without this all ports get added to all networks
            ports=[],
        )

    def update_cidr(self, new_cidr):
        self.cidr = new_cidr
        self.arguments['cidr'] = new_cidr

    def update_port(self, index, port):
        self.ports[index] = port

    def available_addresses(self):
        all_hosts = list(ipaddress.ip_network(self.cidr))
        # Remove network and broadcast address
        all_hosts = all_hosts[1:-1]
        if self.enable_dhcp:
            all_hosts = all_hosts[4:]

        for port in self.ports:
            port_address = ipaddress.ip_address(port.address)
            if port_address in all_hosts:
              all_hosts.remove(port_address)

        return all_hosts

@attr.s
class ResourceOpenstackNetworkingPortV2(HclObject):
    name = attr.ib(default=None)
    subnet_name = attr.ib(default=None)
    address = attr.ib(default=None)
    instance = attr.ib(default=None)
    class FixedIP(HclAttribute):
        @classmethod
        def create(cls, subnet, address):
            return cls(
                type="fixed_ip",
                arguments={
                    "subnet_id": f"openstack_networking_subnet_v2.{subnet}.id",
                    "ip_address": address,
                },
            )

        def update_address(self, new_address):
            self.arguments["ip_address"] = new_address

    @classmethod
    def create(
        cls,
        name,
        subnet_name,
        address,
        instance,
    ):
        return cls(
            block_type=BLOCK_TYPE_RESOURCE,
            block_label="openstack_networking_port_v2",
            block_name=name,
            arguments={
                "name": name,
                "network_id": f"openstack_networking_network_v2.{subnet_name}.id"
            },
            attributes=[
                ResourceOpenstackNetworkingPortV2.FixedIP.create(
                    subnet=subnet_name,
                    address=address,
                )
            ],
            name=name,
            subnet_name=subnet_name,
            address=address,
            instance=instance,
        )

    def update_address(self, new_address):
        self.address = new_address
        self.attributes[0].update_address(new_address)

@attr.s
class ResourceOpenstackComputeInstanceV2(HclObject):
    name = attr.ib(default=None)
    port_names = attr.ib(default=None)
    floating_ip = attr.ib(default=False)
    class Network(HclAttribute):
        @classmethod
        def create(cls, port_name):
            return cls(
                type="network",
                arguments={"port": f"openstack_networking_port_v2.{port_name}.id"},
            )

    @classmethod
    def create(
        cls,
        name,
        port_names,
        image_name="var.image",
        flavor_name="var.vm_flavor",
        user_data="default",
    ):
        return cls(
            block_type=BLOCK_TYPE_RESOURCE,
            block_label="openstack_compute_instance_v2",
            block_name=name,
            arguments={
                "name": name,
                "image_name": image_name,
                "flavor_name": flavor_name,
                "config_drive": True,
                "user_data": f"data.template_cloudinit_config.{user_data}.rendered",
            },
            attributes=[
                ResourceOpenstackComputeInstanceV2.Network.create(
                    port_name=port_name
                ) for port_name in port_names
            ],
            name=name,
            port_names=port_names,
        )


@attr.s
class DataTemplateFile(HclObject):
    class Vars(HclMetaArgument):
        @classmethod
        def create(cls, arguments):
            return cls(
                name="vars",
                arguments=arguments,
            )

    @classmethod
    def create(cls, name, template_file, vars=None):
        return cls(
            block_type=BLOCK_TYPE_DATA,
            block_label="template_file",
            block_name=name,
            arguments={
                "template": f"file(\"${{path.module}}/{template_file}\")",
            },
            attributes=[
                DataTemplateFile.Vars.create(vars)
            ] if vars else None,
        )

    def set_gateway_port(self, port_name):
        self.attributes[0].arguments["gateway-ip"] = f"openstack_networking_port_v2.{port_name}.all_fixed_ips[0]"

@attr.s
class DataTemplateCloudinitConfig(HclObject):
    class Part(HclAttribute):
        @classmethod
        def create(cls, template_name):
            return cls(
                type="part",
                arguments={
                    "content_type": "text/cloud-config",
                    "content": f"data.template_file.{template_name}.rendered",
                }
            )

    @classmethod
    def create(cls, name, template_name):
        return cls(
            block_type=BLOCK_TYPE_DATA,
            block_label="template_cloudinit_config",
            block_name=name,
            arguments={
                "gzip": False,
                "base64_encode": False,
            },
            attributes=[
                DataTemplateCloudinitConfig.Part.create(
                    template_name
                )
            ],
        )

@attr.s
class ResourceOpenstackNetworkingFloatingipV2(HclObject):
    @classmethod
    def create(cls, name):
        return cls(
            block_type=BLOCK_TYPE_RESOURCE,
            block_label="openstack_networking_floatingip_v2",
            block_name=name,
            arguments={
                "pool": "var.external_network",
            },
        )

@attr.s
class ResourceOpenstackComputeFloatingipAssociateV2(HclObject):
    @classmethod
    def create(cls, name, flip_name, instance_name):
        return cls(
            block_type=BLOCK_TYPE_RESOURCE,
            block_label="openstack_compute_floatingip_associate_v2",
            block_name=name,
            arguments={
                "floating_ip": f"openstack_networking_floatingip_v2.{flip_name}.address",
                "instance_id": f"openstack_compute_instance_v2.{instance_name}.id",
                "fixed_ip": f"openstack_compute_instance_v2.{instance_name}.network.0.fixed_ip_v4",
            }
        )
