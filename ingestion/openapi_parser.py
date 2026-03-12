"""
OpenAPI Parser — ingests official OpenAPI JSON/YAML specs from GitHub.

Platforms handled here (they publish public OpenAPI specs):
  - Twilio      → github.com/twilio/twilio-oai
  - SendGrid    → github.com/twilio/sendgrid-oai
  - Stripe      → github.com/stripe/openapi
  - Google Maps → uses REST Discovery API

Meta/WhatsApp/Instagram are NOT handled here — they require Playwright scraping.
"""

import httpx
import yaml
import json
import logging
from typing import List, Dict, Any, Optional
from models import APIEntry, APIParameter

logger = logging.getLogger(__name__)

# Official raw spec URLs
OPENAPI_SOURCES = {
    "Twilio": [
        "https://raw.githubusercontent.com/twilio/twilio-oai/main/spec/json/twilio_messaging_v1.json",
        "https://raw.githubusercontent.com/twilio/twilio-oai/main/spec/json/twilio_verify_v2.json",
        "https://raw.githubusercontent.com/twilio/twilio-oai/main/spec/json/twilio_lookups_v2.json",
    ],
    "SendGrid": [
        "https://raw.githubusercontent.com/twilio/sendgrid-oai/main/oai.yaml",
    ],
    "Stripe": [
        "https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json",
    ],
}

# Stripe endpoints we care about (spec has 600+ endpoints — filter to relevant ones)
STRIPE_ENDPOINT_FILTER = [
    "/v1/payment_intents",
    "/v1/payment_intents/{intent}",
    "/v1/payment_intents/{intent}/confirm",
    "/v1/payment_intents/{intent}/cancel",
    "/v1/payment_intents/{intent}/capture",
    "/v1/charges",
    "/v1/charges/{charge}",
    "/v1/refunds",
    "/v1/refunds/{refund}",
    "/v1/customers",
    "/v1/customers/{customer}",
    "/v1/customers/{customer}/payment_methods",
    "/v1/subscriptions",
    "/v1/subscriptions/{subscription_exposed_id}",
    "/v1/invoices",
    "/v1/invoices/{invoice}",
    "/v1/webhook_endpoints",
    "/v1/webhook_endpoints/{webhook_endpoint}",
    "/v1/balance",
    "/v1/payouts",
]

# SendGrid endpoints to include
SENDGRID_ENDPOINT_FILTER = [
    "/v3/mail/send",
    "/v3/templates",
    "/v3/templates/{template_id}",
    "/v3/templates/{template_id}/versions",
    "/v3/messages",
    "/v3/suppression/unsubscribes",
    "/v3/asm/groups",
    "/v3/asm/groups/{group_id}/suppressions",
    "/v3/stats",
    "/v3/verified_senders",
    "/v3/senders",
    "/v3/marketing/contacts",
    "/v3/marketing/lists",
    "/v3/marketing/singlesends",
]


