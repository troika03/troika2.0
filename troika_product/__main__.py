"""Operator CLI for provisioning closed-beta Troika access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from troika_product.access import AccessRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision Troika beta access")
    parser.add_argument("--database", type=Path, help="Path to the access SQLite database")
    subcommands = parser.add_subparsers(dest="command", required=True)
    provision = subcommands.add_parser("provision", help="Create a user, device, and token")
    provision.add_argument("--email", required=True)
    provision.add_argument("--device-name", required=True)
    provision.add_argument("--platform", required=True, choices=("android", "ios", "web", "desktop"))
    provision.add_argument("--plan", default="beta")
    provision.add_argument("--daily-request-limit", type=int, default=50)
    set_limit = subcommands.add_parser("set-limit", help="Change a user's plan and daily request limit")
    set_limit.add_argument("--user-id", required=True)
    set_limit.add_argument("--plan", required=True)
    set_limit.add_argument("--daily-request-limit", type=int, required=True)
    audit = subcommands.add_parser("audit", help="Show privacy-safe audit events for one user")
    audit.add_argument("--user-id", required=True)
    audit.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    registry = AccessRegistry(args.database)
    if args.command == "provision":
        user_id = registry.create_user(
            args.email,
            plan=args.plan,
            daily_request_limit=args.daily_request_limit,
        )
        device_id = registry.create_device(
            user_id, name=args.device_name, platform=args.platform
        )
        token = registry.issue_device_token(device_id)
        print(f"user_id={user_id}")
        print(f"device_id={device_id}")
        print(f"plan={args.plan}")
        print(f"daily_request_limit={args.daily_request_limit}")
        print(f"token={token}")
        print("Save the token securely: it is shown only once.")
        return 0
    if args.command == "set-limit":
        registry.set_entitlement(
            args.user_id,
            plan=args.plan,
            daily_request_limit=args.daily_request_limit,
        )
        print(f"user_id={args.user_id}")
        print(f"plan={args.plan}")
        print(f"daily_request_limit={args.daily_request_limit}")
        return 0
    if args.command == "audit":
        for event in registry.list_audit_events(args.user_id, limit=args.limit):
            print(
                json.dumps(
                    {
                        "id": event.id,
                        "occurred_at": event.occurred_at,
                        "event_type": event.event_type,
                        "user_id": event.user_id,
                        "device_id": event.device_id,
                        "session_digest": event.session_digest,
                        "run_digest": event.run_digest,
                        "details": event.details,
                    },
                    sort_keys=True,
                )
            )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
