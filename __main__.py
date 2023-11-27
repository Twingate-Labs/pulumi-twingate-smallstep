import pulumi
import pulumi_aws as aws
import pulumi_twingate as tg
import pulumi_random as random
import os
from pathlib import Path
import pydevd_pycharm
import copy
#if __name__ == "__main__":  # noqa: C901
#    pydevd_pycharm.settrace('localhost', port=58165, stdoutToServer=True, stderrToServer=True)


init_aws_ca_template = Path("./scripts/init_aws_ca.sh").read_text()
init_aws_ssh_host_template = Path("./scripts/init_aws_ssh_host.sh").read_text()
init_connector_template = Path("./scripts/init_connector.sh").read_text()

# stack_name = f"{pulumi.get_organization()}/{pulumi.get_project()}/{pulumi.get_stack()}"
# stack_ref = pulumi.StackReference(stack_name)

config = pulumi.Config()
data = config.require_object("data")

ca_root_key_password = random.RandomPassword("ca_root_key_password", length=32, special=True).result

pulumi.export('ca_root_key_password', pulumi.Output.secret(ca_root_key_password))

ca_config = config.require_object("ca_config")
ca_domain = f"{ca_config.get('ca_hostname')}.{data.get('domain')}"
init_aws_ca_script = ca_root_key_password.apply(
    lambda v: init_aws_ca_template.format(**ca_config,
                                          ca_root_key_password=v,
                                          ca_dns_name=ca_domain))

twingate_config = pulumi.Config("twingate")

# Set to True to enable SSH to the connector EC2 instance
ssh_enabled = True

try:
    tg_account = twingate_config.get("network")
    if tg_account is None:
        tg_account = os.getenv('TWINGATE_NETWORK')
except:
    tg_account = os.getenv('TWINGATE_NETWORK')

# Create a VPC
vpc = aws.ec2.Vpc(
    data.get("vpc_name"),
    cidr_block=data.get("vpc_cidr"),
    enable_dns_hostnames=True,
    tags={
        "Name": data.get("vpc_name"),
    }
)

dns_zone = aws.route53.Zone("tgdemo_zone",
                            name=f"{data.get('domain')}.",
                            force_destroy=True,
                            vpcs=[aws.route53.ZoneVpcArgs(
                                vpc_id=vpc.id,
                            )])

# Create a Private Subnet
private_subnet = aws.ec2.Subnet(data.get("prv_subnet_name"),
                                vpc_id=vpc.id,
                                cidr_block=data.get("prv_cidr"),
                                map_public_ip_on_launch=False,
                                tags={
                                    "Name": data.get("prv_subnet_name"),
                                })

# Create a Public Subnet
public_subnet = aws.ec2.Subnet(data.get("pub_subnet_name"),
                               vpc_id=vpc.id,
                               cidr_block=data.get("pub_cidr"),
                               map_public_ip_on_launch=True,
                               tags={
                                   "Name": data.get("pub_subnet_name"),
                               })

# Create an Elastic IP
eip = aws.ec2.Eip(data.get("eip_name"), domain="vpc")

# Create an Internet Gateway
igw = aws.ec2.InternetGateway(data.get("igw_name"),
                              vpc_id=vpc.id,
                              tags={
                                  "Name": data.get("igw_name"),
                              })

# Create a NatGateway
nat_gateway = aws.ec2.NatGateway(data.get("natgw_name"),
                                 allocation_id=eip.allocation_id,
                                 subnet_id=public_subnet.id,
                                 tags={
                                     "Name": data.get("natgw_name"),
                                 },
                                 opts=pulumi.ResourceOptions(depends_on=[igw]))

# Create a Public Route Table
pub_route_table = aws.ec2.RouteTable(data.get("pubrttable_name"),
                                     vpc_id=vpc.id,
                                     routes=[
                                         aws.ec2.RouteTableRouteArgs(
                                             cidr_block="0.0.0.0/0",
                                             gateway_id=igw.id,
                                         )
                                     ],
                                     tags={
                                         "Name": data.get("pubrttable_name"),
                                     })

# Create a private Route Table
prv_route_table = aws.ec2.RouteTable(data.get("prvrttable_name"),
                                     vpc_id=vpc.id,
                                     routes=[
                                         aws.ec2.RouteTableRouteArgs(
                                             cidr_block="0.0.0.0/0",
                                             gateway_id=nat_gateway.id,
                                         )
                                     ],
                                     tags={
                                         "Name": data.get("prvrttable_name"),
                                     })

# Create a Public Route Association
pub_route_association = aws.ec2.RouteTableAssociation(
    data.get("pubrtasst_name"),
    route_table_id=pub_route_table.id,
    subnet_id=public_subnet.id
)

# Create a Private Route Association
prv_route_association = aws.ec2.RouteTableAssociation(
    data.get("prvrtasst_name"),
    route_table_id=prv_route_table.id,
    subnet_id=private_subnet.id
)

# Enable ssh if ssh_enable is true
sg_extra_args = {}
if ssh_enabled:
    sg_extra_args["ingress"] = [
        {
            "protocol": "tcp",
            "from_port": 22,
            "to_port": 22,
            "cidr_blocks": ["0.0.0.0/0"],

        }
    ]

