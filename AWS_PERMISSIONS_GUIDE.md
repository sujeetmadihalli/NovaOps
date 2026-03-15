# AWS & System Permission Requirements

To ensure a flawless deployment of the Amazon Nova automated SRE pipeline, verify the following permissions and access grants are properly configured.

## 1. Amazon Bedrock Model Access (CRITICAL)

By default, AWS accounts **do not** have access to foundational models. You must explicitly request access to the Amazon Nova models before running the system, otherwise Bedrock will return `AccessDeniedException`.

**Steps to enable:**

1. Log into the AWS Management Console.
2. Search for **Amazon Bedrock**.
3. Ensure you are in the same region you set in `.env` (e.g., `us-east-1` or `us-east-2`).
4. On the left sidebar, scroll down to **Model access**.
5. Click **Modify model access** (top right).
6. Scroll to the **Amazon** provider section and check the boxes for:
   - **Amazon Nova Lite** (`us.amazon.nova-2-lite-v1:0`)
   - **Amazon Nova Sonic** (`us.amazon.nova-2-sonic-v1:0`)
7. Click **Next** and submit the request. Access is usually granted within minutes.

## 2. AWS IAM User Permissions

The AWS credentials in your `.env` file (or `~/.aws/credentials`) must have permissions to invoke Bedrock. Because we use LocalStack for DynamoDB and S3, the only real AWS interaction over the internet is LLM inference and (optionally) Amazon Connect for voice escalation.

**Required IAM Policy -- Bedrock Only (minimum):**

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

*Note: The `aggregator.logs` module may attempt CloudWatch `logs:FilterLogEvents` calls. This is expected to fail gracefully -- the system falls back to local mocked logs when running against Minikube. No CloudWatch IAM permissions are needed.*

## 3. Amazon Connect Permissions (Voice Escalation Only)

If you enable real outbound phone calls (`NOVAOPS_VOICE_USE_MOCK=false`), the IAM user also needs Connect permissions.

**Additional IAM Policy -- Amazon Connect:**

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "NovaOpsConnectAccess",
            "Effect": "Allow",
            "Action": [
                "connect:StartOutboundVoiceContact",
                "connect:StopContact",
                "connect:DescribeContact"
            ],
            "Resource": [
                "arn:aws:connect:*:*:instance/YOUR_INSTANCE_ID/*"
            ]
        }
    ]
}
```

**Amazon Connect setup checklist:**

1. Create an Amazon Connect instance in the AWS console.
2. Claim a phone number for outbound calls.
3. Create a Contact Flow that:
   - Plays the `briefing_script` contact attribute via Polly TTS.
   - Routes to a Lex V2 bot for conversational AI.
4. Create a Lex V2 bot with a `VoiceEscalation` intent, fulfillment pointed at the Lambda.
5. Deploy `lambda_handlers/nova_connect_handler.py` as an AWS Lambda function.
6. Set environment variables: `CONNECT_INSTANCE_ID`, `CONNECT_CONTACT_FLOW_ID`, `CONNECT_SOURCE_PHONE`, `ONCALL_PHONE_NUMBER`.

**Lambda IAM Policy:**

The Lambda function needs Bedrock access (same as above) plus the ability to call back to the NovaOps API. If the API is not publicly accessible, configure a VPC endpoint or use API Gateway.

## 4. Docker & Local System Permissions

Keep these in mind if you set up the system on a new machine:

1. **Docker Group**: Ensure the user running `./start_system.sh` and `minikube` is added to the `docker` user group (e.g., `sudo usermod -aG docker $USER`).
2. **Audio Hardware Access**: Running `sonic_call.py` requires direct access to audio devices (`/dev/snd` on Linux). On WSL, passing microphone hardware can be difficult. The application falls back to a text interface if audio fails.
3. **Port Availability**: The system uses these local TCP ports:
   - `8080`: Dummy Service
   - `8081`: Vue.js Dashboard UI
   - `8082`: FastAPI Backend
   - `4566`: LocalStack (DynamoDB & S3)
   - `9090`: Prometheus (if run globally)

## 5. Credential Security

- **Never commit credentials** to the repository. Use `.env` (git-ignored) or `aws configure`.
- **Rotate keys regularly**, especially if they were ever exposed in logs, chat, or version control.
- **Use IAM roles** instead of long-lived access keys when running in AWS (EC2, ECS, Lambda).
- The `.env.example` file documents all environment variables without containing real values.
