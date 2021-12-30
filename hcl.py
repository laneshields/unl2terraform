import abc
import attr
import re

BLOCK_TYPE_RESOURCE = "resource"
BLOCK_TYPE_PROVIDER = "provider"
BLOCK_TYPE_VARIABLE = "variable"
BLOCK_TYPE_DATA = "data"

#When we match this for the value of an attribute we don't quote the whole string
NO_QUOTES_ATTR_RE = re.compile("(^file.*$|^var\..*$|^openstack_.*)")

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
                if not value:
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
    class ValueSpecs(HclMetaArgument):

        @classmethod
        def create(cls, port_security_enabled=False):
            return cls(
                name="value_specs",
                arguments={"port_security_enabled": port_security_enabled},
            )

    @classmethod
    def create(cls, name, admin_state_up=True, port_security_enabled=False):
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
        )


@attr.s
class DataOpenstackNetworkingNetworkV2(HclObject):
    @classmethod
    def create(cls, name, network_name):
        return cls(
            block_type=BLOCK_TYPE_DATA,
            block_label="openstack_networking_network_v2",
            block_name=name,
            arguments={
                "name": network_name,
            },
        )


@attr.s
class ResourceOpenstackNetworkingSubnetV2(HclObject):
    @classmethod
    def create(
        cls,
        name,
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
        )


@attr.s
class ResourceOpenstackNetworkingPortV2(HclObject):
    class FixedIP(HclAttribute):
        @classmethod
        def create(cls, subnet, address="IMPLEMENT_THIS"):
            return cls(
                type="fixed_ip",
                arguments={
                    "subnet_id": f"openstack_networking_subnet_v2.{subnet}.id",
                    "ip_address": address,
                },
            )

    @classmethod
    def create(
        cls,
        name,
        network_name,
    ):
        return cls(
            block_type=BLOCK_TYPE_RESOURCE,
            block_label="openstack_networking_port_v2",
            block_name=name,
            arguments={
                "name": name,
                "network_id": f"openstack_networking_network_v2.{network_name}.id"
            },
            attributes=[
                ResourceOpenstackNetworkingPortV2.FixedIP.create(
                    subnet=network_name,
                )
            ]
        )


@attr.s
class ResourceOpenstackComputeInstanceV2(HclObject):

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
                "user_data": user_data,
            },
            attributes=[
                ResourceOpenstackComputeInstanceV2.Network.create(
                    port_name=port_name
                ) for port_name in port_names
            ],
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