# Create a Security Group
sg = aws.ec2.SecurityGroup(
    data.get("sec_grp_name"),
    egress=[
        {
            "protocol": "-1",
            "from_port": 0,
            "to_port": 0,
            "cidr_blocks": ["0.0.0.0/0"],
        }
    ],
    vpc_id=vpc.id,
    **sg_extra_args
)


sg_ca = aws.ec2.SecurityGroup(
    "CA Security Group",
    egress=[
        {
            "protocol": "-1",
            "from_port": 0,
            "to_port": 0,
            "cidr_blocks": ["0.0.0.0/0"],
        }
    ],
    vpc_id=vpc.id,
    ingress=[
        {
            "protocol": "tcp",
            "from_port": 22,
            "to_port": 22,
            "cidr_blocks": ["0.0.0.0/0"],

        },
        {
            "protocol": "tcp",
            "from_port": 443,
            "to_port": 443,
            "cidr_blocks": ["0.0.0.0/0"],

        }
    ]
)

# Get the Key Pair, Can Also Create New one
keypair = aws.ec2.get_key_pair(key_name=data.get("key_name"), include_public_key=True)

# Getting Twingate Connector AMI
ami = aws.ec2.get_ami(most_recent=True,
                      owners=["617935088040"],
                      filters=[{"name": "name", "values": ["twingate/images/hvm-ssd/twingate-amd64-*"]}])

# Create a Twingate remote network
remote_network = tg.TwingateRemoteNetwork(data.get("tg_remote_network"), name=data.get("tg_remote_network"))

connectors = data.get("connectors")

# Create an EC2 Instance for CA
if True:
    ca_ec2_instance = aws.ec2.Instance(
        "smallstep-ca",
        tags={
            "Name": "smallstep-ca",
        },
        instance_type=data.get("ec2_type"),
        vpc_security_group_ids=[sg_ca.id],
        ami=ami.id,
        key_name=keypair.key_name,
        user_data=init_aws_ca_script,
        subnet_id=private_subnet.id,
        private_ip="10.0.1.104",  # TODO TEMP
        associate_public_ip_address=False,
    )

    ca_a_record = aws.route53.Record('ca_a_record',
                                     name=f"{ca_config.get('ca_hostname')}.",
                                     zone_id=dns_zone.id,
                                     type="A",
                                     ttl=300,
                                     records=[ca_ec2_instance.private_ip],
                                     )

    tg_ca_resource = tg.TwingateResource('ca_tg_resource',
                                         name='Certificate Authority',
                                         remote_network_id=remote_network.id,
                                         address=ca_domain
                                         )

def get_string_after_first_line(val: str):
    return "\n".join(val.splitlines()[1:])


def get_connector_user_data(access_token, refresh_token, connector_name):
    host_fqdn = f"tg-{connector_name}.{data.get('domain')}"
    connector_init = init_connector_template.format(tg_account=tg_account, access_token=access_token, refresh_token=refresh_token, host_fqdn=host_fqdn)
    connector_ssh = init_aws_ssh_host_template.format(ca_url=f"https://{ca_domain}", host_fqdn=host_fqdn)
    user_data = connector_init + get_string_after_first_line(connector_ssh)
    return user_data

# Create a EC2 Instance For Each Connector
for i in range(1, connectors + 1):
    connector = tg.TwingateConnector(f"twingate_connector_{i}", name="", remote_network_id=remote_network.id)
    connector_token = tg.TwingateConnectorTokens(f"connector_token_{i}", connector_id=connector.id)
    user_data = pulumi.Output.all(connector_token.access_token, connector_token.refresh_token, connector.name).apply(lambda v: get_connector_user_data(access_token=v[0], refresh_token=v[1], connector_name=v[2]))
    if True:
        ec2_instance = aws.ec2.Instance(
            f"Twingate-Connector-{i}",
            tags={
                "Name": pulumi.Output.all(connector.name).apply(lambda v: f"tg-{v[0]}"),
            },
            instance_type=data.get("ec2_type"),
            vpc_security_group_ids=[sg.id],
            ami=ami.id,
            key_name=keypair.key_name,
            user_data=user_data,
            subnet_id=private_subnet.id,
            associate_public_ip_address=False,
        )
        connector_a_record = aws.route53.Record(f"connector_a_record-{i}",
                                         name=pulumi.Output.all(connector.name).apply(lambda v: f"tg-{v[0]}."),
                                         zone_id=dns_zone.id,
                                         type="A",
                                         ttl=300,
                                         records=[ec2_instance.private_ip],
                                         )

        connector_tg_resource = tg.TwingateResource(f"connector_tg_resource-{i}",
                                             name=pulumi.Output.all(connector.name).apply(lambda v: f"Twingate Connector {v[0]}"),
                                             remote_network_id=remote_network.id,
                                             address=pulumi.Output.all(connector.name).apply(lambda v: f"tg-{v[0]}.{data.get('domain')}")
                                             )

