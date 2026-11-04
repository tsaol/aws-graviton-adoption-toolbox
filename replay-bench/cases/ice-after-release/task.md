After the Graviton rollout, the customer's web tier launched fine for the first two nights. Since then, launches fail again at night. The customer asks why it came back and what to do.

The files in ./input are:
- events.jsonl: CloudTrail events exported from their account (region eu-west-1), including RunInstances and capacity reservation events.
- subnet-map.json: subnet ID to Availability Zone.
- az-ids.json: Availability Zone name to AZ ID.

The web tier's primary instance type is m8g.24xlarge, with m8g.16xlarge as the fallback.

Find out why launches fail again. Tell them what to do now, what to do differently next time, and who owns each action. Write your final answer to ./answer.md.
