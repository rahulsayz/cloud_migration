import base64
import requests
import json
import os
import hcl2  # Terraform language parser
from dotenv import load_dotenv
from pathlib import Path
import subprocess
from azure.identity import ClientSecretCredential
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.security import SecurityCenter
import boto3
from botocore.exceptions import ClientError

# Load environment variables from .env file
load_dotenv()
openai_api_key = os.getenv('OPENAI_API_KEY')

openai_url = "https://api.openai.com/v1/chat/completions"
openai_headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {openai_api_key}"
}

# Get the source and target clouds from the user
source_cloud = input("Enter the source cloud (azure or aws): ").lower()
target_cloud = "gcp"

# Define the local directory to store the Terraform files
script_dir = Path(__file__).parent
local_dir = script_dir / "terraform"
local_dir.mkdir(parents=True, exist_ok=True)


def generate_provider_and_required_providers(aws_provider_config, google_provider_config):
    provider_block = f"""
provider "aws" {{
  {aws_provider_config}
}}

provider "google" {{
  {google_provider_config}
}}
"""

    required_providers_block = f"""
terraform {{
  required_providers {{
    aws = {{
      source = "hashicorp/aws"
    }}
    google = {{
      source = "hashicorp/google"
    }}
  }}
}}
"""

    return provider_block, required_providers_block

import os
from pathlib import Path

def generate_provider_and_required_providers(aws_provider_config, google_provider_config):
    provider_block = f"""
provider "aws" {{
  {aws_provider_config}
}}

provider "google" {{
  {google_provider_config}
}}
"""

    required_providers_block = f"""
terraform {{
  required_providers {{
    aws = {{
      source = "hashicorp/aws"
    }}
    google = {{
      source = "hashicorp/google"
    }}
  }}
}}
"""

    return provider_block, required_providers_block


def generate_terraform_code(resource_name, resource_type, aws_service="", resource_details="", aws_provider_config="", google_provider_config=""):
    # Mapping of AWS services to GCP resources
    aws_to_gcp_resource_map = {
        "ec2": "google_compute_instance",
        "s3": "google_storage_bucket",
        "rds": "google_sql_database_instance",
        "vpc": "google_compute_network",
        "security_group": "google_compute_firewall"
    }

    target_gcp_resource = aws_to_gcp_resource_map.get(aws_service.lower(), "google_resource")

    if aws_service.lower() == "ec2":
        prompt = f"Provide a complete Terraform configuration to migrate the 'EC2 Instance' resource '{resource_name}' from AWS to the '{target_gcp_resource}' resource in Google Cloud Platform. The resource details are: {resource_details}"
    elif aws_service.lower() == "s3":
        prompt = f"Provide a complete Terraform configuration to migrate the 'S3 Bucket' resource '{resource_name}' from AWS to the '{target_gcp_resource}' resource in Google Cloud Platform. The resource details are: {resource_details}"
    elif aws_service.lower() == "rds":
        prompt = f"Provide a complete Terraform configuration to migrate the 'RDS Instance' resource '{resource_name}' from AWS to the '{target_gcp_resource}' resource in Google Cloud Platform. The resource details are: {resource_details}"
    elif aws_service.lower() == "vpc":
        prompt = f"Provide a complete Terraform configuration to migrate the 'VPC' resource '{resource_name}' from AWS to the '{target_gcp_resource}' resource in Google Cloud Platform. The resource details are: {resource_details}"
    elif aws_service.lower() == "security_group":
        prompt = f"Provide a complete Terraform configuration to migrate the 'Security Group' resource '{resource_name}' from AWS to the '{target_gcp_resource}' resource in Google Cloud Platform. The resource details are: {resource_details}"
    else:
        prompt = f"Provide a complete Terraform configuration to migrate the '{resource_type}' resource '{resource_name}' from AWS to the '{target_gcp_resource}' resource in Google Cloud Platform. The resource details are: {resource_details}"

    messages = [{"role": "user", "content": prompt}]
    data = {
        "model": "gpt-3.5-turbo",
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 4096
    }
    response = requests.post(openai_url, headers=openai_headers, json=data)
    terraform_code = response.json()["choices"][0]["message"]["content"].strip()

    # Remove any non-Terraform code or prompts from the response
    terraform_code = terraform_code.split("```")[0].strip()  # Assuming the valid Terraform code does not contain ```

    # Parse the Terraform code to check for errors
    try:
        parsed_code = hcl2.loads(terraform_code)
    except hcl2.HCLError as e:
        print(f"Error parsing Terraform code: {e}")
        return None

    # Generate a unique resource name based on the resource type, AWS service, and other identifiers
    unique_resource_name = f"{aws_service.lower()}_{resource_type.lower()}_{resource_name.replace('-', '_')}.tf"

    # Determine the output file path based on the resource type
    output_dir = local_dir / source_cloud / target_cloud
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / unique_resource_name

    # Prepend the provider and required providers blocks
    provider_block, required_providers_block = generate_provider_and_required_providers(aws_provider_config, google_provider_config)
    updated_terraform_code = f"{provider_block}\n{required_providers_block}\n{terraform_code}"

    # Write the Terraform code to the file
    with output_path.open('w') as f:
        f.write(updated_terraform_code)

    # Validate the Terraform code
    try:
        subprocess.check_output(['terraform', 'validate', str(output_dir)], universal_newlines=True)
    except subprocess.CalledProcessError as e:
        print(f"Terraform validation error: {e.output}")
        # Log the need for manual review
        print("Please review the generated Terraform code for errors and correct them manually.")

    return updated_terraform_code


 
