The customer's platform team says that since their Graviton rollout started three nights ago, their Auto Scaling groups keep failing to launch instances at night. They ask whether they should pause the rollout.

The files in ./input are:
- events.jsonl.gz: CloudTrail RunInstances events exported from their account (region eu-west-1).
- subnet-map.json: subnet ID to Availability Zone.
- az-ids.json: Availability Zone name to AZ ID.
- capacity-snapshot.json: a capacity snapshot that the AWS account team shared, showing free capacity by instance type and AZ at a few points in time.
- usage-hourly.csv: hourly EC2 usage from their Cost and Usage Report.

The web tier's primary instance type is m8g.24xlarge, with m8g.16xlarge as the fallback.

Find out why launches fail. Tell them whether to keep rolling out, what to do, and who owns each action. Write your final answer to ./answer.md.