class OpenAPIParser:

    def __init__(self):
        self.client = httpx.Client(timeout=30, follow_redirects=True)

    def _fetch(self, url: str) -> Optional[Dict]:
        """Fetch and parse a JSON or YAML spec from a URL."""
        try:
            logger.info(f"Fetching spec: {url}")
            resp = self.client.get(url)
            resp.raise_for_status()
            if url.endswith(".yaml") or url.endswith(".yml"):
                return yaml.safe_load(resp.text)
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def _resolve_ref(self, spec: Dict, ref: str) -> Dict:
        """Resolve a $ref string like #/components/schemas/Foo."""
        parts = ref.lstrip("#/").split("/")
        node = spec
        for part in parts:
            node = node.get(part, {})
        return node

    def _extract_parameters(self, spec: Dict, operation: Dict) -> List[APIParameter]:
        """Extract parameters from an OpenAPI operation."""
        params = []

        for p in operation.get("parameters", []):
            if "$ref" in p:
                p = self._resolve_ref(spec, p["$ref"])
            schema = p.get("schema", {})
            params.append(APIParameter(
                name=p.get("name", ""),
                required=p.get("required", False),
                type=schema.get("type", "string"),
                description=p.get("description", schema.get("description", "")),
                example=str(schema.get("example", "")),
            ))

        # Also pull from requestBody if present
        req_body = operation.get("requestBody", {})
        if req_body:
            content = req_body.get("content", {})
            schema = (
                content.get("application/json", {}).get("schema", {}) or
                content.get("application/x-www-form-urlencoded", {}).get("schema", {})
            )
            if "$ref" in schema:
                schema = self._resolve_ref(spec, schema["$ref"])
            required_fields = schema.get("required", [])
            for prop_name, prop_schema in schema.get("properties", {}).items():
                if "$ref" in prop_schema:
                    prop_schema = self._resolve_ref(spec, prop_schema["$ref"])
                params.append(APIParameter(
                    name=prop_name,
                    required=prop_name in required_fields,
                    type=prop_schema.get("type", "string"),
                    description=prop_schema.get("description", ""),
                    example=str(prop_schema.get("example", "")),
                ))
        return params[:20]

    def _operation_to_entry(
        self,
        spec: Dict,
        path: str,
        method: str,
        operation: Dict,
        platform: str,
        category: str,
        base_url: str,
    ) -> Optional[APIEntry]:
        """Convert a single OpenAPI operation to an APIEntry."""
        summary = operation.get("summary", "")
        description = operation.get("description", summary)
        if not summary and not description:
            return None

        name = summary or f"{method.upper()} {path}"
        parameters = self._extract_parameters(spec, operation)

        # Build plain explanation stub — will be enriched by structuring.py
        plain = (
            f"{method.upper()} {path} — {summary}. "
            f"{description[:300] if description else ''}"
        )

        return APIEntry(
            name=name,
            platform=platform,
            category=category,
            method=method.upper(),
            endpoint=path,
            base_url=base_url,
            auth=self._detect_auth(spec),
            parameters=parameters,
            description=description,
            plain_explanation=plain,
            doc_url="",
        )

    def _detect_auth(self, spec: Dict) -> str:
        """Best-effort auth detection from spec security schemes."""
        schemes = spec.get("components", {}).get("securitySchemes", {})
        if not schemes:
            return "See documentation"
        types = []
        for name, scheme in schemes.items():
            t = scheme.get("type", "")
            if t == "http":
                types.append(f"{scheme.get('scheme', 'bearer').title()} token")
            elif t == "apiKey":
                types.append(f"API Key ({scheme.get('in', 'header')}: {scheme.get('name', '')})")
            elif t == "oauth2":
                types.append("OAuth 2.0")
        return ", ".join(types) if types else "Bearer token"

    def _get_base_url(self, spec: Dict) -> str:
        servers = spec.get("servers", [])
        if servers:
            return servers[0].get("url", "")
        return ""

    # ── Platform-specific parsers ─────────────────────────────────────────

    def parse_twilio(self, spec: Dict, spec_url: str) -> List[APIEntry]:
        entries = []
        base_url = self._get_base_url(spec)

        # Determine category from URL
        if "messaging" in spec_url:
            category = "Messaging"
        elif "verify" in spec_url:
            category = "Verification / OTP"
        elif "lookups" in spec_url:
            category = "Phone Lookup"
        else:
            category = "Twilio"

        for path, path_item in spec.get("paths", {}).items():
            for method in ["get", "post", "put", "patch", "delete"]:
                operation = path_item.get(method)
                if not operation:
                    continue
                entry = self._operation_to_entry(
                    spec, path, method, operation, "Twilio", category, base_url
                )
                if entry:
                    entries.append(entry)
        return entries

    def parse_sendgrid(self, spec: Dict) -> List[APIEntry]:
        entries = []
        base_url = self._get_base_url(spec)

        for path, path_item in spec.get("paths", {}).items():
            # Filter to relevant endpoints only
            if not any(path.startswith(f) or path == f for f in SENDGRID_ENDPOINT_FILTER):
                continue
            for method in ["get", "post", "put", "patch", "delete"]:
                operation = path_item.get(method)
                if not operation:
                    continue
                tags = operation.get("tags", ["Email"])
                category = tags[0] if tags else "Email"
                entry = self._operation_to_entry(
                    spec, path, method, operation, "SendGrid", category, base_url
                )
                if entry:
                    entries.append(entry)
        return entries

    def parse_stripe(self, spec: Dict) -> List[APIEntry]:
        entries = []
        base_url = self._get_base_url(spec)

        for path, path_item in spec.get("paths", {}).items():
            if path not in STRIPE_ENDPOINT_FILTER:
                continue
            for method in ["get", "post", "put", "patch", "delete"]:
                operation = path_item.get(method)
                if not operation:
                    continue
                # Determine category from path
                if "payment_intent" in path:
                    category = "Payment Intents"
                elif "charge" in path:
                    category = "Charges"
                elif "refund" in path:
                    category = "Refunds"
                elif "customer" in path:
                    category = "Customers"
                elif "subscription" in path:
                    category = "Subscriptions"
                elif "invoice" in path:
                    category = "Invoices"
                elif "webhook" in path:
                    category = "Webhooks"
                else:
                    category = "Stripe"
                entry = self._operation_to_entry(
                    spec, path, method, operation, "Stripe", category, base_url
                )
                if entry:
                    entries.append(entry)
        return entries

    # ── Google Maps (REST Discovery API) ─────────────────────────────────

    def parse_google_maps(self) -> List[APIEntry]:
        """
        Google Maps doesn't have a traditional OpenAPI spec.
        We define the key endpoints manually with full detail since
        the Maps REST Discovery JSON doesn't expose full parameter docs.
        """
        entries = [
            APIEntry(
                name="Google Maps Geocoding — Address to Coordinates",
                platform="Google Maps",
                category="Geocoding",
                method="GET",
                endpoint="/maps/api/geocode/json",
                base_url="https://maps.googleapis.com",
                auth="API Key (key query parameter)",
                parameters=[
                    APIParameter(name="address", required=True, type="string", description="The street address to geocode", example="123 MG Road, Bengaluru"),
                    APIParameter(name="key", required=True, type="string", description="Your Google Maps API key"),
                    APIParameter(name="region", required=False, type="string", description="Region biasing (ccTLD format)", example="in"),
                    APIParameter(name="language", required=False, type="string", description="Language for results", example="en"),
                ],
                description="Converts a human-readable address into geographic coordinates (latitude and longitude). Supports address, component, and bounds filtering. Also supports reverse geocoding (latlng parameter instead of address). Returns structured address components, geometry, and place_id.",
                plain_explanation="Converts a street address like '123 MG Road, Bengaluru' into GPS coordinates (latitude/longitude). Used to plot addresses on maps, validate addresses, or calculate distances.",
                doc_url="https://developers.google.com/maps/documentation/geocoding",
            ),
            APIEntry(
                name="Google Maps Reverse Geocoding — Coordinates to Address",
                platform="Google Maps",
                category="Geocoding",
                method="GET",
                endpoint="/maps/api/geocode/json",
                base_url="https://maps.googleapis.com",
                auth="API Key (key query parameter)",
                parameters=[
                    APIParameter(name="latlng", required=True, type="string", description="Lat/lng to reverse geocode", example="12.9716,77.5946"),
                    APIParameter(name="key", required=True, type="string", description="Your Google Maps API key"),
                    APIParameter(name="result_type", required=False, type="string", description="Filter by address type", example="street_address"),
                ],
                description="Converts GPS coordinates (latitude, longitude) into a human-readable address. Returns structured address components including street number, route, locality, and postal code.",
                plain_explanation="Turns a GPS location into a readable street address. Useful for showing a customer's location as a proper address rather than raw coordinates.",
                doc_url="https://developers.google.com/maps/documentation/geocoding/requests-reverse-geocoding",
            ),
            APIEntry(
                name="Google Maps Distance Matrix",
                platform="Google Maps",
                category="Distance & Directions",
                method="GET",
                endpoint="/maps/api/distancematrix/json",
                base_url="https://maps.googleapis.com",
                auth="API Key (key query parameter)",
                parameters=[
                    APIParameter(name="origins", required=True, type="string", description="Starting location(s), pipe-separated", example="Mumbai"),
                    APIParameter(name="destinations", required=True, type="string", description="Destination(s), pipe-separated", example="Pune"),
                    APIParameter(name="key", required=True, type="string", description="Your Google Maps API key"),
                    APIParameter(name="mode", required=False, type="string", description="Travel mode: driving, walking, bicycling, transit", example="driving"),
                    APIParameter(name="departure_time", required=False, type="integer", description="Unix timestamp for traffic-aware estimates"),
                ],
                description="Returns travel distance and estimated time between one or more origins and destinations. Supports multiple travel modes and real-time traffic data via departure_time.",
                plain_explanation="Calculates driving/walking distance and travel time between locations. Used for showing delivery ETAs, finding nearest store, or sorting delivery routes by distance.",
                doc_url="https://developers.google.com/maps/documentation/distance-matrix",
            ),
            APIEntry(
                name="Google Maps Places Autocomplete",
                platform="Google Maps",
                category="Places",
                method="GET",
                endpoint="/maps/api/place/autocomplete/json",
                base_url="https://maps.googleapis.com",
                auth="API Key (key query parameter)",
                parameters=[
                    APIParameter(name="input", required=True, type="string", description="User-typed search string", example="123 MG"),
                    APIParameter(name="key", required=True, type="string", description="Your Google Maps API key"),
                    APIParameter(name="sessiontoken", required=False, type="string", description="UUID to group autocomplete calls into a session for billing"),
                    APIParameter(name="types", required=False, type="string", description="Filter result types: geocode, address, establishment", example="address"),
                    APIParameter(name="components", required=False, type="string", description="Restrict to country", example="country:in"),
                ],
                description="Returns place predictions as a user types, enabling real-time address autocomplete. Billed per session (not per keystroke) when sessiontoken is used.",
                plain_explanation="Powers the 'start typing an address and see suggestions' feature in forms. When a customer types their address, this suggests matching real addresses instantly.",
                doc_url="https://developers.google.com/maps/documentation/places/web-service/autocomplete",
            ),
            APIEntry(
                name="Google Maps Place Details",
                platform="Google Maps",
                category="Places",
                method="GET",
                endpoint="/maps/api/place/details/json",
                base_url="https://maps.googleapis.com",
                auth="API Key (key query parameter)",
                parameters=[
                    APIParameter(name="place_id", required=True, type="string", description="Place ID from Autocomplete or Geocoding result"),
                    APIParameter(name="key", required=True, type="string", description="Your Google Maps API key"),
                    APIParameter(name="fields", required=False, type="string", description="Comma-separated fields to return (reduces cost)", example="name,formatted_address,geometry"),
                ],
                description="Retrieves detailed information about a place using its place_id. Returns full address components, coordinates, phone number, opening hours, rating, and photos.",
                plain_explanation="Fetches full details about a specific location — its exact address, phone number, opening hours, and GPS coordinates. Used after the user selects an address suggestion from autocomplete.",
                doc_url="https://developers.google.com/maps/documentation/places/web-service/details",
            ),
        ]
        return entries

    # ── Main entrypoint ───────────────────────────────────────────────────

    def parse_all(self, platforms: list = None) -> List[APIEntry]:
        """Parse all configured OpenAPI sources. Returns list of APIEntry objects."""
        all_entries: List[APIEntry] = []
        target = set(platforms) if platforms else {"Twilio", "SendGrid", "Stripe", "Google Maps"}

        if "Twilio" in target:
            for url in OPENAPI_SOURCES["Twilio"]:
                spec = self._fetch(url)
                if spec:
                    entries = self.parse_twilio(spec, url)
                    logger.info(f"Twilio ({url.split('/')[-1]}): {len(entries)} endpoints parsed")
                    all_entries.extend(entries)

        if "SendGrid" in target:
            spec = self._fetch(OPENAPI_SOURCES["SendGrid"][0])
            if spec:
                entries = self.parse_sendgrid(spec)
                logger.info(f"SendGrid: {len(entries)} endpoints parsed")
                all_entries.extend(entries)

        if "Stripe" in target:
            spec = self._fetch(OPENAPI_SOURCES["Stripe"][0])
            if spec:
                entries = self.parse_stripe(spec)
                logger.info(f"Stripe: {len(entries)} endpoints parsed")
                all_entries.extend(entries)

        if "Google Maps" in target:
            entries = self.parse_google_maps()
            logger.info(f"Google Maps: {len(entries)} endpoints defined")
            all_entries.extend(entries)

        logger.info(f"OpenAPI parser total: {len(all_entries)} entries")
        return all_entries
