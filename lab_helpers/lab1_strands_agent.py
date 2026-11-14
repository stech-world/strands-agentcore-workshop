"""Lab 1 customer support agent: model, system prompt and local tools.

get_return_policy, get_product_info and web_search are mocked with in-memory
data. get_technical_support searches the Amazon Bedrock Knowledge Base created
in Lab 1. The same tools are reused by Labs 2, 3 and 4.
"""

import boto3
from strands.tools import tool

MODEL_ID = "global.amazon.nova-2-lite-v1:0"

# System prompt defining the agent's role and capabilities
SYSTEM_PROMPT = """You are a helpful and professional customer support assistant for an electronics e-commerce company.
Your role is to:
- Provide accurate information using the tools available to you
- Support the customer with technical information, product specifications and maintenance questions
- Be friendly, patient, and understanding with customers
- Always offer additional help after answering questions
- If you can't help with something, direct customers to the appropriate contact

You have access to the following tools:
1. get_return_policy() - For warranty and return policy questions
2. get_product_info() - To get information about a specific product
3. web_search() - To search for updated information on the web
4. get_technical_support() - For troubleshooting issues, setup guides and maintenance tips
For any technical problems, setup questions, or maintenance concerns, always use the get_technical_support() tool.

Always use the appropriate tool to get accurate, up-to-date information rather than making assumptions about electronic products or specifications."""


@tool
def get_return_policy(product_category: str) -> str:
    """
    Get return policy information for a specific product category.

    Args:
        product_category: Electronics category (e.g., 'smartphones', 'laptops', 'accessories')

    Returns:
        Formatted return policy details including timeframes and conditions
    """
    # Mock return policy database
    return_policies = {
        "smartphones": {
            "window": "30 days",
            "condition": "Original packaging, no physical damage, factory reset required",
            "refund_time": "5-7 business days after inspection",
            "warranty": "1-year manufacturer warranty included",
        },
        "laptops": {
            "window": "30 days",
            "condition": "Original packaging, all accessories, no software modifications",
            "refund_time": "7-10 business days after inspection",
            "warranty": "1-year manufacturer warranty, extended options available",
        },
        "accessories": {
            "window": "30 days",
            "condition": "Unopened packaging preferred, all components included",
            "refund_time": "3-5 business days after receipt",
            "warranty": "90-day manufacturer warranty",
        },
    }
    default_policy = {
        "window": "30 days",
        "condition": "Original condition with all included components",
        "refund_time": "5-7 business days after inspection",
        "warranty": "Standard manufacturer warranty applies",
    }

    policy = return_policies.get(product_category.lower(), default_policy)
    return (
        f"Return Policy - {product_category.title()}:\n"
        f"• Return window: {policy['window']} from delivery\n"
        f"• Condition: {policy['condition']}\n"
        f"• Refund timeline: {policy['refund_time']}\n"
        f"• Warranty: {policy['warranty']}"
    )


@tool
def get_product_info(product_type: str) -> str:
    """
    Get technical specifications and information for electronics products.

    Args:
        product_type: Electronics product type (e.g., 'laptops', 'smartphones', 'headphones', 'monitors')

    Returns:
        Formatted product information including warranty, specs and features
    """
    # Mock product catalog
    products = {
        "laptops": {
            "warranty": "1-year manufacturer warranty + optional extended coverage",
            "specs": "Intel/AMD processors, 8-32GB RAM, SSD storage",
            "features": "Backlit keyboard, USB-C/Thunderbolt, Wi-Fi 6",
        },
        "smartphones": {
            "warranty": "1-year manufacturer warranty",
            "specs": "5G connectivity, 128GB-1TB storage, multiple cameras",
            "features": "Wireless charging, water resistance, biometric security",
        },
        "headphones": {
            "warranty": "1-year manufacturer warranty",
            "specs": "Wired/wireless options, 20Hz-20kHz frequency response",
            "features": "Active noise cancellation, touch controls",
        },
        "monitors": {
            "warranty": "3-year manufacturer warranty",
            "specs": "4K/1440p/1080p resolutions, IPS/OLED panels",
            "features": "HDR support, high refresh rates, adjustable stand",
        },
    }
    product = products.get(product_type.lower())
    if not product:
        return f"No product information available for '{product_type}'. Please contact our support team."

    return (
        f"Product Information - {product_type.title()}:\n"
        f"• Warranty: {product['warranty']}\n"
        f"• Specifications: {product['specs']}\n"
        f"• Key features: {product['features']}"
    )


@tool
def web_search(keywords: str, max_results: int = 3) -> str:
    """
    Search the web for updated information (mocked: returns canned results).

    Args:
        keywords: The search query keywords
        max_results: The maximum number of results to return

    Returns:
        A list of search results with title, link and snippet
    """
    # Mock search index: a real implementation would call a search API
    mock_results = [
        {
            "title": f"{keywords} - Troubleshooting guide",
            "href": "https://support.example.com/troubleshooting",
            "body": f"Common causes and step-by-step fixes for '{keywords}', verified by our support team.",
        },
        {
            "title": f"{keywords} - Community forum",
            "href": "https://community.example.com/threads",
            "body": f"Users discuss their experience with '{keywords}' and share workarounds.",
        },
        {
            "title": f"{keywords} - Latest firmware and software updates",
            "href": "https://updates.example.com/release-notes",
            "body": "Keeping firmware and software up to date fixes most known issues.",
        },
    ]
    results = mock_results[: max(1, min(max_results, len(mock_results)))]
    return "\n".join(f"- {r['title']} ({r['href']}): {r['body']}" for r in results)


@tool
def get_technical_support(issue_description: str) -> str:
    """
    Get troubleshooting steps, setup guides and maintenance tips from the technical documentation.

    Args:
        issue_description: Description of the customer's technical issue or question

    Returns:
        The most relevant passages of the technical documentation
    """
    try:
        # The Knowledge Base is created in Lab 1, which stores its ID in SSM Parameter Store
        kb_id = boto3.client("ssm").get_parameter(Name="/app/customersupport/knowledge_base/id")["Parameter"]["Value"]

        response = boto3.client("bedrock-agent-runtime").retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": issue_description},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3}},
        )
        passages = []
        for result in response["retrievalResults"]:
            source = result.get("location", {}).get("s3Location", {}).get("uri", "").split("/")[-1]
            passages.append(f"[{source}]\n{result['content']['text']}")
        return "\n\n".join(passages) if passages else "No relevant technical documentation found."
    except Exception as e:
        return f"Unable to access technical support documentation. Error: {e}"