if source_cloud == "azure":
   # Get the Azure credentials from the user
   tenant_id = input("Enter your Azure tenant ID: ")
   client_id = input("Enter your Azure client ID: ")
   client_secret = input("Enter your Azure client secret: ")
   subscription_id = input("Enter your Azure subscription ID: ")

   # Set up the Azure credentials
   credential = ClientSecretCredential(
       tenant_id=tenant_id,
       client_id=client_id,
       client_secret=client_secret
   )

   # Create the resource management, network, and security clients
   resource_client = ResourceManagementClient(credential, subscription_id)
   network_client = NetworkManagementClient(credential, subscription_id)
   security_client = SecurityCenter(credential)

   # Get a list of all the resource groups
   resource_groups = resource_client.resource_groups.list()

   for resource_group in resource_groups:
       # Get a list of all the resources in the resource group
       resources = resource_client.resources.list_by_resource_group(resource_group.name)

       for resource in resources:
           # Retrieve the security services details
           security_services = security_client.security_assessments.list()

           resource_details = f"Resource Name: {resource.name}\nResource Type: {resource.type.split('/')[-1]}\nLocation: {resource.location}\nResource Group: {resource_group.name}\nSecurity Services: {security_services}"
           terraform_code_snippet = generate_terraform_code(resource.name, resource.type.split('/')[-1], resource_details)

           # Determine the output file path based on the resource type
           output_path = local_dir / f"azure_to_gcp_{resource.type.split('/')[-1]}_{resource.name}.tf"

           # Write the Terraform code snippet to the file
           with output_path.open('w') as f:
               f.write(terraform_code_snippet)
           print(f"Terraform code snippet for '{resource.name}' saved to: {output_path}")

       # Get a list of all the virtual networks in the resource group
       virtual_networks = network_client.virtual_networks.list(resource_group.name)
       for vnet in virtual_networks:
           resource_details = f"Virtual Network Name: {vnet.name}\nLocation: {vnet.location}\nResource Group: {resource_group.name}"
           terraform_code_snippet = generate_terraform_code(vnet.name, "Virtual Network", resource_details)

           # Determine the output file path
           output_path = local_dir / f"azure_to_gcp_vnet_{vnet.name}.tf"

           # Write the Terraform code snippet to the file
           with output_path.open('w') as f:
               f.write(terraform_code_snippet)
           print(f"Terraform code snippet for '{vnet.name}' saved to: {output_path}")

       # Get a list of all the network security groups in the resource group
       network_security_groups = network_client.network_security_groups.list(resource_group.name)
       for nsg in network_security_groups:
           resource_details = f"Network Security Group Name: {nsg.name}\nLocation: {nsg.location}\nResource Group: {resource_group.name}"
           terraform_code_snippet = generate_terraform_code(nsg.name, "Network Security Group", resource_details)

           # Determine the output file path
           output_path = local_dir / f"azure_to_gcp_nsg_{nsg.name}.tf"

           # Write the Terraform code snippet to the file
           with output_path.open('w') as f:
               f.write(terraform_code_snippet)
           print(f"Terraform code snippet for '{nsg.name}' saved to: {output_path}")

