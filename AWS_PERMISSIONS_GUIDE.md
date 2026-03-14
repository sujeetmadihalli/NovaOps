# AWS & System Permission Requirements

To ensure a flawless live demonstration of the Amazon Nova automated SRE pipeline, please verify the following permissions and access grants are properly configured.

## 1. Amazon Bedrock Model Access (CRITICAL)

By default, AWS accounts **do not** have access to foundational models. You must explicitly request access to the Amazon Nova models before running the demo, otherwise Bedrock will return `AccessDeniedException`.

**Steps to enable:**
1. Log into the AWS Management Console.
2. Search for **Amazon Bedrock**.
3. Ensure you are in the same region you set in `.env` (e.g., `us-east-1` or `us-east-2`).
4. On the left sidebar, scroll down to **Model access**.
5. Click **Modify model access** (top right).
6. Scroll to the **Amazon** provider section and check the boxes for:
   - ✅ **Amazon Nova Lite** (`us.amazon.nova-2-lite-v1:0`)
   - ✅ **Amazon Nova Sonic** (`us.amazon.nova-2-sonic-v1:0`)
7. Click **Next** and submit the request. Access is usually granted within minutes.

## 2. AWS IAM User Permissions

The AWS Access Key and Secret Key placed in your `.env` file must belong to an IAM User (or Role) that has permissions to invoke Bedrock. Because we are using LocalStack for DynamoDB and S3, the only real AWS interaction happening over the internet is the LLM inference.

**Required IAM Policy Definition:**
Attach the following inline policy to your IAM User:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "NovaOpsBedrockAccess",
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
                "bedrock:Converse",
                "bedrock:ConverseStream"
            ],
            "Resource": [
                "arn:aws:bedrock:*::foundation-model/us.amazon.nova-2-lite-v1:0",
                "arn:aws:bedrock:*::foundation-model/us.amazon.nova-2-sonic-v1:0"
            ]
        }
    ]
}
```

*Note: You saw an `AccessDeniedException` error for CloudWatch logs (`logs:FilterLogEvents`) during the simulation. This is entirely normal and expected. The `aggregator.logs` module is designed to gracefully fallback to local mocked logs when investigating Minikube instances, so you do NOT need to add CloudWatch IAM permissions!*

## 3. Docker & Local System Permissions

You have already successfully verified these via the recent script executions, but keep them in mind if you migrate the code to a new presentation laptop:

1. **Docker Group Allocation**: Ensure the user running `./start_system.sh` and `minikube` is added to the `docker` user group to avoid needing `sudo` (e.g., `sudo usermod -aG docker $USER`).
2. **Audio Hardware Access**: Running `sonic_call.py` requires direct access to `/dev/snd`. If you demo this from a WSL (Windows Subsystem for Linux) instance instead of a native Mac/Linux machine, passing the microphone hardware to WSL can be notoriously difficult. The application is now designed to safely fallback to a textual interface if the microphone errors out.
3. **Port Availability**: The system relies on the following local TCP ports. Ensure no other databases or apps are hoarding them:
   - `8080`: Dummy Service
   - `8081`: Vue.js Dashboard UI
   - `8082`: FastAPI Backend
   - `4566`: LocalStack (DynamoDB & S3 Mock)
   - `9090`: Prometheus (if run globally)
