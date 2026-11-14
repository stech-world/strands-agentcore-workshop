"""AWS Lambda function exposed as MCP tools through AgentCore Gateway (Lab 3).

It implements two mocked tools with in-memory data and the Python standard
library only, so it is deployed as a single file without layers or databases:

- check_warranty_status: look up the warranty of a product by serial number
- web_search: the Lab 1 web search tool, now shared through the Gateway

AgentCore Gateway passes the tool arguments in the event and the tool name in
the client context as "<target name>___<tool name>".
"""

from datetime import date, timedelta

# Mock warranty database: serial number -> product, purchase date and coverage
_TODAY = date.today()
WARRANTIES = {
    "MNO33333333": {
        "product": "Gaming Console Pro",
        "customer_email": "john.doe@example.com",
        "purchase_date": _TODAY - timedelta(days=200),
        "warranty_days": 730,
    },
    "ABC12345678": {
        "product": "Smartphone X",
        "customer_email": "jane.smith@example.com",
        "purchase_date": _TODAY - timedelta(days=400),
        "warranty_days": 365,
    },
    "XYZ98765432": {
        "product": "Laptop Pro 14",
        "customer_email": "alex.lee@example.com",
        "purchase_date": _TODAY - timedelta(days=350),
        "warranty_days": 365,
    },
}


def check_warranty_status(serial_number: str, customer_email: str = None) -> str:
    record = WARRANTIES.get(serial_number.strip().upper())
    if not record:
        return f"No warranty found for serial number {serial_number}."
    if customer_email and customer_email.strip().lower() != record["customer_email"]:
        return f"The email provided does not match our records for serial number {serial_number}."

    end_date = record["purchase_date"] + timedelta(days=record["warranty_days"])
    days_left = (end_date - _TODAY).days
    if days_left > 30:
        status = "Active"
    elif days_left > 0:
        status = "Expiring soon"
    else:
        status = "Expired"

    return (
        f"Warranty status for {record['product']} (serial {serial_number}):\n"
        f"• Status: {status}\n"
        f"• Purchase date: {record['purchase_date'].isoformat()}\n"
        f"• Warranty end date: {end_date.isoformat()} ({max(days_left, 0)} days left)"
    )


def web_search(keywords: str, max_results: int = 3) -> str:
    # Same mocked results as the Lab 1 local tool
    mock_results = [
        (f"{keywords} - Troubleshooting guide", "https://support.example.com/troubleshooting"),
        (f"{keywords} - Community forum", "https://community.example.com/threads"),
        (f"{keywords} - Latest firmware and software updates", "https://updates.example.com/release-notes"),
    ]
    results = mock_results[: max(1, min(int(max_results), len(mock_results)))]
    return "\n".join(f"- {title} ({href})" for title, href in results)


def lambda_handler(event, context):
    tool_name = context.client_context.custom["bedrockAgentCoreToolName"].split("___")[-1]
    print(f"Tool: {tool_name}, arguments: {event}")

    if tool_name == "check_warranty_status":
        if not event.get("serial_number"):
            return {"statusCode": 400, "body": "Please provide serial_number"}
        body = check_warranty_status(event["serial_number"], event.get("customer_email"))
    elif tool_name == "web_search":
        if not event.get("keywords"):
            return {"statusCode": 400, "body": "Please provide keywords"}
        body = web_search(event["keywords"], event.get("max_results", 3))
    else:
        return {"statusCode": 400, "body": f"Unknown tool: {tool_name}"}

    return {"statusCode": 200, "body": body}