elif source_cloud == "aws":
   # Get the AWS credentials from the user
   aws_access_key_id = input("Enter your AWS access key ID: ")
   aws_secret_access_key = input("Enter your AWS secret access key: ")

   # Set up the AWS credentials
   session = boto3.Session(
       aws_access_key_id=aws_access_key_id,
       aws_secret_access_key=aws_secret_access_key,
       region_name='us-east-1'
   )

   # Create the resource management client
   ec2_client = session.client('ec2')
   s3_client = session.client('s3')
   rds_client = session.client('rds')
   vpc_client = session.client('ec2')
   security_client = session.client('ec2')

   # Get a list of all the EC2 instances
   try:
       instances = ec2_client.describe_instances()['Reservations']
   except ClientError as e:
       print(f"Error retrieving EC2 instances: {e}")
       instances = []

   # Get a list of all the S3 buckets
   try:
       s3_buckets = s3_client.list_buckets()['Buckets']
   except ClientError as e:
       print(f"Error retrieving S3 buckets: {e}")
       s3_buckets = []

   # Get a list of all the RDS instances
   try:
       rds_instances = rds_client.describe_db_instances()['DBInstances']
   except ClientError as e:
       print(f"Error retrieving RDS instances: {e}")
       rds_instances = []

   # Get a list of all the VPCs
   try:
       vpcs = vpc_client.describe_vpcs()['Vpcs']
   except ClientError as e:
       print(f"Error retrieving VPCs: {e}")
       vpcs = []

   # Get a list of all the security groups
   try:
       security_groups = security_client.describe_security_groups()['SecurityGroups']
   except ClientError as e:
       print(f"Error retrieving security groups: {e}")
       security_groups = []

   for instance in instances:
       instance_id = instance['Instances'][0]['InstanceId']
       resource_details = f"Instance ID: {instance_id}"
       terraform_code_snippet = generate_terraform_code(instance_id, "EC2 Instance", resource_details)

       # Determine the output file path
       output_path = local_dir / f"aws_to_gcp_ec2_{instance_id}.tf"

       # Write the Terraform code snippet to the file
       with output_path.open('w') as f:
           f.write(terraform_code_snippet)
       print(f"Terraform code snippet for '{instance_id}' saved to: {output_path}")

   for bucket in s3_buckets:
       bucket_name = bucket['Name']
       resource_details = f"Bucket Name: {bucket_name}"
       terraform_code_snippet = generate_terraform_code(bucket_name, "S3 Bucket", resource_details)

       # Determine the output file path
       output_path = local_dir / f"aws_to_gcp_s3_{bucket_name}.tf"

       # Write the Terraform code snippet to the file
       with output_path.open('w') as f:
           f.write(terraform_code_snippet)
       print(f"Terraform code snippet for '{bucket_name}' saved to: {output_path}")

   for rds_instance in rds_instances:
       instance_id = rds_instance['DBInstanceIdentifier']
       resource_details = f"Instance ID: {instance_id}"
       terraform_code_snippet = generate_terraform_code(instance_id, "RDS Instance", resource_details)

       # Determine the output file path
       output_path = local_dir / f"aws_to_gcp_rds_{instance_id}.tf"

       # Write the Terraform code snippet to the file
       with output_path.open('w') as f:
           f.write(terraform_code_snippet)
       print(f"Terraform code snippet for '{instance_id}' saved to: {output_path}")

   for vpc in vpcs:
       vpc_id = vpc['VpcId']
       resource_details = f"VPC ID: {vpc_id}"
       terraform_code_snippet = generate_terraform_code(vpc_id, "VPC", resource_details)

       # Determine the output file path
       output_path = local_dir / f"aws_to_gcp_vpc_{vpc_id}.tf"

       # Write the Terraform code snippet to the file
       with output_path.open('w') as f:
           f.write(terraform_code_snippet)
       print(f"Terraform code snippet for '{vpc_id}' saved to: {output_path}")

   for security_group in security_groups:
       group_id = security_group['GroupId']
       resource_details = f"Security Group ID: {group_id}"
       terraform_code_snippet = generate_terraform_code(group_id, "Security Group", resource_details)

       # Determine the output file path
       output_path = local_dir / f"aws_to_gcp_security_group_{group_id}.tf"

       # Write the Terraform code snippet to the file
       with output_path.open('w') as f:
           f.write(terraform_code_snippet)
       print(f"Terraform code snippet for '{group_id}' saved to: {output_path}")

else:
   print("Invalid source cloud. Please enter 'azure' or 'aws'.")
